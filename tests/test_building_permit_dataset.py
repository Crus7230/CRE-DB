from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).parents[1]
SQLITE_MIGRATION = ROOT / "db/v2/migrations/3.6.0_building_permits.sqlite.sql"
SQLITE_SOURCE_PATCH = ROOT / "db/v2/migrations/3.6.1_building_permit_source_dimension.sqlite.sql"
SQLITE_DATE_PATCH = ROOT / "db/v2/migrations/3.6.2_building_permit_event_date_quality.sqlite.sql"
SQLITE_AREA_PATCH = ROOT / "db/v2/migrations/3.6.3_building_permit_area_quality.sqlite.sql"
SQLITE_SERVING_PATCH = ROOT / "db/v2/migrations/3.6.4_building_permit_compact_serving.sqlite.sql"
SQLITE_DETAIL_PATCH = ROOT / "db/v2/migrations/3.6.5_building_permit_current_serving.sqlite.sql"


def base_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE schema_meta(
          schema_key TEXT PRIMARY KEY,
          schema_value TEXT NOT NULL,
          updated_at TEXT
        );
        INSERT INTO schema_meta VALUES('schema_version','3.5.0','2026-09-02');
        CREATE TABLE collection_sources(
          source_id TEXT PRIMARY KEY,
          source_code TEXT NOT NULL UNIQUE,
          source_name TEXT NOT NULL,
          source_kind TEXT NOT NULL,
          base_url TEXT,
          authority_tier INTEGER NOT NULL DEFAULT 4,
          collection_policy TEXT NOT NULL,
          policy_checked_at TEXT,
          config_json TEXT NOT NULL DEFAULT '{}',
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT '2026-09-02'
        );
        """
    )
    return conn


def migrated() -> sqlite3.Connection:
    conn = base_db()
    conn.executescript(SQLITE_MIGRATION.read_text(encoding="utf-8"))
    conn.executescript(SQLITE_SOURCE_PATCH.read_text(encoding="utf-8"))
    conn.executescript(SQLITE_DATE_PATCH.read_text(encoding="utf-8"))
    conn.executescript(SQLITE_AREA_PATCH.read_text(encoding="utf-8"))
    conn.executescript(SQLITE_SERVING_PATCH.read_text(encoding="utf-8"))
    conn.executescript(SQLITE_DETAIL_PATCH.read_text(encoding="utf-8"))
    return conn


def test_additive_feature_scoped_migration_and_views() -> None:
    conn = migrated()
    try:
        assert conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0] == "3.5.0"
        assert conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version'"
        ).fetchone()[0] == "1.0.5"
        objects = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view','index')"
            )
        }
        for name in (
            "building_permit_snapshots",
            "building_permit_record_versions",
            "building_permit_snapshot_records",
            "building_permit_classifications",
            "building_permit_exclusion_summary",
            "v_latest_building_permit_records",
            "v_cre_building_permit_events",
            "v_cre_building_permit_monthly",
        ):
            assert name in objects
    finally:
        conn.close()


def test_json_shapes_and_current_classification_are_enforced() -> None:
    conn = migrated()
    try:
        conn.execute(
            "INSERT INTO collection_sources(source_id,source_code,source_name,source_kind,collection_policy) VALUES('s','SEOUL_BUILDING_PERMIT','서울','OPEN_API','PUBLIC')"
        )
        conn.execute(
            """INSERT INTO building_permit_snapshots(
                   snapshot_id,source_id,snapshot_kind,status_code,started_at,metadata_json
                 ) VALUES('snap','s','FULL','RUNNING','2026-09-02T00:00:00Z','{}')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO building_permit_record_versions(
                       record_version_id,source_id,source_record_key,payload_sha256,raw_json,
                       first_seen_at,last_seen_at,created_at
                     ) VALUES('r','s','k',?,'[]','2026','2026','2026')""",
                ("0" * 64,),
            )
        conn.execute(
            """INSERT INTO building_permit_record_versions(
                   record_version_id,source_id,source_record_key,payload_sha256,raw_json,
                   first_seen_at,last_seen_at,created_at
                 ) VALUES('r','s','k',?,'{}','2026','2026','2026')""",
            ("0" * 64,),
        )
        conn.execute(
            """INSERT INTO building_permit_classifications(
                   classification_id,record_version_id,rule_version,scope_status,
                   asset_type,construction_action,confidence_score,is_current,reason_json,classified_at
                 ) VALUES('c1','r','v1','IN_SCOPE','OFFICE','NEW_SUPPLY',1,1,'{}','2026')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO building_permit_classifications(
                       classification_id,record_version_id,rule_version,scope_status,
                       asset_type,construction_action,confidence_score,is_current,reason_json,classified_at
                     ) VALUES('c2','r','v2','IN_SCOPE','HOTEL','NEW_SUPPLY',1,1,'{}','2026')"""
            )
    finally:
        conn.close()


def test_monthly_view_uses_latest_completed_snapshot_and_three_actual_events() -> None:
    conn = migrated()
    try:
        conn.execute(
            "INSERT INTO collection_sources(source_id,source_code,source_name,source_kind,collection_policy) VALUES('s','SEOUL_BUILDING_PERMIT','서울','OPEN_API','PUBLIC')"
        )
        conn.execute(
            """INSERT INTO building_permit_snapshots(
                   snapshot_id,source_id,snapshot_kind,status_code,started_at,completed_at,
                   source_total_count,fetched_count,candidate_count,metadata_json
                 ) VALUES('snap','s','FULL','COMPLETED','2026-09-02','2026-09-02',1,1,1,'{}')"""
        )
        conn.execute(
            """INSERT INTO building_permit_record_versions(
                   record_version_id,source_id,source_record_key,payload_sha256,raw_json,
                   district_name,main_use_name,construction_type,total_floor_area_m2,
                   permit_date,planned_start_date,actual_start_date,use_approval_date,
                   first_seen_at,last_seen_at,created_at
                 ) VALUES('r','s','permit-1',?,'{}','강남구','업무시설','신축',10000,
                   '2025-01-02','2025-02-01','2025-03-04','2026-06-07','2026','2026','2026')""",
            ("1" * 64,),
        )
        conn.execute("INSERT INTO building_permit_snapshot_records VALUES('snap','r',1)")
        conn.execute(
            """INSERT INTO building_permit_classifications(
                   classification_id,record_version_id,rule_version,scope_status,
                   asset_type,construction_action,confidence_score,is_current,reason_json,classified_at
                 ) VALUES('c','r','cre-permit-v1','IN_SCOPE','OFFICE','NEW_SUPPLY',1,1,'{}','2026')"""
        )
        rows = conn.execute(
            "SELECT event_type,event_month,permit_count,total_floor_area_m2 FROM v_cre_building_permit_monthly ORDER BY event_month"
        ).fetchall()
        assert rows == [
            ("PERMIT", "2025-01", 1, 10000.0),
            ("ACTUAL_START", "2025-03", 1, 10000.0),
            ("USE_APPROVAL", "2026-06", 1, 10000.0),
        ]
        conn.execute("UPDATE building_permit_record_versions SET total_floor_area_m2=950387392 WHERE record_version_id='r'")
        assert conn.execute(
            "SELECT sum(total_floor_area_m2),sum(invalid_area_count) FROM v_cre_building_permit_monthly"
        ).fetchone() == (0, 3)
        assert conn.execute(
            """SELECT record_count FROM v_building_permit_area_quality
               WHERE source_id='s' AND quality_status='ABOVE_2M'"""
        ).fetchone()[0] == 1
        conn.execute("UPDATE building_permit_record_versions SET permit_date='2995-01-02' WHERE record_version_id='r'")
        assert conn.execute(
            "SELECT count(*) FROM v_cre_building_permit_events WHERE event_type='PERMIT'"
        ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT record_count FROM v_building_permit_event_date_quality
               WHERE source_id='s' AND event_type='PERMIT' AND quality_status='FUTURE'"""
        ).fetchone()[0] == 1
    finally:
        conn.close()
