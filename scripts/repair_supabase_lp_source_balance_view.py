#!/usr/bin/env python
"""Repair the LP source-balance view to use PostgreSQL numeric amounts."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
ARTIFACT = ROOT / "artifacts" / "supabase-lp-source-balance-view-repair.json"
VIEW = "v_lp_mandate_source_balance"
DOTENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def load_env() -> dict[str, str]:
    result = {}
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        m = DOTENV_RE.match(line.strip())
        if m:
            result[m.group(1)] = m.group(2).strip().strip("\"'")
    return result


def q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def main() -> None:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    spec = importlib.util.spec_from_file_location("migration", ROOT / "scripts" / "migrate_sqlite_to_supabase.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    env = load_env()
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    sqlite_conn = sqlite3.connect(f"file:{(ROOT / 'data' / 'market.db').as_posix()}?mode=ro", uri=True)
    ddl_by_view = {}
    for ddl in module.view_sql(sqlite_conn, schema):
        match = re.match(r'CREATE VIEW\s+"[^"]+"\."([^"]+)"', ddl, re.I)
        if match:
            ddl_by_view[match.group(1)] = ddl
    sqlite_conn.close()
    ddl = ddl_by_view[VIEW]
    if "AS numeric" not in ddl:
        raise SystemExit("numeric translation was not applied")
    with psycopg.connect(env["SUPABASE_DB_URL"], connect_timeout=20) as conn:
        dependents = conn.execute(
            """
            SELECT DISTINCT dependent.relname
            FROM pg_depend d
            JOIN pg_rewrite r ON r.oid=d.objid
            JOIN pg_class dependent ON dependent.oid=r.ev_class
            JOIN pg_class referenced ON referenced.oid=d.refobjid
            JOIN pg_namespace ns ON ns.oid=dependent.relnamespace
            WHERE ns.nspname=%s AND referenced.relname=%s AND dependent.relname<>%s
            """,
            (schema, VIEW, VIEW),
        ).fetchall()
        if dependents:
            raise SystemExit(f"dependent views require reviewed rebuild: {[r[0] for r in dependents]}")
        conn.execute("SELECT set_config('search_path', %s, true)", (f"{schema},public",))
        conn.execute(f"DROP VIEW {q(schema)}.{q(VIEW)}")
        conn.execute(ddl)
        row_count = conn.execute(f"SELECT count(*) FROM {q(schema)}.{q(VIEW)}").fetchone()[0]
        view_definition = conn.execute(
            "SELECT pg_get_viewdef(%s::regclass, true)", (f'{q(schema)}.{q(VIEW)}',)
        ).fetchone()[0]
        column_types = dict(conn.execute(
            "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
            (schema, VIEW),
        ).fetchall())
    report = {
        "repaired_at": datetime.now(timezone.utc).isoformat(),
        "schema": schema,
        "view": VIEW,
        "row_count": row_count,
        "amount_columns": {k: v for k, v in column_types.items() if "amount" in k},
        "numeric_internal_cast": "numeric" in view_definition.lower(),
        "passed": "numeric" in view_definition.lower(),
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
