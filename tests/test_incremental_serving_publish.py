from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.incremental_serving_publish import (
    _delete_derived_row,
    apply_remote_serving_bootstrap,
    canonical_json,
    publish_snapshot,
    sha256_json,
    snapshot_dataset,
)


def remote_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
      CREATE TABLE serving_dataset_freshness(
        dataset_code TEXT PRIMARY KEY,source_code TEXT,source_as_of_date TEXT,generated_at TEXT,
        source_status_code TEXT,source_row_count INTEGER,serving_row_count INTEGER,
        content_sha256 TEXT,metadata_json TEXT);
      CREATE TABLE serving_row_fingerprints(
        dataset_code TEXT,table_name TEXT,row_key_json TEXT,content_sha256 TEXT,
        state_code TEXT,updated_at TEXT,PRIMARY KEY(dataset_code,table_name,row_key_json));
      CREATE TABLE financial_macro_monthly_serving(
        series_code TEXT,observation_month TEXT,numeric_value REAL,
        PRIMARY KEY(series_code,observation_month));
    """)
    return conn


def snapshot(value: float, *, metadata: dict | None = None) -> dict:
    key = canonical_json({"observation_month": "2026-08", "series_code": "A"})
    row_hash = sha256_json({"numeric_value": value})
    return {
        "datasetCode": "FINANCIAL_MACRO",
        "tables": {
            "financial_macro_monthly_serving": {
                "columns": ["series_code", "observation_month", "numeric_value"],
                "pk": ["series_code", "observation_month"],
                "rows": {key: {"values": ("A", "2026-08", value), "hash": row_hash}},
            }
        },
        "rowCount": 1,
        "sourceRowCount": 1,
        "servingRowCount": 1,
        "sourceAsOfDate": "2026-09-08",
        "contentSha256": sha256_json([value]),
        "localMetadataJson": json.dumps(metadata or {"availableThrough": "2026-08"}),
    }


def test_same_row_count_content_change_is_upserted() -> None:
    conn = remote_db()
    first = publish_snapshot(conn, snapshot(1.0), source_code="FINANCIAL_MARKETS")
    conn.commit()
    second = publish_snapshot(conn, snapshot(2.0), source_code="FINANCIAL_MARKETS")
    conn.commit()
    assert first["changedRows"] == 1
    assert second["changedRows"] == 1
    assert conn.execute("SELECT numeric_value FROM financial_macro_monthly_serving").fetchone()[0] == 2.0


def test_unchanged_dataset_uses_freshness_fast_path() -> None:
    conn = remote_db()
    item = snapshot(1.0)
    publish_snapshot(conn, item, source_code="FINANCIAL_MARKETS")
    conn.commit()
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    newer = snapshot(1.0, metadata={"availableThrough": "2026-09"})
    newer["sourceAsOfDate"] = "2026-09-09"
    result = publish_snapshot(conn, newer, source_code="FINANCIAL_MARKETS")
    assert result == {
        "status": "UNCHANGED", "datasetCode": "FINANCIAL_MACRO",
        "changedRows": 0, "metadataUpdated": True, "remotePending": False,
    }
    stored = conn.execute(
        "SELECT source_as_of_date,metadata_json FROM serving_dataset_freshness"
    ).fetchone()
    assert stored[0] == "2026-09-09"
    assert json.loads(stored[1])["availableThrough"] == "2026-09"
    publish_sql = "\n".join(statements)
    assert "serving_row_fingerprints" not in publish_sql
    assert "INSERT INTO \"financial_macro_monthly_serving\"" not in publish_sql


def test_materializer_metadata_is_preserved_at_top_level() -> None:
    conn = remote_db()
    publish_snapshot(conn, snapshot(1.0, metadata={"availableThrough": "2026-08", "dateRule": "SOURCE"}), source_code="FINANCIAL_MARKETS")
    conn.commit()
    stored = json.loads(conn.execute("SELECT metadata_json FROM serving_dataset_freshness").fetchone()[0])
    assert stored["availableThrough"] == "2026-08"
    assert stored["dateRule"] == "SOURCE"
    assert stored["publisherVersion"] == "content-aware-v1"


class FailOnFreshness:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def execute(self, sql, args=None):
        if sql.startswith("INSERT INTO \"serving_dataset_freshness\""):
            raise RuntimeError("injected")
        return self.conn.execute(sql, args or [])


def test_mid_publish_failure_can_rollback_previous_dataset() -> None:
    conn = remote_db()
    publish_snapshot(conn, snapshot(1.0), source_code="FINANCIAL_MARKETS")
    conn.commit()
    conn.execute("BEGIN")
    try:
        publish_snapshot(FailOnFreshness(conn), snapshot(2.0), source_code="FINANCIAL_MARKETS")
    except RuntimeError:
        conn.rollback()
    assert conn.execute("SELECT numeric_value FROM financial_macro_monthly_serving").fetchone()[0] == 1.0
    assert conn.execute("SELECT content_sha256 FROM serving_dataset_freshness").fetchone()[0] == snapshot(1.0)["contentSha256"]


def test_additive_bootstrap_has_no_security_or_drop(tmp_path: Path) -> None:
    migration = tmp_path / "002.sql"
    migration.write_text("CREATE TABLE IF NOT EXISTS serving_x(id TEXT PRIMARY KEY);\n", encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    assert apply_remote_serving_bootstrap(conn, migration) == 1
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='serving_x'").fetchone()[0] == "serving_x"


def test_repository_bootstrap_creates_only_approved_serving_schema() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT,updated_at TEXT)")
    count = apply_remote_serving_bootstrap(conn)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert count >= 8
    assert "serving_dataset_freshness" in names
    assert "serving_daily_article_details" in names
    assert "serving_v2_building_permit_monthly" in names
    assert "serving_molit_current_transactions" in names
    assert not any(name.startswith("dashboard_access_") for name in names)


def test_derived_retirement_uses_exact_key_delete() -> None:
    conn = remote_db()
    publish_snapshot(conn, snapshot(1.0), source_code="FINANCIAL_MARKETS")
    conn.commit()
    empty = snapshot(1.0)
    empty["tables"]["financial_macro_monthly_serving"]["rows"] = {}
    empty["rowCount"] = empty["sourceRowCount"] = empty["servingRowCount"] = 0
    empty["contentSha256"] = sha256_json([])
    result = publish_snapshot(conn, empty, source_code="FINANCIAL_MARKETS")
    conn.commit()
    assert result["retiredRows"] == 1
    assert conn.execute("SELECT count(*) FROM financial_macro_monthly_serving").fetchone()[0] == 0
    assert conn.execute("SELECT state_code FROM serving_row_fingerprints").fetchone()[0] == "RETIRED"


def test_molit_materializer_fingerprint_keys_are_publisher_compatible(tmp_path: Path) -> None:
    database = tmp_path / "molit.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT,updated_at TEXT)")
    apply_remote_serving_bootstrap(conn)
    conn.execute(
        """INSERT INTO serving_molit_completed_partitions VALUES(
             '11680:2026-07','11680','2026-07','run-1','2026-08-01T00:00:00Z',1,1,1,
             'COMPLETE_FULL_SNAPSHOT','2026-09-08T00:00:00Z')"""
    )
    payload = canonical_json({"dealAmount": "100,000"})
    natural_key = canonical_json({"districtCode": "11680", "dealMonth": "2026-07", "record": {"x": 1}})
    transaction_key = __import__("hashlib").sha256(natural_key.encode()).hexdigest()
    conn.execute(
        """INSERT INTO serving_molit_current_transactions VALUES(
             ?,?,'11680:2026-07','run-1','doc-1','dv-1',?,?,1,'11680','강남구','역삼동',
             '업무시설','100','100,000','2026','7','15','2026-09-08T00:00:00Z')""",
        (transaction_key, natural_key, payload, sha256_json({"payload": payload})),
    )
    partition_fp_key = canonical_json({"dealMonth": "2026-07", "districtCode": "11680"})
    conn.executemany(
        "INSERT INTO serving_row_fingerprints VALUES('MOLIT_TRANSACTIONS',?,?,?,'ACTIVE','2026-09-08T00:00:00Z')",
        [
            ("serving_molit_completed_partitions", partition_fp_key, "a" * 64),
            ("serving_molit_current_transactions", natural_key, "b" * 64),
        ],
    )
    conn.execute(
        """INSERT INTO serving_dataset_freshness VALUES(
             'MOLIT_TRANSACTIONS','MOLIT_REAL_TRANSACTION','2026-08-01','2026-09-08T00:00:00Z',
             'READY',1,2,?,'{"coverageComplete":false,"missingHistoricalMonths":["2026-06"]}')""",
        ("c" * 64,),
    )
    conn.commit()
    result = snapshot_dataset(conn, "MOLIT_TRANSACTIONS")
    assert result["rowCount"] == 2
    assert result["contentSha256"] == "c" * 64
    assert json.loads(result["localMetadataJson"])["coverageComplete"] is False
    conn.close()


def test_molit_retirement_derives_exact_storage_keys() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
      CREATE TABLE serving_molit_completed_partitions(
        partition_key TEXT PRIMARY KEY,district_code TEXT,deal_month TEXT);
      CREATE TABLE serving_molit_current_transactions(
        transaction_key TEXT PRIMARY KEY,transaction_key_json TEXT);
    """)
    natural_key = canonical_json({"districtCode": "11680", "dealMonth": "2026-07", "record": {"x": 1}})
    transaction_key = __import__("hashlib").sha256(natural_key.encode()).hexdigest()
    conn.execute("INSERT INTO serving_molit_completed_partitions VALUES('11680:2026-07','11680','2026-07')")
    conn.execute("INSERT INTO serving_molit_current_transactions VALUES(?,?)", (transaction_key, natural_key))
    _delete_derived_row(conn, "serving_molit_current_transactions", ("transaction_key",), natural_key)
    _delete_derived_row(
        conn, "serving_molit_completed_partitions", ("partition_key",),
        canonical_json({"dealMonth": "2026-07", "districtCode": "11680"}),
    )
    assert conn.execute("SELECT count(*) FROM serving_molit_current_transactions").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM serving_molit_completed_partitions").fetchone()[0] == 0
