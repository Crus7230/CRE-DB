"""Rehearse or apply the additive contextual-intelligence feature migration."""
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
SQLITE_MIGRATION = ROOT / "db/v2/migrations/3.8.0_contextual_intelligence.sqlite.sql"
POSTGRES_MIGRATION = ROOT / "db/v2/migrations/3.8.0_contextual_intelligence.sql"
DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
FEATURE_VERSION = "1.0.0"
EXPECTED_TABLES = (
    "contextual_processing_campaigns", "contextual_rule_sets", "contextual_rules",
    "contextual_document_runs", "legacy_derived_records", "contextual_event_frames",
    "contextual_frame_participants", "contextual_frame_targets",
    "contextual_impact_assertions", "contextual_review_decisions",
    "contextual_search_records",
)
RAW_TABLES = ("source_documents", "document_versions")


def load_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def migration_body(path: Path) -> str:
    body = path.read_text(encoding="utf-8")
    body, begin_count = re.subn(r"(?m)^BEGIN;\s*", "", body, count=1)
    body, commit_count = re.subn(r"(?m)^COMMIT;\s*$", "", body, count=1)
    if begin_count != 1 or commit_count != 1:
        raise RuntimeError(f"migration transaction wrapper not recognized: {path.name}")
    return body


def sqlite_verify(conn: sqlite3.Connection, raw_before: dict[str, int] | None = None) -> dict[str, Any]:
    feature = conn.execute(
        "SELECT schema_value FROM schema_meta WHERE schema_key='contextual_intelligence_schema_version'"
    ).fetchone()
    objects = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = [table for table in EXPECTED_TABLES if table not in objects]
    raw_counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in RAW_TABLES}
    result = {
        "featureVersion": feature[0] if feature else None,
        "globalVersion": conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0],
        "missingObjects": missing,
        "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "foreignKeyViolations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        "rawCounts": raw_counts,
        "rawCountsUnchanged": raw_before is None or raw_before == raw_counts,
    }
    if (result["featureVersion"] != FEATURE_VERSION or missing or result["integrity"] != "ok"
            or result["foreignKeyViolations"] or not result["rawCountsUnchanged"]):
        raise RuntimeError(f"SQLite contextual migration verification failed: {result}")
    return result


def sqlite_run(db_path: Path, apply: bool) -> dict[str, Any]:
    source = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    raw_before = {table: source.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in RAW_TABLES}
    source.close()
    backup: Path | None = None
    temp_dir: Path | None = None
    if apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = ROOT / f"backups/market-pre-contextual-intelligence-{stamp}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        dest = sqlite3.connect(backup)
        try:
            src.backup(dest)
        finally:
            dest.close(); src.close()
        db_path.chmod(stat.S_IREAD | stat.S_IWRITE)
        target = db_path
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="cre-contextual-migration-"))
        target = temp_dir / "market.db"
        src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        dest = sqlite3.connect(target)
        try:
            src.backup(dest)
        finally:
            dest.close(); src.close()
    conn = sqlite3.connect(target, timeout=60)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        existing = conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='contextual_intelligence_schema_version'"
        ).fetchone()
        changed = existing is None
        if changed:
            conn.executescript(SQLITE_MIGRATION.read_text(encoding="utf-8"))
        elif existing[0] != FEATURE_VERSION:
            raise RuntimeError(f"unsupported contextual feature version: {existing[0]}")
        verification = sqlite_verify(conn, raw_before)
        return {
            "engine": "sqlite",
            "status": ("applied" if apply else "rehearsal_passed") if changed else
                      ("already_applied" if apply else "already_installed_rehearsal"),
            "backup": str(backup) if backup else None,
            "verification": verification,
        }
    finally:
        conn.close()
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def postgres_verify(conn, raw_before: dict[str, int] | None = None) -> dict[str, Any]:
    feature = conn.execute(
        "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='contextual_intelligence_schema_version'"
    ).fetchone()
    objects = {
        row[0] for row in conn.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema='market_intelligence'"""
        ).fetchall()
    }
    missing = [table for table in EXPECTED_TABLES if table not in objects]
    raw_counts = {
        table: conn.execute(f"SELECT count(*) FROM market_intelligence.{table}").fetchone()[0]
        for table in RAW_TABLES
    }
    result = {
        "featureVersion": feature[0] if feature else None,
        "missingObjects": missing,
        "rawCounts": raw_counts,
        "rawCountsUnchanged": raw_before is None or raw_before == raw_counts,
    }
    if result["featureVersion"] != FEATURE_VERSION or missing or not result["rawCountsUnchanged"]:
        raise RuntimeError(f"PostgreSQL contextual migration verification failed: {result}")
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
        if not conn.execute("SELECT pg_try_advisory_xact_lock(%s,%s)", (0x435245, 0x435458)).fetchone()[0]:
            raise RuntimeError("another contextual-intelligence migration is running")
        raw_before = {
            table: conn.execute(f"SELECT count(*) FROM market_intelligence.{table}").fetchone()[0]
            for table in RAW_TABLES
        }
        existing = conn.execute(
            "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='contextual_intelligence_schema_version'"
        ).fetchone()
        changed = existing is None
        if changed:
            conn.execute(migration_body(POSTGRES_MIGRATION), prepare=False)
        elif existing[0] != FEATURE_VERSION:
            raise RuntimeError(f"unsupported contextual feature version: {existing[0]}")
        verification = postgres_verify(conn, raw_before)
        if apply:
            conn.commit()
            status = "applied" if changed else "already_applied"
        else:
            conn.rollback()
            status = "rollback_rehearsal" if changed else "already_installed_rehearsal"
        persisted = conn.execute(
            "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='contextual_intelligence_schema_version'"
        ).fetchone()
        return {
            "engine": "postgres",
            "status": status,
            "verificationInTransaction": verification,
            "persistedFeatureVersion": persisted[0] if persisted else None,
        }
    except Exception:
        conn.rollback()
        raise
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
    report = args.report or ROOT / f"artifacts/contextual-intelligence/migration-{args.engine}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "report": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
