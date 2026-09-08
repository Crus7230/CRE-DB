from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path

from scripts.build_compact_serving_v2 import build_compact_candidate


PERMIT_TABLES = [
    "building_permit_classifications",
    "building_permit_current_serving",
    "building_permit_exclusion_summary",
    "building_permit_monthly_serving",
    "building_permit_record_versions",
    "building_permit_snapshot_pages",
    "building_permit_snapshot_records",
    "building_permit_snapshots",
]


def test_build_compact_candidate_keeps_archive_immutable_and_prunes_non_serving_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "market.db"
        output = Path(tmp) / "market-serving-v2.db"
        con = sqlite3.connect(source)
        for table in PERMIT_TABLES:
            con.execute(f'CREATE TABLE "{table}"(id INTEGER PRIMARY KEY)')
            con.execute(f'INSERT INTO "{table}" VALUES (1)')
        con.executescript("""
            CREATE TABLE analytics_refresh_runs(
                analytics_refresh_run_id TEXT PRIMARY KEY,
                pipeline_code TEXT, algorithm_version TEXT, status_code TEXT,
                completed_at TEXT
            );
            CREATE TABLE keyword_observations_daily(
                keyword_id TEXT, bucket_date TEXT, algorithm_version TEXT
            );
            CREATE TABLE keyword_cooccurrences_daily(
                keyword_left_id TEXT, keyword_right_id TEXT,
                bucket_date TEXT, algorithm_version TEXT
            );
            INSERT INTO analytics_refresh_runs VALUES
                ('old','KEYWORD_DAILY','v0','COMPLETED','2026-08-01T00:00:00Z'),
                ('new','KEYWORD_DAILY','v1','COMPLETED','2026-09-04T00:00:00Z');
            INSERT INTO keyword_observations_daily VALUES
                ('k1','2026-08-01','v1'),('k1','2026-09-04','v1'),('k1','2026-09-04','v0');
            INSERT INTO keyword_cooccurrences_daily VALUES
                ('k1','k2','2026-08-01','v1'),('k1','k2','2026-09-04','v1'),('k1','k2','2026-09-04','v0');
        """)
        con.commit()
        con.close()

        report = build_compact_candidate(source, output, keyword_days=30)
        repeat_report = build_compact_candidate(source, output, keyword_days=30)

        source_con = sqlite3.connect(source)
        assert source_con.execute("SELECT count(*) FROM building_permit_snapshots").fetchone()[0] == 1
        assert source_con.execute("SELECT count(*) FROM keyword_observations_daily").fetchone()[0] == 3
        source_con.close()

        candidate = sqlite3.connect(output)
        assert all(candidate.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0 for table in PERMIT_TABLES)
        assert candidate.execute("SELECT keyword_id,bucket_date,algorithm_version FROM keyword_observations_daily").fetchall() == [("k1", "2026-09-04", "v1")]
        assert candidate.execute("SELECT keyword_left_id,keyword_right_id,bucket_date,algorithm_version FROM keyword_cooccurrences_daily").fetchall() == [("k1", "k2", "2026-09-04", "v1")]
        candidate.close()

        assert report["integrity"] == "ok"
        assert report["foreignKeyViolations"] == 0
        assert report["keywordCutoff"] == "2026-08-06"


def test_build_compact_candidate_rejects_source_as_output_before_unlink() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "market.db"
        with closing(sqlite3.connect(source)) as conn:
            conn.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
            conn.execute("INSERT INTO sentinel VALUES('archive-preserved')")
            conn.commit()

        for output in (source, Path(tmp) / "market-hardlink.db"):
            if output != source:
                output.hardlink_to(source)
            try:
                build_compact_candidate(source, output)
            except ValueError as exc:
                assert "different file" in str(exc)
            else:
                raise AssertionError("source/output alias must be rejected")

        with closing(sqlite3.connect(source)) as conn:
            assert conn.execute("SELECT value FROM sentinel").fetchone() == ("archive-preserved",)


