from __future__ import annotations

from pathlib import Path
import sqlite3

from collector.building_permit_store import (
    complete_snapshot,
    create_snapshot,
    ensure_source,
    store_seoul_page,
)

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "db/v2/migrations/3.6.0_building_permits.sqlite.sql"


def database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL,updated_at TEXT);
        INSERT INTO schema_meta VALUES('schema_version','3.5.0','2026');
        CREATE TABLE collection_sources(
          source_id TEXT PRIMARY KEY,source_code TEXT NOT NULL UNIQUE,source_name TEXT NOT NULL,
          source_kind TEXT NOT NULL,base_url TEXT,authority_tier INTEGER NOT NULL DEFAULT 4,
          collection_policy TEXT NOT NULL,policy_checked_at TEXT,config_json TEXT NOT NULL DEFAULT '{}',
          is_active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT '2026'
        );
        """
    )
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return conn


def raw(key: str, use: str, name: str = "빌딩", area: float = 1000, hh: int = 0) -> dict:
    return {
        "PRMSN_LDGR_SN": key,
        "SGG_CD_NM": "서울특별시 강남구",
        "STDG_CD_NM": "역삼동",
        "PLAT_PLC": f"서울특별시 강남구 역삼동 {key}",
        "BLDG_NM": name,
        "ARCH_SE_CD_NM": "신축",
        "MN_USG_CD_NM": use,
        "GFA": area,
        "HH_CNT": hh,
        "HO_CNT": 0,
        "FML_CNT": 0,
        "ARCH_PRMSN_YMD": "2025-01-02",
    }


def test_page_store_is_resumable_versioned_and_exclusion_auditable(tmp_path: Path) -> None:
    conn = database(tmp_path / "permit.db")
    try:
        source_id = ensure_source(conn, "SEOUL_BUILDING_PERMIT")
        snapshot_id = create_snapshot(conn, source_id, "PILOT", 1000, "2026-09-02T00:00:00Z")
        rows = [
            raw("1", "업무시설", area=10000),
            raw("2", "공동주택", hh=20),
            raw("3", "방송통신시설", name="방송국"),
            raw("4", "종교시설"),
        ]
        first = store_seoul_page(conn, snapshot_id, source_id, rows, 1, 0)
        assert first.fetched == 4
        assert first.stored == 2
        assert first.excluded == 2
        assert conn.execute("SELECT count(*) FROM building_permit_record_versions").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM building_permit_exclusion_summary").fetchone()[0] == 2
        assert conn.execute("SELECT sum(permit_count) FROM building_permit_exclusion_summary").fetchone()[0] == 2

        # Replaying the same page does not duplicate content versions or memberships.
        replay = store_seoul_page(conn, snapshot_id, source_id, rows, 1, 0)
        assert replay.stored == 2
        assert conn.execute("SELECT count(*) FROM building_permit_record_versions").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM building_permit_snapshot_records").fetchone()[0] == 2

        complete_snapshot(conn, snapshot_id, source_total=4, fetched=4, stored=2,
                          excluded=2, request_count=1, last_page=1,
                          classification_counts={"IN_SCOPE": 1, "REVIEW_DATA_CENTER": 1})
        assert conn.execute("SELECT status_code FROM building_permit_snapshots").fetchone()[0] == "COMPLETED"
        assert conn.execute("SELECT count(*) FROM v_current_cre_building_permit_records").fetchone()[0] == 2
    finally:
        conn.close()


def test_changed_payload_creates_revision_without_overwriting_prior(tmp_path: Path) -> None:
    conn = database(tmp_path / "permit.db")
    try:
        source_id = ensure_source(conn, "SEOUL_BUILDING_PERMIT")
        s1 = create_snapshot(conn, source_id, "FULL", 1000, "2026-09-01T00:00:00Z")
        store_seoul_page(conn, s1, source_id, [raw("1", "업무시설", area=10000)], 1, 0)
        complete_snapshot(conn, s1, 1, 1, 1, 0, 1, 1, {"IN_SCOPE": 1})
        s2 = create_snapshot(conn, source_id, "FULL", 1000, "2026-09-02T00:00:00Z")
        store_seoul_page(conn, s2, source_id, [raw("1", "업무시설", area=12000)], 1, 0)
        complete_snapshot(conn, s2, 1, 1, 1, 0, 1, 1, {"IN_SCOPE": 1})
        assert conn.execute(
            "SELECT group_concat(revision_no,',') FROM (SELECT revision_no FROM building_permit_record_versions ORDER BY revision_no)"
        ).fetchone()[0] == "1,2"
        assert conn.execute(
            "SELECT total_floor_area_m2 FROM v_latest_building_permit_records"
        ).fetchone()[0] == 12000
    finally:
        conn.close()
