"""Publish compact monthly building-permit serving data from Local SQLite to Supabase."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from scripts.apply_building_permit_migration import load_env  # noqa: E402

DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
DEFAULT_REPORT = ROOT / "artifacts/building-permits/supabase-sync.json"
LOCK = (0x435245, 0x425053)
MONTHLY_COLUMNS = (
    "source_id", "source_snapshot_id", "event_month", "event_type", "district_name",
    "asset_type", "scope_status", "construction_action", "permit_count",
    "total_floor_area_m2", "missing_area_count", "invalid_area_count", "generated_at",
)
CURRENT_COLUMNS = (
    "source_id", "source_snapshot_id", "record_version_id", "source_record_key", "revision_no",
    "source_created_date", "sigungu_code", "bjdong_code", "district_name", "legal_dong_name",
    "parcel_address", "road_address", "parcel_type_code", "main_lot_number", "sub_lot_number",
    "building_name", "construction_type", "main_use_code", "main_use_name",
    "site_area_m2", "building_area_m2", "total_floor_area_m2",
    "household_count", "unit_count", "family_count", "permit_date", "planned_start_date",
    "delayed_start_date", "actual_start_date", "use_approval_date", "first_seen_at", "last_seen_at",
    "rule_version", "scope_status", "asset_type", "construction_action", "confidence_score",
    "permit_date_quality", "actual_start_date_quality", "use_approval_date_quality",
    "area_quality_status", "published_at",
)


def table_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in conn.execute(f'PRAGMA table_info("{table}")'))


def latest_completed(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """WITH ranked AS (
             SELECT *,row_number() OVER (
               PARTITION BY source_id ORDER BY completed_at DESC,snapshot_id DESC
             ) rn
             FROM building_permit_snapshots WHERE status_code='COMPLETED'
           ) SELECT * FROM ranked WHERE rn=1 ORDER BY source_id"""
    ).fetchall()


def build_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    snapshots = latest_completed(conn)
    if not snapshots:
        raise RuntimeError("no completed building-permit snapshot is available")
    snapshot_cols = table_columns(conn, "building_permit_snapshots")
    source_cols = table_columns(conn, "collection_sources")
    snapshot_rows = [tuple(row[column] for column in snapshot_cols) for row in snapshots]
    snapshot_by_source = {row["source_id"]: row["snapshot_id"] for row in snapshots}
    source_ids = sorted(snapshot_by_source)
    marks = ",".join("?" for _ in source_ids)
    source_rows = conn.execute(
        f"SELECT {','.join(source_cols)} FROM collection_sources WHERE source_id IN ({marks}) ORDER BY source_id",
        source_ids,
    ).fetchall()
    generated_at = datetime.now(timezone.utc).isoformat()
    monthly_rows: list[tuple] = []
    for row in conn.execute(
        f"""SELECT source_id,event_month,event_type,district_name,asset_type,scope_status,
                    construction_action,permit_count,total_floor_area_m2,missing_area_count,invalid_area_count
             FROM v_cre_building_permit_monthly WHERE source_id IN ({marks})
             ORDER BY source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action""",
        source_ids,
    ):
        monthly_rows.append((
            row[0], snapshot_by_source[row[0]], *row[1:], generated_at,
        ))
    expected = {}
    current_rows = []
    current_sql = f"""SELECT source_id,snapshot_id,record_version_id,source_record_key,revision_no,
        source_created_date,sigungu_code,bjdong_code,district_name,legal_dong_name,
        parcel_address,road_address,parcel_type_code,main_lot_number,sub_lot_number,
        building_name,construction_type,main_use_code,main_use_name,
        site_area_m2,building_area_m2,total_floor_area_m2,household_count,unit_count,family_count,
        permit_date,planned_start_date,delayed_start_date,actual_start_date,use_approval_date,
        first_seen_at,last_seen_at,rule_version,scope_status,asset_type,construction_action,confidence_score,
        CASE WHEN permit_date IS NULL THEN 'MISSING' WHEN permit_date<'1900-01-01' THEN 'BEFORE_1900'
             WHEN permit_date>date('now') THEN 'FUTURE' ELSE 'VALID' END,
        CASE WHEN actual_start_date IS NULL THEN 'MISSING' WHEN actual_start_date<'1900-01-01' THEN 'BEFORE_1900'
             WHEN actual_start_date>date('now') THEN 'FUTURE' ELSE 'VALID' END,
        CASE WHEN use_approval_date IS NULL THEN 'MISSING' WHEN use_approval_date<'1900-01-01' THEN 'BEFORE_1900'
             WHEN use_approval_date>date('now') THEN 'FUTURE' ELSE 'VALID' END,
        CASE WHEN total_floor_area_m2 IS NULL THEN 'MISSING' WHEN total_floor_area_m2<0 THEN 'NEGATIVE'
             WHEN total_floor_area_m2>2000000 THEN 'ABOVE_2M' ELSE 'VALID' END
        FROM v_current_cre_building_permit_records WHERE source_id IN ({marks})
        ORDER BY source_id,source_record_key"""
    for row in conn.execute(current_sql, source_ids):
        current_rows.append((*tuple(row), generated_at))
    expected_current = {}
    for source_id, scope_status, asset_type, action, records in conn.execute(
        f"""SELECT source_id,scope_status,asset_type,construction_action,count(*)
             FROM v_current_cre_building_permit_records WHERE source_id IN ({marks})
             GROUP BY source_id,scope_status,asset_type,construction_action
             ORDER BY source_id,scope_status,asset_type,construction_action""", source_ids
    ):
        expected_current.setdefault(source_id, {})[f"{scope_status}|{asset_type}|{action}"] = int(records)
    expected = {}
    for source_id in source_ids:
        expected[source_id] = {}
        for event_type, permits, area, invalid in conn.execute(
            """SELECT event_type,sum(permit_count),round(sum(total_floor_area_m2),6),sum(invalid_area_count)
               FROM v_cre_building_permit_monthly WHERE source_id=? GROUP BY event_type ORDER BY event_type""",
            (source_id,),
        ):
            expected[source_id][event_type] = {
                "permitCount": int(permits), "areaM2": float(area or 0), "invalidAreaCount": int(invalid or 0),
            }
    return {
        "sourceColumns": source_cols, "sourceRows": [tuple(row) for row in source_rows],
        "snapshotColumns": snapshot_cols, "snapshotRows": snapshot_rows,
        "monthlyRows": monthly_rows, "currentRows": current_rows, "sourceIds": source_ids,
        "snapshotBySource": snapshot_by_source, "expected": expected,
        "expectedCurrent": expected_current,
    }


def copy_rows(conn, temp_table: str, columns: tuple[str, ...], rows: list[tuple]) -> None:
    if not rows:
        return
    with conn.cursor().copy(f"COPY {temp_table} ({','.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def upsert_from_temp(conn, table: str, temp_table: str, columns: tuple[str, ...], pk: tuple[str, ...]) -> None:
    updates = [f"{column}=EXCLUDED.{column}" for column in columns if column not in pk]
    conn.execute(
        f"INSERT INTO market_intelligence.{table} ({','.join(columns)}) "
        f"SELECT {','.join(columns)} FROM {temp_table} "
        f"ON CONFLICT ({','.join(pk)}) DO UPDATE SET {','.join(updates)}"
    )


def stage_and_sync(conn, payload: dict[str, Any]) -> dict[str, int]:
    source_cols = payload["sourceColumns"]
    snapshot_cols = payload["snapshotColumns"]
    conn.execute("CREATE TEMP TABLE _bp_sources (LIKE market_intelligence.collection_sources INCLUDING DEFAULTS) ON COMMIT DROP")
    conn.execute("CREATE TEMP TABLE _bp_snapshots (LIKE market_intelligence.building_permit_snapshots INCLUDING DEFAULTS) ON COMMIT DROP")
    conn.execute("CREATE TEMP TABLE _bp_monthly (LIKE market_intelligence.building_permit_monthly_serving INCLUDING DEFAULTS) ON COMMIT DROP")
    copy_rows(conn, "_bp_sources", source_cols, payload["sourceRows"])
    copy_rows(conn, "_bp_snapshots", snapshot_cols, payload["snapshotRows"])
    copy_rows(conn, "_bp_monthly", MONTHLY_COLUMNS, payload["monthlyRows"])
    upsert_from_temp(conn, "collection_sources", "_bp_sources", source_cols, ("source_id",))
    upsert_from_temp(conn, "building_permit_snapshots", "_bp_snapshots", snapshot_cols, ("snapshot_id",))
    conn.execute(
        "DELETE FROM market_intelligence.building_permit_monthly_serving WHERE source_id IN (SELECT source_id FROM _bp_sources)"
    )
    conn.execute(
        f"INSERT INTO market_intelligence.building_permit_monthly_serving ({','.join(MONTHLY_COLUMNS)}) "
        f"SELECT {','.join(MONTHLY_COLUMNS)} FROM _bp_monthly"
    )
    conn.execute("TRUNCATE market_intelligence.building_permit_current_serving")
    copy_rows(conn, "market_intelligence.building_permit_current_serving", CURRENT_COLUMNS, payload["currentRows"])
    return {
        "sources": len(payload["sourceRows"]), "snapshots": len(payload["snapshotRows"]),
        "monthlyRows": len(payload["monthlyRows"]), "currentRows": len(payload["currentRows"]),
    }


def remote_aggregates(conn, source_ids: list[str]) -> dict[str, Any]:
    result = {source_id: {} for source_id in source_ids}
    rows = conn.execute(
        """SELECT source_id,event_type,sum(permit_count),round(sum(total_floor_area_m2),6),sum(invalid_area_count)
           FROM market_intelligence.building_permit_monthly_serving
           WHERE source_id=ANY(%s) GROUP BY source_id,event_type ORDER BY source_id,event_type""",
        (source_ids,),
    ).fetchall()
    for source_id, event_type, permits, area, invalid in rows:
        result[source_id][event_type] = {
            "permitCount": int(permits), "areaM2": float(area or 0), "invalidAreaCount": int(invalid or 0),
        }
    return result


def remote_current_aggregates(conn, source_ids: list[str]) -> dict[str, Any]:
    result = {source_id: {} for source_id in source_ids}
    rows = conn.execute(
        """SELECT source_id,scope_status,asset_type,construction_action,count(*)
           FROM market_intelligence.building_permit_current_serving
           WHERE source_id=ANY(%s)
           GROUP BY source_id,scope_status,asset_type,construction_action
           ORDER BY source_id,scope_status,asset_type,construction_action""", (source_ids,),
    ).fetchall()
    for source_id, scope_status, asset_type, action, records in rows:
        result[source_id][f"{scope_status}|{asset_type}|{action}"] = int(records)
    return result


def run(db_path: Path, env_path: Path, *, apply: bool) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required; use the configured Python interpreter") from exc
    local = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    local.row_factory = sqlite3.Row
    try:
        version = local.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version'"
        ).fetchone()[0]
        if version != "1.0.5":
            raise RuntimeError(f"Local building permit feature 1.0.5 is required, found {version}")
        payload = build_payload(local)
    finally:
        local.close()
    env = load_env(env_path)
    dsn = env.get("SUPABASE_DB_URL") or env.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL or DATABASE_URL is missing")
    conn = psycopg.connect(dsn, connect_timeout=20)
    try:
        conn.execute("SET lock_timeout='30s'")
        conn.execute("SET statement_timeout='20min'")
        if not conn.execute("SELECT pg_try_advisory_xact_lock(%s,%s)", LOCK).fetchone()[0]:
            raise RuntimeError("another building permit serving sync is running")
        feature = conn.execute(
            "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='building_permit_schema_version'"
        ).fetchone()
        if not feature or feature[0] != "1.0.5":
            raise RuntimeError("Supabase building permit feature 1.0.5 is not installed")
        staged = stage_and_sync(conn, payload)
        actual = remote_aggregates(conn, payload["sourceIds"])
        if actual != payload["expected"]:
            raise RuntimeError(f"aggregate readback mismatch: expected={payload['expected']} actual={actual}")
        staged_monthly = conn.execute("SELECT count(*) FROM _bp_monthly").fetchone()[0]
        persisted_monthly = conn.execute(
            "SELECT count(*) FROM market_intelligence.building_permit_monthly_serving WHERE source_id=ANY(%s)",
            (payload["sourceIds"],),
        ).fetchone()[0]
        if staged_monthly != persisted_monthly:
            raise RuntimeError(f"monthly row readback mismatch: {staged_monthly}/{persisted_monthly}")
        current_actual = remote_current_aggregates(conn, payload["sourceIds"])
        if current_actual != payload["expectedCurrent"]:
            raise RuntimeError("current-detail classification readback mismatch")
        persisted_current = conn.execute(
            "SELECT count(*) FROM market_intelligence.building_permit_current_serving"
        ).fetchone()[0]
        if persisted_current != len(payload["currentRows"]):
            raise RuntimeError(f"current-detail row readback mismatch: {len(payload['currentRows'])}/{persisted_current}")
        verification = {
            "status": "passed", "monthlyRows": persisted_monthly, "currentRows": persisted_current,
            "aggregates": actual, "currentClassification": current_actual,
            "snapshotBySource": payload["snapshotBySource"],
        }
        if apply:
            conn.commit(); status = "applied"
        else:
            conn.rollback(); status = "rollback_rehearsal"
        final_rows = conn.execute(
            "SELECT count(*) FROM market_intelligence.building_permit_monthly_serving WHERE source_id=ANY(%s)",
            (payload["sourceIds"],),
        ).fetchone()[0]
        final_current = conn.execute(
            "SELECT count(*) FROM market_intelligence.building_permit_current_serving"
        ).fetchone()[0]
        database_bytes = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        return {
            "status": status, "staged": staged, "verification": verification,
            "persistedMonthlyRows": final_rows, "persistedCurrentRows": final_current,
            "databaseBytes": database_bytes,
            "completedAt": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = run(args.db, args.env, apply=args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({**result, "report": str(args.report)}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
