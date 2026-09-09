from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.split_local_serving_databases import (  # noqa: E402
    SplitDatabaseError,
    build_split_snapshot,
    inspect_split_plan,
)


DATASET_CODES = (
    "DAILY_ARTICLES",
    "FINANCIAL_MACRO",
    "MOLIT_TRANSACTIONS",
    "SEOUL_BUILDING_PERMITS",
)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _create_fixture(path: Path, *, fingerprint_mismatch: bool = False) -> None:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE collection_sources(
          source_id TEXT PRIMARY KEY,
          source_code TEXT NOT NULL UNIQUE,
          source_name TEXT NOT NULL,
          config_json TEXT NOT NULL CHECK(json_valid(config_json))
        );
        CREATE TABLE units(
          unit_code TEXT PRIMARY KEY,
          dimension_code TEXT NOT NULL,
          name_ko TEXT NOT NULL,
          symbol TEXT,
          metadata_json TEXT NOT NULL
        );
        CREATE TABLE regions(
          region_id TEXT PRIMARY KEY,
          canonical_name TEXT NOT NULL,
          parent_region_id TEXT REFERENCES regions(region_id)
        );
        CREATE TABLE asset_classes(
          asset_class_id TEXT PRIMARY KEY,
          code TEXT NOT NULL UNIQUE,
          name_ko TEXT NOT NULL,
          parent_id TEXT REFERENCES asset_classes(asset_class_id)
        );

        CREATE TABLE serving_daily_article_dates(
          article_date TEXT PRIMARY KEY,
          article_count INTEGER NOT NULL,
          categorized_count INTEGER NOT NULL,
          summarized_count INTEGER NOT NULL,
          last_collected_at TEXT,
          generated_at TEXT NOT NULL
        );
        CREATE TABLE serving_daily_articles(
          document_id TEXT PRIMARY KEY,
          document_version_id TEXT NOT NULL UNIQUE,
          article_date TEXT NOT NULL,
          title TEXT NOT NULL,
          published_at TEXT NOT NULL
        );
        CREATE INDEX ix_fixture_article_date
          ON serving_daily_articles(article_date,published_at DESC,document_id);
        CREATE TABLE serving_daily_article_topics(
          document_id TEXT NOT NULL REFERENCES serving_daily_articles(document_id),
          document_version_id TEXT NOT NULL REFERENCES serving_daily_articles(document_version_id),
          term_code TEXT NOT NULL,
          PRIMARY KEY(document_id,term_code)
        );
        CREATE TABLE serving_daily_article_details(
          document_id TEXT PRIMARY KEY REFERENCES serving_daily_articles(document_id),
          document_version_id TEXT NOT NULL UNIQUE REFERENCES serving_daily_articles(document_version_id),
          payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
        );

        CREATE TABLE serving_molit_completed_partitions(
          partition_key TEXT PRIMARY KEY,
          deal_month TEXT NOT NULL,
          coverage_status TEXT NOT NULL
        );
        CREATE TABLE serving_molit_current_transactions(
          transaction_key TEXT PRIMARY KEY,
          partition_key TEXT NOT NULL REFERENCES serving_molit_completed_partitions(partition_key),
          deal_year TEXT NOT NULL,
          deal_month_number TEXT NOT NULL,
          deal_amount_text TEXT NOT NULL,
          building_area_text TEXT NOT NULL
        );
        CREATE TABLE macro_series(
          macro_series_id TEXT PRIMARY KEY,
          series_code TEXT NOT NULL UNIQUE,
          series_name_ko TEXT NOT NULL,
          source_id TEXT REFERENCES collection_sources(source_id),
          unit_code TEXT NOT NULL REFERENCES units(unit_code),
          region_id TEXT REFERENCES regions(region_id),
          asset_class_id TEXT REFERENCES asset_classes(asset_class_id)
        );
        CREATE TABLE financial_macro_monthly_serving(
          series_code TEXT NOT NULL,
          source_id TEXT NOT NULL REFERENCES collection_sources(source_id),
          region_id TEXT REFERENCES regions(region_id),
          observation_month TEXT NOT NULL,
          numeric_value REAL NOT NULL,
          observation_count INTEGER NOT NULL,
          unit_code TEXT NOT NULL REFERENCES units(unit_code),
          PRIMARY KEY(series_code,observation_month)
        );
        CREATE TABLE serving_v2_building_permit_monthly(
          source_id TEXT NOT NULL,
          event_month TEXT NOT NULL,
          event_type TEXT NOT NULL,
          district_name TEXT NOT NULL,
          asset_type TEXT NOT NULL,
          scope_status TEXT NOT NULL,
          construction_action TEXT NOT NULL,
          permit_count INTEGER NOT NULL,
          total_floor_area_m2 REAL NOT NULL,
          missing_area_count INTEGER NOT NULL,
          invalid_area_count INTEGER NOT NULL,
          PRIMARY KEY(source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action)
        );
        CREATE TABLE serving_v2_building_permit_hot_detail(
          source_id TEXT NOT NULL,
          source_record_key TEXT NOT NULL,
          parcel_address TEXT,
          PRIMARY KEY(source_id,source_record_key)
        );

        CREATE TABLE serving_dataset_freshness(
          dataset_code TEXT PRIMARY KEY,
          source_code TEXT NOT NULL,
          source_as_of_date TEXT NOT NULL,
          generated_at TEXT NOT NULL,
          source_status_code TEXT NOT NULL,
          source_row_count INTEGER NOT NULL,
          serving_row_count INTEGER NOT NULL,
          content_sha256 TEXT NOT NULL,
          metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json))
        );
        CREATE TABLE serving_row_fingerprints(
          dataset_code TEXT NOT NULL,
          table_name TEXT NOT NULL,
          row_key_json TEXT NOT NULL CHECK(json_valid(row_key_json)),
          content_sha256 TEXT NOT NULL,
          state_code TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(dataset_code,table_name,row_key_json)
        );
        """
    )
    connection.executemany(
        "INSERT INTO collection_sources VALUES(?,?,?,?)",
        [
            ("src-news", "NEWS", "뉴스", "{}"),
            ("src-macro", "MACRO", "한국은행", "{}"),
            ("src-unused", "UNUSED", "미사용 코드행", "{}"),
        ],
    )
    connection.execute("INSERT INTO units VALUES('PCT','RATE','퍼센트','%','{}')")
    connection.executemany(
        "INSERT INTO regions VALUES(?,?,?)",
        [("kr", "대한민국", None), ("seoul", "서울특별시", "kr")],
    )
    connection.executemany(
        "INSERT INTO asset_classes VALUES(?,?,?,?)",
        [("cre", "CRE", "상업용 부동산", None), ("office", "OFFICE", "오피스", "cre")],
    )
    connection.execute(
        "INSERT INTO serving_daily_article_dates VALUES('2026-09-08',1,1,1,'2026-09-08T09:00:00Z','2026-09-08T09:01:00Z')"
    )
    connection.execute(
        "INSERT INTO serving_daily_articles VALUES('doc-1','ver-1','2026-09-08','기사','2026-09-08T08:00:00Z')"
    )
    connection.execute(
        "INSERT INTO serving_daily_article_topics VALUES('doc-1','ver-1','OFFICE')"
    )
    connection.execute(
        "INSERT INTO serving_daily_article_details VALUES('doc-1','ver-1','{\"id\":\"doc-1\"}')"
    )
    connection.execute(
        "INSERT INTO serving_molit_completed_partitions VALUES('part-1','2026-08','COMPLETE_FULL_SNAPSHOT')"
    )
    connection.execute(
        "INSERT INTO serving_molit_current_transactions VALUES('tx-1','part-1','2026','08','1000','3301')"
    )
    connection.execute(
        "INSERT INTO macro_series VALUES('macro-1','BOK_BASE_RATE_MONTHLY','기준금리','src-macro','PCT','kr','office')"
    )
    connection.execute(
        "INSERT INTO financial_macro_monthly_serving VALUES('BOK_BASE_RATE_MONTHLY','src-macro','kr','2026-08',0,1,'PCT')"
    )
    connection.execute(
        """INSERT INTO serving_v2_building_permit_monthly VALUES(
          'src_seoul_building_permit','2026-08','PERMIT','강남구','OFFICE','IN_SCOPE','NEW_SUPPLY',1,0,0,0
        )"""
    )
    connection.execute(
        "INSERT INTO serving_v2_building_permit_hot_detail VALUES('src_seoul_building_permit','permit-1','서울')"
    )
    for code in DATASET_CODES:
        connection.execute(
            "INSERT INTO serving_dataset_freshness VALUES(?,?,?,?,?,?,?,?,?)",
            (code, f"source-{code}", "2026-09-08", "2026-09-08T09:00:00Z", "READY", 1, 1, "a" * 64, "{}"),
        )
    table_codes = {
        "DAILY_ARTICLES": (
            "serving_daily_article_dates",
            "serving_daily_articles",
            "serving_daily_article_topics",
            "serving_daily_article_details",
        ),
        "FINANCIAL_MACRO": ("financial_macro_monthly_serving", "macro_series"),
        "MOLIT_TRANSACTIONS": (
            "serving_molit_current_transactions",
            "serving_molit_completed_partitions",
        ),
        "SEOUL_BUILDING_PERMITS": ("serving_v2_building_permit_monthly",),
    }
    for code, tables in table_codes.items():
        for table in tables:
            connection.execute(
                "INSERT INTO serving_row_fingerprints VALUES(?,?,?,?,?,?)",
                (code, table, json.dumps({"table": table}), "b" * 64, "ACTIVE", "2026-09-08T09:00:00Z"),
            )
    if fingerprint_mismatch:
        connection.execute(
            "DELETE FROM serving_row_fingerprints WHERE table_name='serving_daily_article_topics'"
        )
    connection.commit()
    connection.close()


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def test_plan_is_read_only_and_resolves_recursive_small_parent_tables(tmp_path: Path) -> None:
    source = tmp_path / "market.db"
    output = tmp_path / "split"
    _create_fixture(source)
    before = _sha256(source)

    plan = inspect_split_plan(source, output)

    assert plan["mode"] == "PLAN"
    assert plan["willWrite"] is False
    assert not output.exists()
    assert _sha256(source) == before
    news_tables = {item["name"] for item in plan["outputs"]["news"]["tables"]}
    timeseries_tables = {item["name"] for item in plan["outputs"]["timeseries"]["tables"]}
    assert news_tables == {
        "serving_daily_article_dates",
        "serving_daily_articles",
        "serving_daily_article_topics",
        "serving_daily_article_details",
        "serving_dataset_freshness",
        "serving_row_fingerprints",
    }
    assert {"collection_sources", "units", "regions", "asset_classes"} <= timeseries_tables
    assert any(
        item["table"] == "serving_v2_building_permit_hot_detail"
        for item in plan["intentionallyExcluded"]
    )


def test_apply_builds_two_independent_parity_checked_databases_and_atomic_pointer(tmp_path: Path) -> None:
    source = tmp_path / "market.db"
    output = tmp_path / "split"
    _create_fixture(source)
    before = _sha256(source)
    fixed = datetime(2026, 9, 8, 9, 30, tzinfo=timezone.utc)

    manifest = build_split_snapshot(source, output, now=fixed, nonce="fixture1")

    assert _sha256(source) == before
    assert manifest["complete"] is True
    assert manifest["crossOutput"]["sourceRowParity"] is True
    snapshot = output / manifest["currentSnapshot"]
    assert snapshot.is_dir()
    assert (snapshot / "news.db").is_file()
    assert (snapshot / "timeseries.db").is_file()
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["currentSnapshot"] == snapshot.name
    assert json.loads((snapshot / "snapshot-manifest.json").read_text(encoding="utf-8"))["complete"] is True

    with _open_read_only(snapshot / "news.db") as news:
        assert news.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert news.execute("PRAGMA foreign_key_check").fetchall() == []
        assert news.execute("SELECT count(*) FROM serving_daily_articles").fetchone()[0] == 1
        assert news.execute("SELECT dataset_code FROM serving_dataset_freshness").fetchall() == [("DAILY_ARTICLES",)]
        with pytest.raises(sqlite3.OperationalError):
            news.execute("SELECT * FROM financial_macro_monthly_serving").fetchall()

    with _open_read_only(snapshot / "timeseries.db") as timeseries:
        assert timeseries.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert timeseries.execute("PRAGMA foreign_key_check").fetchall() == []
        assert timeseries.execute(
            "SELECT numeric_value FROM financial_macro_monthly_serving"
        ).fetchone()[0] == 0
        assert timeseries.execute(
            "SELECT total_floor_area_m2 FROM serving_v2_building_permit_monthly"
        ).fetchone()[0] == 0
        assert timeseries.execute("SELECT count(*) FROM collection_sources").fetchone()[0] == 3
        assert timeseries.execute(
            "SELECT count(*) FROM sqlite_schema WHERE type='table' AND name='serving_v2_building_permit_hot_detail'"
        ).fetchone()[0] == 0
        assert {row[0] for row in timeseries.execute("SELECT dataset_code FROM serving_dataset_freshness")} == {
            "FINANCIAL_MACRO",
            "MOLIT_TRANSACTIONS",
            "SEOUL_BUILDING_PERMITS",
        }

    for output_report in manifest["outputs"].values():
        assert output_report["integrity"] == "ok"
        assert output_report["foreignKeyViolations"] == 0
        assert output_report["allTableParity"] is True
        assert all(table["parity"] for table in output_report["tables"].values())


def test_existing_snapshot_is_never_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "market.db"
    output = tmp_path / "split"
    _create_fixture(source)
    fixed = datetime(2026, 9, 8, 9, 30, tzinfo=timezone.utc)
    first = build_split_snapshot(source, output, now=fixed, nonce="same-snapshot")
    manifest_before = (output / "manifest.json").read_bytes()
    news_before = (output / first["currentSnapshot"] / "news.db").read_bytes()

    with pytest.raises(FileExistsError, match="overwrite"):
        build_split_snapshot(source, output, now=fixed, nonce="same-snapshot")

    assert (output / "manifest.json").read_bytes() == manifest_before
    assert (output / first["currentSnapshot"] / "news.db").read_bytes() == news_before


def test_missing_active_fingerprint_fails_closed_without_creating_output(tmp_path: Path) -> None:
    source = tmp_path / "market.db"
    output = tmp_path / "split"
    _create_fixture(source, fingerprint_mismatch=True)

    with pytest.raises(SplitDatabaseError, match="active fingerprints"):
        inspect_split_plan(source, output)

    assert not output.exists()