def test_build_compact_candidate_materializes_monthly_and_hot_permit_marts_before_pruning() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "market.db"
        output = Path(tmp) / "serving.db"
        con = sqlite3.connect(source)
        con.executescript("""
            CREATE TABLE building_permit_monthly_serving(
                source_id TEXT, source_snapshot_id TEXT, event_month TEXT, event_type TEXT,
                district_name TEXT, asset_type TEXT, scope_status TEXT, construction_action TEXT,
                permit_count INTEGER, total_floor_area_m2 REAL, missing_area_count INTEGER,
                invalid_area_count INTEGER, generated_at TEXT
            );
            CREATE TABLE building_permit_snapshots(source_as_of_date TEXT);
            INSERT INTO building_permit_snapshots VALUES ('2026-09-04');
            CREATE TABLE building_permit_current_serving(
                source_id TEXT, source_record_key TEXT, source_created_date TEXT,
                sigungu_code TEXT, bjdong_code TEXT, district_name TEXT, legal_dong_name TEXT,
                parcel_address TEXT, parcel_type_code TEXT, main_lot_number TEXT, sub_lot_number TEXT,
                building_name TEXT, construction_type TEXT, main_use_code TEXT, main_use_name TEXT,
                site_area_m2 REAL, building_area_m2 REAL, total_floor_area_m2 REAL,
                household_count INTEGER, unit_count INTEGER, family_count INTEGER,
                permit_date TEXT, planned_start_date TEXT, delayed_start_date TEXT,
                actual_start_date TEXT, use_approval_date TEXT, scope_status TEXT,
                asset_type TEXT, construction_action TEXT, confidence_score REAL,
                permit_date_quality TEXT, actual_start_date_quality TEXT,
                use_approval_date_quality TEXT, area_quality_status TEXT, last_seen_at TEXT
            );
            INSERT INTO building_permit_monthly_serving VALUES
                ('s','snap','2020-01','PERMIT','강남구','OFFICE','IN_SCOPE','NEW_BUILD',2,2000,0,0,'2026-09-04'),
                ('s','snap','2020-01','PERMIT','강남구','OTHER','REVIEW_OTHER','EXTENSION',3,3000,0,0,'2026-09-04');
            INSERT INTO building_permit_current_serving(
                source_id,source_record_key,district_name,parcel_address,total_floor_area_m2,
                permit_date,planned_start_date,scope_status,asset_type,construction_action,confidence_score,
                permit_date_quality,actual_start_date_quality,use_approval_date_quality,
                area_quality_status,last_seen_at
            ) VALUES
                ('s','hot','강남구','주소1',1000,'2026-09-01','2030-01-01','IN_SCOPE','OFFICE','NEW_BUILD',0.9,'VALID','MISSING','MISSING','VALID','2026-09-04'),
                ('s','cold','강남구','주소2',1000,'2020-01-01',NULL,'IN_SCOPE','OFFICE','NEW_BUILD',0.9,'VALID','MISSING','MISSING','VALID','2026-09-04');
        """)
        con.commit()
        con.close()

        report = build_compact_candidate(source, output, keyword_days=30)

        with closing(sqlite3.connect(output)) as candidate:
            monthly = candidate.execute(
                "SELECT district_name,scope_status,construction_action,permit_count FROM serving_v2_building_permit_monthly ORDER BY scope_status"
            ).fetchall()
            hot = candidate.execute("SELECT source_record_key FROM serving_v2_building_permit_hot_detail").fetchall()
        assert monthly == [("강남구", "IN_SCOPE", "NEW_BUILD", 2), ("__ALL__", "REVIEW_OTHER", "__ALL__", 3)]
        assert hot == [("hot",)]
        assert report["permitMonthlyRows"] == 2
        assert report["permitHotDetailRows"] == 1
        assert report["permitHotCutoff"] == "2021-10-01"
