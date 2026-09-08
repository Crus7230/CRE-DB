#!/usr/bin/env python
"""Build a compact, dashboard-only SQLite source for Supabase serving v2."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3

try:
    from scripts.refresh_dashboard_serving import (
        refresh_compact_permit_metadata,
        refresh_dashboard_serving,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from refresh_dashboard_serving import (  # type: ignore[no-redef]
        refresh_compact_permit_metadata,
        refresh_dashboard_serving,
    )

PERMIT_TABLES_DELETE_ORDER = (
    "building_permit_classifications",
    "building_permit_current_serving",
    "building_permit_exclusion_summary",
    "building_permit_monthly_serving",
    "building_permit_snapshot_pages",
    "building_permit_snapshot_records",
    "building_permit_record_versions",
    "building_permit_snapshots",
)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _copy_sqlite(source: Path, output: Path) -> None:
    if output.exists():
        output.chmod(0o666)
        output.unlink()
    with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(output)) as dst:
            src.backup(dst)


def _materialize_permit_marts(conn: sqlite3.Connection, present: set[str]) -> dict[str, object]:
    required = {"building_permit_monthly_serving", "building_permit_current_serving"}
    monthly_columns = {row[1] for row in conn.execute("PRAGMA table_info(building_permit_monthly_serving)")}
    current_columns = {row[1] for row in conn.execute("PRAGMA table_info(building_permit_current_serving)")}
    required_monthly = {"source_id", "event_month", "event_type", "district_name", "asset_type", "scope_status", "construction_action", "permit_count", "total_floor_area_m2", "missing_area_count", "invalid_area_count"}
    required_current = {"source_id", "source_record_key", "permit_date", "planned_start_date", "delayed_start_date", "actual_start_date", "use_approval_date", "scope_status", "asset_type", "construction_action", "confidence_score", "permit_date_quality", "actual_start_date_quality", "use_approval_date_quality", "area_quality_status", "last_seen_at"}
    if not required.issubset(present) or not required_monthly.issubset(monthly_columns) or not required_current.issubset(current_columns):
        return {"permitMonthlyRows": 0, "permitHotDetailRows": 0, "permitHotCutoff": None}
    conn.executescript("""
        DROP TABLE IF EXISTS serving_v2_building_permit_monthly;
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
        INSERT INTO serving_v2_building_permit_monthly
        SELECT source_id,event_month,event_type,
               CASE WHEN scope_status='IN_SCOPE' THEN district_name ELSE '__ALL__' END,
               asset_type,scope_status,
               CASE WHEN scope_status='IN_SCOPE' THEN construction_action ELSE '__ALL__' END,
               sum(permit_count),sum(total_floor_area_m2),sum(missing_area_count),sum(invalid_area_count)
        FROM building_permit_monthly_serving
        GROUP BY source_id,event_month,event_type,
                 CASE WHEN scope_status='IN_SCOPE' THEN district_name ELSE '__ALL__' END,
                 asset_type,scope_status,
                 CASE WHEN scope_status='IN_SCOPE' THEN construction_action ELSE '__ALL__' END;
        CREATE INDEX idx_serving_v2_permit_monthly_date_scope
            ON serving_v2_building_permit_monthly(event_month,scope_status,asset_type);
    """)
    latest = None
    if "building_permit_snapshots" in present:
        snapshot_columns = {row[1] for row in conn.execute("PRAGMA table_info(building_permit_snapshots)")}
        if "source_as_of_date" in snapshot_columns:
            latest = conn.execute(
                "SELECT max(source_as_of_date) FROM building_permit_snapshots WHERE source_as_of_date IS NOT NULL"
            ).fetchone()[0]
    if not latest:
        latest = conn.execute("""
            SELECT max(event_date) FROM (
                SELECT permit_date event_date FROM building_permit_current_serving
                UNION ALL SELECT planned_start_date FROM building_permit_current_serving
                UNION ALL SELECT delayed_start_date FROM building_permit_current_serving
                UNION ALL SELECT actual_start_date FROM building_permit_current_serving
                UNION ALL SELECT use_approval_date FROM building_permit_current_serving
            ) WHERE event_date IS NOT NULL AND event_date<>''
        """).fetchone()[0]
    cutoff = None
    if latest:
        cutoff = conn.execute("SELECT date(?,'start of month','-59 months')", (latest,)).fetchone()[0]
    conn.executescript("""
        DROP TABLE IF EXISTS serving_v2_building_permit_hot_detail;
        CREATE TABLE serving_v2_building_permit_hot_detail(
            source_id TEXT NOT NULL,
            source_record_key TEXT NOT NULL,
            source_created_date TEXT,
            sigungu_code TEXT,
            bjdong_code TEXT,
            district_name TEXT,
            legal_dong_name TEXT,
            parcel_address TEXT,
            parcel_type_code TEXT,
            main_lot_number TEXT,
            sub_lot_number TEXT,
            building_name TEXT,
            construction_type TEXT,
            main_use_code TEXT,
            main_use_name TEXT,
            site_area_m2 REAL,
            building_area_m2 REAL,
            total_floor_area_m2 REAL,
            household_count INTEGER,
            unit_count INTEGER,
            family_count INTEGER,
            permit_date TEXT,
            planned_start_date TEXT,
            delayed_start_date TEXT,
            actual_start_date TEXT,
            use_approval_date TEXT,
            scope_status TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            construction_action TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            quality_flags INTEGER NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY(source_id,source_record_key)
        );
    """)
    if cutoff:
        conn.execute("""
            INSERT INTO serving_v2_building_permit_hot_detail
            SELECT source_id,source_record_key,source_created_date,sigungu_code,bjdong_code,
                   district_name,legal_dong_name,parcel_address,parcel_type_code,
                   main_lot_number,sub_lot_number,building_name,construction_type,
                   main_use_code,main_use_name,site_area_m2,building_area_m2,total_floor_area_m2,
                   household_count,unit_count,family_count,permit_date,planned_start_date,
                   delayed_start_date,actual_start_date,use_approval_date,scope_status,
                   asset_type,construction_action,confidence_score,
                   (CASE WHEN permit_date_quality<>'VALID' THEN 1 ELSE 0 END)
                   +(CASE WHEN actual_start_date_quality<>'VALID' THEN 2 ELSE 0 END)
                   +(CASE WHEN use_approval_date_quality<>'VALID' THEN 4 ELSE 0 END)
                   +(CASE WHEN area_quality_status<>'VALID' THEN 8 ELSE 0 END),
                   last_seen_at
            FROM building_permit_current_serving
            WHERE max(coalesce(permit_date,''),coalesce(planned_start_date,''),
                      coalesce(delayed_start_date,''),coalesce(actual_start_date,''),
                      coalesce(use_approval_date,'')) >= ?
        """, (cutoff,))
    conn.executescript("""
        CREATE INDEX idx_serving_v2_permit_hot_date
            ON serving_v2_building_permit_hot_detail(permit_date,actual_start_date,use_approval_date);
        CREATE INDEX idx_serving_v2_permit_hot_filter
            ON serving_v2_building_permit_hot_detail(scope_status,asset_type,district_name);
    """)
    return {
        "permitMonthlyRows": int(conn.execute("SELECT count(*) FROM serving_v2_building_permit_monthly").fetchone()[0]),
        "permitHotDetailRows": int(conn.execute("SELECT count(*) FROM serving_v2_building_permit_hot_detail").fetchone()[0]),
        "permitHotCutoff": cutoff,
    }


def build_compact_candidate(source: Path, output: Path, *, keyword_days: int = 30) -> dict[str, object]:
    if keyword_days < 1:
        raise ValueError("keyword_days must be positive")
    source = source.resolve()
    output = output.resolve()
    if source == output or (output.exists() and source.samefile(output)):
        raise ValueError("compact output must be a different file from the source archive")
    _copy_sqlite(source, output)
    report: dict[str, object] = {
        "source": str(source),
        "output": str(output),
        "sourceBytes": source.stat().st_size,
        "keywordDays": keyword_days,
    }
    with closing(sqlite3.connect(output)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        present = _tables(conn)
        # Refresh the governed projections on the candidate before the raw
        # archive tables are pruned. Minimal unit-test fixtures intentionally
        # omit schema_meta and continue to exercise only compact pruning.
        if "schema_meta" in present:
            report["dashboardServing"] = refresh_dashboard_serving(
                conn,
                refresh_compact_metadata=False,
            )
            present = _tables(conn)
        report.update(_materialize_permit_marts(conn, present))
        if "schema_meta" in present:
            report["compactPermitFreshness"] = refresh_compact_permit_metadata(
                conn,
                str(report["dashboardServing"]["generatedAt"]),
            )
        permit_rows: dict[str, int] = {}
        for table in PERMIT_TABLES_DELETE_ORDER:
            if table not in present:
                continue
            permit_rows[table] = int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
            conn.execute(f'DELETE FROM "{table}"')
        report["excludedPermitRows"] = permit_rows

        required = {"analytics_refresh_runs", "keyword_observations_daily", "keyword_cooccurrences_daily"}
        if required.issubset(present):
            latest = conn.execute(
                """SELECT algorithm_version FROM analytics_refresh_runs
                   WHERE pipeline_code='KEYWORD_DAILY' AND status_code='COMPLETED'
                   ORDER BY completed_at DESC,analytics_refresh_run_id DESC LIMIT 1"""
            ).fetchone()
            if latest:
                algorithm = str(latest[0])
                latest_day_row = conn.execute(
                    "SELECT max(bucket_date) FROM keyword_observations_daily WHERE algorithm_version=?",
                    (algorithm,),
                ).fetchone()
                if latest_day_row and latest_day_row[0]:
                    latest_day = date.fromisoformat(str(latest_day_row[0]))
                    cutoff = latest_day - timedelta(days=keyword_days - 1)
                    report["keywordAlgorithmVersion"] = algorithm
                    report["keywordLatestDate"] = latest_day.isoformat()
                    report["keywordCutoff"] = cutoff.isoformat()
                    for table in ("keyword_cooccurrences_daily", "keyword_observations_daily"):
                        before = int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
                        conn.execute(
                            f'DELETE FROM "{table}" WHERE algorithm_version<>? OR bucket_date<?',
                            (algorithm, cutoff.isoformat()),
                        )
                        after = int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
                        report[f"{table}Before"] = before
                        report[f"{table}After"] = after
        conn.commit()
        foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        if foreign_keys:
            raise RuntimeError("compact candidate has foreign-key violations")
        conn.execute("VACUUM")
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError("compact candidate failed integrity check")
    output.chmod(0o444)
    report.update(
        integrity=integrity,
        foreignKeyViolations=foreign_keys,
        outputBytes=output.stat().st_size,
    )
    report["reductionBytes"] = int(report["sourceBytes"]) - int(report["outputBytes"])
    return report


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "data" / "market.db")
    parser.add_argument("--output", type=Path, default=root / "data" / "market-serving-v2.candidate.db")
    parser.add_argument("--keyword-days", type=int, default=30)
    parser.add_argument("--report", type=Path, default=root / "artifacts" / "compact-serving-v2-latest.json")
    args = parser.parse_args()
    report = build_compact_candidate(args.source, args.output, keyword_days=args.keyword_days)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
