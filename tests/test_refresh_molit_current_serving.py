from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.refresh_molit_current_serving import (  # noqa: E402
    DATASET_CODE,
    EXPECTED_SEOUL_DISTRICTS,
    TRANSACTION_TABLE,
    apply_migration,
    refresh_molit_current_serving,
)


BASE_SCHEMA = """
CREATE TABLE schema_meta(
  schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE TABLE collection_sources(source_id TEXT PRIMARY KEY,source_code TEXT NOT NULL);
CREATE TABLE collection_jobs(job_id TEXT PRIMARY KEY,source_id TEXT NOT NULL);
CREATE TABLE collection_runs(
  run_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,query_rendered TEXT,
  completed_at TEXT,created_at TEXT NOT NULL,status_code TEXT NOT NULL,
  discovered_count INTEGER
);
CREATE TABLE source_documents(
  document_id TEXT PRIMARY KEY,external_document_key TEXT
);
CREATE TABLE document_versions(
  document_version_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,metadata_json TEXT NOT NULL
);
CREATE TABLE run_documents(
  run_id TEXT NOT NULL,document_version_id TEXT NOT NULL,result_rank INTEGER,
  PRIMARY KEY(run_id,document_version_id)
);
CREATE TABLE serving_dataset_freshness(
  dataset_code TEXT PRIMARY KEY,source_code TEXT NOT NULL,source_as_of_date TEXT NOT NULL,
  generated_at TEXT NOT NULL,source_status_code TEXT NOT NULL,source_row_count INTEGER NOT NULL,
  serving_row_count INTEGER NOT NULL,content_sha256 TEXT NOT NULL,metadata_json TEXT NOT NULL
);
CREATE TABLE serving_row_fingerprints(
  dataset_code TEXT NOT NULL,table_name TEXT NOT NULL,row_key_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,state_code TEXT NOT NULL,updated_at TEXT NOT NULL,
  PRIMARY KEY(dataset_code,table_name,row_key_json)
);
INSERT INTO collection_sources VALUES ('molit','MOLIT_REAL_TRANSACTION');
"""


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(BASE_SCHEMA)
    apply_migration(conn)
    return conn


def record(
    *,
    lot: str = "100-1",
    amount: str = "100,000",
    cancellation_day: str = "",
    day: str = "15",
) -> dict[str, str]:
    return {
        "sggCd": "11680",
        "sggNm": "강남구",
        "umdNm": "역삼동",
        "jibun": lot,
        "buildingUse": "업무",
        "buildingType": "일반",
        "buildingAr": "4000.5",
        "plottageAr": "500",
        "floor": "10",
        "buildYear": "2005",
        "landUse": "상업지역",
        "buyerGbn": "법인",
        "slerGbn": "법인",
        "shareDealingType": "",
        "dealingGbn": "중개거래",
        "estateAgentSggNm": "서울 강남구",
        "dealAmount": amount,
        "dealYear": "2026",
        "dealMonth": "7",
        "dealDay": day,
        "cdealDay": cancellation_day,
        "cdealType": "",
    }


