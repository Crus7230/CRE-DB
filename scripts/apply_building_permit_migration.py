"""Rehearse/apply the additive building-permit feature migration."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
from typing import Any

ROOT = Path(__file__).parents[1]
SQLITE_MIGRATION = ROOT / "db/v2/migrations/3.6.0_building_permits.sqlite.sql"
SQLITE_SOURCE_PATCH = ROOT / "db/v2/migrations/3.6.1_building_permit_source_dimension.sqlite.sql"
SQLITE_DATE_PATCH = ROOT / "db/v2/migrations/3.6.2_building_permit_event_date_quality.sqlite.sql"
SQLITE_AREA_PATCH = ROOT / "db/v2/migrations/3.6.3_building_permit_area_quality.sqlite.sql"
SQLITE_SERVING_PATCH = ROOT / "db/v2/migrations/3.6.4_building_permit_compact_serving.sqlite.sql"
SQLITE_DETAIL_PATCH = ROOT / "db/v2/migrations/3.6.5_building_permit_current_serving.sqlite.sql"
POSTGRES_MIGRATION = ROOT / "db/v2/migrations/3.6.0_building_permits.sql"
POSTGRES_SOURCE_PATCH = ROOT / "db/v2/migrations/3.6.1_building_permit_source_dimension.sql"
POSTGRES_DATE_PATCH = ROOT / "db/v2/migrations/3.6.2_building_permit_event_date_quality.sql"
POSTGRES_AREA_PATCH = ROOT / "db/v2/migrations/3.6.3_building_permit_area_quality.sql"
POSTGRES_SERVING_PATCH = ROOT / "db/v2/migrations/3.6.4_building_permit_compact_serving.sql"
POSTGRES_DETAIL_PATCH = ROOT / "db/v2/migrations/3.6.5_building_permit_current_serving.sql"
DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
EXPECTED_TABLES = (
    "building_permit_snapshots", "building_permit_snapshot_pages",
    "building_permit_record_versions", "building_permit_snapshot_records",
    "building_permit_classifications", "building_permit_exclusion_summary",
    "building_permit_monthly_serving", "building_permit_current_serving",
)
EXPECTED_VIEWS = (
    "v_latest_building_permit_records", "v_current_cre_building_permit_records",
    "v_cre_building_permit_events", "v_cre_building_permit_monthly",
    "v_building_permit_event_date_quality", "v_building_permit_area_quality",
)


def load_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def sqlite_verify(conn: sqlite3.Connection) -> dict[str, Any]:
    feature = conn.execute(
        "SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version'"
    ).fetchone()
    objects = {row[0]: row[1] for row in conn.execute(
        "SELECT name,type FROM sqlite_master WHERE name LIKE '%building_permit%'"
    )}
    missing = [name for name in (*EXPECTED_TABLES, *EXPECTED_VIEWS) if name not in objects]
    result = {
        "featureVersion": feature[0] if feature else None,
        "globalVersion": conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0],
        "missingObjects": missing,
        "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "foreignKeyViolations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
    }
    if result["featureVersion"] != "1.0.5" or missing or result["integrity"] != "ok" or result["foreignKeyViolations"]:
        raise RuntimeError(f"SQLite migration verification failed: {result}")
    return result


def sqlite_run(db_path: Path, apply: bool) -> dict[str, Any]:
    backup: Path | None = None
    if apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = ROOT / f"backups/market-pre-building-permits-{stamp}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(db_path)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close(); source.close()
        # A migrated archive copy can retain the Windows read-only attribute.
        # Only clear it after a consistent SQLite backup has succeeded.
        db_path.chmod(stat.S_IREAD | stat.S_IWRITE)
        target = db_path
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="cre-building-permit-rehearsal-"))
        target = temp_dir / "market.db"
        source = sqlite3.connect(db_path)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close(); source.close()
    conn = sqlite3.connect(target, timeout=60)
    try:
        before = conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0]
        existing = conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version'"
        ).fetchone()
        feature = existing[0] if existing else None
        changed = False
        if feature is None:
            conn.executescript(SQLITE_MIGRATION.read_text(encoding="utf-8"))
            feature, changed = "1.0.0", True
        if feature == "1.0.0":
            conn.executescript(SQLITE_SOURCE_PATCH.read_text(encoding="utf-8"))
            feature, changed = "1.0.1", True
        if feature == "1.0.1":
            conn.executescript(SQLITE_DATE_PATCH.read_text(encoding="utf-8"))
            feature, changed = "1.0.2", True
        if feature == "1.0.2":
            conn.executescript(SQLITE_AREA_PATCH.read_text(encoding="utf-8"))
            feature, changed = "1.0.3", True
        if feature == "1.0.3":
            conn.executescript(SQLITE_SERVING_PATCH.read_text(encoding="utf-8"))
            feature, changed = "1.0.4", True
        if feature == "1.0.4":
            conn.executescript(SQLITE_DETAIL_PATCH.read_text(encoding="utf-8"))
            feature, changed = "1.0.5", True
        if feature != "1.0.5":
            raise RuntimeError(f"unsupported building permit feature version: {feature}")
        verification = sqlite_verify(conn)
        status = ("applied" if apply else "rehearsal_passed") if changed else (
            "already_applied" if apply else "already_installed_rehearsal"
        )
        return {"engine": "sqlite", "status": status, "globalVersionBefore": before,
                "backup": str(backup) if backup else None, "verification": verification}
    finally:
        conn.close()
        if not apply:
            shutil.rmtree(target.parent, ignore_errors=True)


def migration_body(path: Path) -> str:
    body = path.read_text(encoding="utf-8")
    body = re.sub(r"(?m)^BEGIN;\s*", "", body, count=1)
    body = re.sub(r"(?m)^COMMIT;\s*$", "", body, count=1)
    return body


def postgres_verify(conn) -> dict[str, Any]:
    feature = conn.execute(
        "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='building_permit_schema_version'"
    ).fetchone()
    rows = conn.execute(
        """SELECT table_name,table_type FROM information_schema.tables
           WHERE table_schema='market_intelligence' AND table_name LIKE '%building_permit%'
           UNION ALL SELECT table_name,'VIEW' FROM information_schema.views
           WHERE table_schema='market_intelligence' AND table_name LIKE '%building_permit%'"""
    ).fetchall()
    objects = {row[0] for row in rows}
    missing = [name for name in (*EXPECTED_TABLES, *EXPECTED_VIEWS) if name not in objects]
    result = {"featureVersion": feature[0] if feature else None, "missingObjects": missing}
    if result["featureVersion"] != "1.0.5" or missing:
        raise RuntimeError(f"PostgreSQL migration verification failed: {result}")
    return result


def postgres_run(env_path: Path, apply: bool) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    env = load_env(env_path)
    dsn = env.get("SUPABASE_DB_URL") or env.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL or DATABASE_URL is missing")
    conn = psycopg.connect(dsn, connect_timeout=20)
    try:
        conn.execute("SET lock_timeout='30s'")
        conn.execute("SET statement_timeout='20min'")
        if not conn.execute("SELECT pg_try_advisory_xact_lock(%s,%s)", (0x435245, 0x42504D)).fetchone()[0]:
            raise RuntimeError("another building permit migration is running")
        before = conn.execute(
            "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0]
        existing = conn.execute(
            "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='building_permit_schema_version'"
        ).fetchone()
        feature = existing[0] if existing else None
        changed = False
        if feature is None:
            conn.execute(migration_body(POSTGRES_MIGRATION), prepare=False)
            feature, changed = "1.0.0", True
        if feature == "1.0.0":
            conn.execute(migration_body(POSTGRES_SOURCE_PATCH), prepare=False)
            feature, changed = "1.0.1", True
        if feature == "1.0.1":
            conn.execute(migration_body(POSTGRES_DATE_PATCH), prepare=False)
            feature, changed = "1.0.2", True
        if feature == "1.0.2":
            conn.execute(migration_body(POSTGRES_AREA_PATCH), prepare=False)
            feature, changed = "1.0.3", True
        if feature == "1.0.3":
            conn.execute(migration_body(POSTGRES_SERVING_PATCH), prepare=False)
            feature, changed = "1.0.4", True
        if feature == "1.0.4":
            conn.execute(migration_body(POSTGRES_DETAIL_PATCH), prepare=False)
            feature, changed = "1.0.5", True
        if feature != "1.0.5":
            raise RuntimeError(f"unsupported building permit feature version: {feature}")
        verification = postgres_verify(conn)
        if apply:
            conn.commit(); status = "applied" if changed else "already_applied"
        else:
            conn.rollback(); status = "rollback_rehearsal" if changed else "already_installed_rehearsal"
        persisted = conn.execute(
            "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='building_permit_schema_version'"
        ).fetchone()
        return {"engine": "postgres", "status": status, "globalVersionBefore": before,
                "verificationInTransaction": verification,
                "persistedFeatureVersion": persisted[0] if persisted else None}
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("sqlite", "postgres"), required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = sqlite_run(args.db, args.apply) if args.engine == "sqlite" else postgres_run(args.env, args.apply)
    report = args.report or ROOT / f"artifacts/building-permits/migration-{args.engine}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "report": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
