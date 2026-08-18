#!/usr/bin/env python
"""Verify the active Supabase-main / SQLite-sub cutover."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.db"
ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
CONFIG = ROOT / "db" / "runtime-config.json"
OUTPUT = ROOT / "artifacts" / "main-sub-cutover-qa.json"
DOTENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def load_env() -> dict[str, str]:
    result = {}
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        match = DOTENV_RE.match(line.strip())
        if match:
            result[match.group(1)] = match.group(2).strip().strip("\"'")
    return result


def tables(conn: sqlite3.Connection) -> list[str]:
    result = []
    for name, sql in conn.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        if (sql or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
            continue
        if name.startswith("document_fts_"):
            continue
        result.append(name)
    return result


def main() -> None:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    env = load_env()
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    sqlite_conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row
    table_names = tables(sqlite_conn)
    mismatches = []
    representative_names = [
        "source_documents", "document_versions", "collection_runs", "extraction_runs",
        "relationship_resolution_runs", "lp_mandates", "lp_mandate_selections",
        "review_tasks", "organizations",
    ]
    representative = {}
    views = [
        "v_relationship_gaps",
        "v_lp_manager_best_available",
        "v_lp_mandate_source_balance",
        "v_event_feed",
    ]
    view_counts = {}
    with psycopg.connect(env["SUPABASE_DB_URL"], connect_timeout=20) as pg_conn:
        for table in table_names:
            local = sqlite_conn.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0]
            remote = pg_conn.execute(
                f"SELECT count(*) FROM {q(schema)}.{q(table)}"
            ).fetchone()[0]
            if local != remote:
                mismatches.append({"table": table, "main": remote, "sub": local})
            if table in representative_names:
                representative[table] = {"main": remote, "sub": local}
        for view in views:
            local = sqlite_conn.execute(f"SELECT count(*) FROM {q(view)}").fetchone()[0]
            remote = pg_conn.execute(
                f"SELECT count(*) FROM {q(schema)}.{q(view)}"
            ).fetchone()[0]
            view_counts[view] = {"main": remote, "sub": local}
        pg_fts = pg_conn.execute(
            f"SELECT count(*) FROM {q(schema)}.document_fts"
        ).fetchone()[0]
        pg_triggers = pg_conn.execute(
            "SELECT count(*) FROM information_schema.triggers WHERE trigger_schema=%s", (schema,)
        ).fetchone()[0]
    integrity = sqlite_conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = sqlite_conn.execute("PRAGMA foreign_key_check").fetchall()
    local_triggers = sqlite_conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='trigger'"
    ).fetchone()[0]
    sqlite_conn.close()
    write_blocked = False
    probe = sqlite3.connect(DB, timeout=3)
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.execute("CREATE TABLE _should_be_blocked(id INTEGER)")
        probe.rollback()
    except sqlite3.OperationalError as exc:
        probe.rollback()
        write_blocked = "readonly" in str(exc).lower() or "read-only" in str(exc).lower()
    finally:
        probe.close()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "main": "supabase-postgresql",
        "schema": schema,
        "sub": str(DB.resolve()),
        "tables_compared": len(table_names),
        "row_count_mismatches": mismatches,
        "representative_counts": representative,
        "representative_view_counts": view_counts,
        "sub_integrity": integrity,
        "sub_foreign_key_violations": len(fk),
        "sub_write_blocked": write_blocked,
        "main_fts_rows": pg_fts,
        "main_triggers": pg_triggers,
        "sub_triggers": local_triggers,
        "runtime_config_active": config.get("cutoverStatus") == "ACTIVE",
        "runtime_config_main": config.get("main", {}).get("backend"),
        "runtime_config_sub_mode": config.get("sub", {}).get("mode"),
    }
    report["passed"] = not any((
        mismatches,
        integrity != "ok",
        fk,
        not write_blocked,
        pg_triggers != 12,
        local_triggers != 12,
        not report["runtime_config_active"],
        report["runtime_config_main"] != "supabase-postgresql",
        report["runtime_config_sub_mode"] != "read-only-replica",
    ))
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