def add_run(
    conn: sqlite3.Connection,
    run_id: str,
    completed_at: str,
    records: list[dict[str, str]],
    *,
    discovered_count: int | None = None,
    status: str = "COMPLETED",
    district: str = "11680",
    month: str = "202607",
) -> None:
    job_id = f"job-{run_id}"
    conn.execute("INSERT INTO collection_jobs VALUES (?, 'molit')", (job_id,))
    conn.execute(
        """INSERT INTO collection_runs(
             run_id,job_id,query_rendered,completed_at,created_at,status_code,discovered_count
           ) VALUES (?,?,?,?,?,?,?)""",
        (
            run_id,
            job_id,
            f"MOLIT RTMS NRG trade; LAWD_CD={district}; DEAL_YMD={month}; identity=record-hash-occurrence-v2",
            completed_at,
            completed_at,
            status,
            len(records) if discovered_count is None else discovered_count,
        ),
    )
    for index, api_record in enumerate(records, 1):
        document_id = f"document-{run_id}-{index}"
        version_id = f"version-{run_id}-{index}"
        conn.execute("INSERT INTO source_documents VALUES (?,?)", (document_id, f"payload-{run_id}-{index}"))
        conn.execute(
            "INSERT INTO document_versions VALUES (?,?,?)",
            (
                version_id,
                document_id,
                json.dumps(
                    {"api_record": api_record, "duplicate_occurrence": 1},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        conn.execute("INSERT INTO run_documents VALUES (?,?,?)", (run_id, version_id, index))
    conn.commit()


def materialize(conn: sqlite3.Connection, timestamp: str) -> dict:
    result = refresh_molit_current_serving(conn, generated_at=timestamp)
    conn.commit()
    return result


def add_empty_companion_districts(conn: sqlite3.Connection, completed_at: str) -> None:
    for district in sorted(EXPECTED_SEOUL_DISTRICTS - {"11680"}):
        add_run(
            conn,
            f"empty-{district}",
            completed_at,
            [],
            discovered_count=0,
            district=district,
        )


def test_amount_correction_replaces_value_at_stable_identity_without_deleting_raw_history() -> None:
    conn = database()
    add_run(conn, "initial", "2026-08-01T00:00:00Z", [record(amount="100,000")])
    add_empty_companion_districts(conn, "2026-08-01T00:00:00Z")
    materialize(conn, "2026-08-01T01:00:00Z")
    before = conn.execute(
        f"SELECT transaction_key,deal_amount_text FROM {TRANSACTION_TABLE}"
    ).fetchone()
    fingerprint_before = conn.execute(
        """SELECT content_sha256 FROM serving_row_fingerprints
            WHERE dataset_code=? AND table_name=?""",
        (DATASET_CODE, TRANSACTION_TABLE),
    ).fetchone()[0]

    add_run(conn, "corrected", "2026-08-02T00:00:00Z", [record(amount="125,000")], discovered_count=1)
    materialize(conn, "2026-08-02T01:00:00Z")
    after = conn.execute(
        f"SELECT transaction_key,deal_amount_text FROM {TRANSACTION_TABLE}"
    ).fetchone()
    fingerprint_after = conn.execute(
        """SELECT content_sha256 FROM serving_row_fingerprints
            WHERE dataset_code=? AND table_name=? AND state_code='ACTIVE'""",
        (DATASET_CODE, TRANSACTION_TABLE),
    ).fetchone()[0]

    assert before == (after[0], "100,000")
    assert after[1] == "125,000"
    assert fingerprint_after != fingerprint_before
    assert conn.execute("SELECT count(*) FROM source_documents").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM document_versions").fetchone()[0] == 2


def test_linked_cancellation_retires_prior_active_identity() -> None:
    conn = database()
    add_run(conn, "initial", "2026-08-01T00:00:00Z", [record()])
    add_empty_companion_districts(conn, "2026-08-01T00:00:00Z")
    materialize(conn, "2026-08-01T01:00:00Z")
    row_key = conn.execute(
        """SELECT row_key_json FROM serving_row_fingerprints
            WHERE dataset_code=? AND table_name=? AND state_code='ACTIVE'""",
        (DATASET_CODE, TRANSACTION_TABLE),
    ).fetchone()[0]

    add_run(conn, "cancelled", "2026-08-02T00:00:00Z", [record(cancellation_day="20260802")])
    result = materialize(conn, "2026-08-02T01:00:00Z")

    assert conn.execute(f"SELECT count(*) FROM {TRANSACTION_TABLE}").fetchone()[0] == 0
    assert conn.execute(
        """SELECT state_code FROM serving_row_fingerprints
            WHERE dataset_code=? AND table_name=? AND row_key_json=?""",
        (DATASET_CODE, TRANSACTION_TABLE, row_key),
    ).fetchone()[0] == "RETIRED"
    assert result["retiredRows"] == 1


def test_latest_completed_zero_discovery_authoritatively_clears_partition() -> None:
    conn = database()
    add_run(conn, "initial", "2026-08-01T00:00:00Z", [record(lot="1"), record(lot="2")])
    add_run(conn, "empty", "2026-08-03T00:00:00Z", [], discovered_count=0)
    materialize(conn, "2026-08-03T01:00:00Z")

    assert conn.execute(f"SELECT count(*) FROM {TRANSACTION_TABLE}").fetchone()[0] == 0
    assert conn.execute(
        """SELECT latest_run_id,discovered_count,linked_document_count,
                  active_record_count,coverage_status
             FROM serving_molit_completed_partitions"""
    ).fetchone() == ("empty", 0, 0, 0, "COMPLETE_EMPTY")


def test_incomplete_later_run_is_ignored() -> None:
    conn = database()
    add_run(conn, "complete", "2026-08-01T00:00:00Z", [record(amount="100,000")])
    add_empty_companion_districts(conn, "2026-08-01T00:00:00Z")
    add_run(conn, "partial", "2026-08-04T00:00:00Z", [record(amount="999,000")], status="PARTIAL")
    materialize(conn, "2026-08-04T01:00:00Z")

    assert conn.execute(f"SELECT deal_amount_text FROM {TRANSACTION_TABLE}").fetchone()[0] == "100,000"
    assert conn.execute(
        "SELECT latest_run_id FROM serving_molit_completed_partitions"
    ).fetchone()[0] == "complete"


def test_change_only_56_to_1_overlay_keeps_55_unchanged_rows() -> None:
    conn = database()
    initial = [record(lot=str(index), amount=f"{100_000 + index:,}") for index in range(56)]
    add_run(conn, "full-56", "2026-08-01T00:00:00Z", initial, discovered_count=56)
    add_empty_companion_districts(conn, "2026-08-01T00:00:00Z")
    add_run(
        conn,
        "change-only-1",
        "2026-08-05T00:00:00Z",
        [record(lot="0", amount="777,000")],
        discovered_count=56,
    )
    result = materialize(conn, "2026-08-05T01:00:00Z")

    assert conn.execute(f"SELECT count(*) FROM {TRANSACTION_TABLE}").fetchone()[0] == 56
    assert conn.execute(
        f"SELECT deal_amount_text FROM {TRANSACTION_TABLE} WHERE api_payload_json LIKE '%\"jibun\":\"0\"%'"
    ).fetchone()[0] == "777,000"
    assert conn.execute(
        """SELECT discovered_count,linked_document_count,active_record_count,coverage_status
             FROM serving_molit_completed_partitions WHERE district_code='11680'"""
    ).fetchone() == (56, 1, 56, "COMPLETE_BASELINE_WITH_CHANGES")
    assert result["metadata"]["coverageCaveatPartitionCount"] == 0
    freshness = json.loads(conn.execute(
        "SELECT metadata_json FROM serving_dataset_freshness WHERE dataset_code=?",
        (DATASET_CODE,),
    ).fetchone()[0])
    assert freshness["coverageByMonth"] == [{
        "month": "2026-07",
        "expectedPartitionCount": 25,
        "missingPartitionCount": 0,
        "completeMonth": True,
        "partitionCount": 25,
        "availablePartitionCount": 25,
        "unavailablePartitionCount": 0,
        "emptyPartitionCount": 24,
        "discoveredCount": 56,
        "linkedDocumentCount": 1,
        "activeRecordCount": 56,
    }]


def test_change_only_partition_without_baseline_is_unavailable_and_not_served() -> None:
    conn = database()
    add_run(
        conn,
        "change-only-without-baseline",
        "2026-08-05T00:00:00Z",
        [record(lot="0", amount="777,000")],
        discovered_count=56,
    )
    result = materialize(conn, "2026-08-05T01:00:00Z")

    assert conn.execute(f"SELECT count(*) FROM {TRANSACTION_TABLE}").fetchone()[0] == 0
    assert conn.execute(
        """SELECT discovered_count,linked_document_count,active_record_count,coverage_status
             FROM serving_molit_completed_partitions"""
    ).fetchone() == (56, 1, None, "UNAVAILABLE_NO_BASELINE")
    assert result["status"] == "PARTIAL_COVERAGE"
    assert result["metadata"]["completeMonthCount"] == 0
    assert result["metadata"]["missingHistoricalMonths"] == ["2026-07"]


def test_exactly_25_authoritative_district_partitions_make_one_ready_month() -> None:
    conn = database()
    for index, district in enumerate(sorted(EXPECTED_SEOUL_DISTRICTS), 1):
        add_run(
            conn,
            f"district-{district}",
            f"2026-08-01T00:{index:02d}:00Z",
            [record(lot=f"{district}-1")],
            district=district,
        )
    result = materialize(conn, "2026-08-01T01:00:00Z")

    assert result["status"] == "READY"
    assert result["activeRecords"] == 25
    assert result["metadata"]["expectedDistrictCount"] == 25
    assert result["metadata"]["completeMonthCount"] == 1
    assert result["metadata"]["coverageComplete"] is True
    assert result["metadata"]["availableFrom"] == "2026-07"
    assert result["metadata"]["availableThrough"] == "2026-07"
    assert conn.execute(
        "SELECT source_status_code FROM serving_dataset_freshness WHERE dataset_code=?",
        (DATASET_CODE,),
    ).fetchone()[0] == "READY"


def test_online_pulse_query_reads_only_the_complete_projection() -> None:
    conn = database()
    for index, district in enumerate(sorted(EXPECTED_SEOUL_DISTRICTS), 1):
        add_run(
            conn,
            f"query-{district}",
            f"2026-08-01T00:{index:02d}:00Z",
            [record(lot=f"{district}-query")],
            district=district,
        )
    materialize(conn, "2026-08-01T01:00:00Z")

    source = (ROOT / "web" / "src" / "lib" / "server" / "quantitative-market-pulse.ts").read_text(encoding="utf-8")
    match = re.search(r"const QUERY = `(.*?)`;", source, re.DOTALL)
    assert match is not None
    payload = json.loads(conn.execute(match.group(1)).fetchone()[0])

    assert payload["asOfPeriod"] == "2026-07"
    assert payload["trend"][-1]["transactionCount"] == 25
    assert payload["coverage"] == {
        "expectedDistrictCount": 25,
        "observedMonthCount": 1,
        "completeMonthCount": 1,
        "returnedMonthCount": 1,
        "excludedMonthCount": 0,
        "coverageComplete": True,
    }
    assert "document_versions" not in match.group(1)
    assert "collection_runs" not in match.group(1)
