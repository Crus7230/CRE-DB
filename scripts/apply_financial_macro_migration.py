#!/usr/bin/env python
"""Rehearse/apply the financial macro feature migration without exposing credentials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
SQLITE_SQL = ROOT / "db/v2/migrations/3.7.0_financial_macro.sqlite.sql"
SQLITE_PATCH = ROOT / "db/v2/migrations/3.7.1_financial_macro_semantics.sqlite.sql"
SQLITE_VALIDITY_PATCH = ROOT / "db/v2/migrations/3.7.2_financial_macro_validity.sqlite.sql"
POSTGRES_SQL = ROOT / "db/v2/migrations/3.7.0_financial_macro.sql"
POSTGRES_PATCH = ROOT / "db/v2/migrations/3.7.1_financial_macro_semantics.sql"
POSTGRES_VALIDITY_PATCH = ROOT / "db/v2/migrations/3.7.2_financial_macro_validity.sql"
DOTENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = DOTENV_RE.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip().strip("\"'")
    return values


def verify_sqlite(conn: sqlite3.Connection) -> dict:
    version = conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='financial_macro_schema_version'").fetchone()
    objects = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    required = {"v_latest_macro_observations", "v_financial_macro_monthly", "financial_macro_monthly_serving"}
    sources = conn.execute("SELECT count(*) FROM collection_sources WHERE source_id IN ('src_ny_fed','src_us_treasury')").fetchone()[0]
    return {"version": version[0] if version else None, "objectsPresent": sorted(required & objects), "sources": sources}


def sqlite_run(path: Path, apply: bool) -> dict:
    source = sqlite3.connect(path)
    target = source if apply else sqlite3.connect(":memory:")
    if not apply:
        source.backup(target)
        source.close()
    try:
        target.execute("PRAGMA foreign_keys=ON")
        current = target.execute("SELECT schema_value FROM schema_meta WHERE schema_key='financial_macro_schema_version'").fetchone()
        if not current:
            target.executescript(SQLITE_SQL.read_text(encoding="utf-8"))
            current = ("1.0.0",)
        if current[0] == "1.0.0":
            target.executescript(SQLITE_PATCH.read_text(encoding="utf-8"))
            current = ("1.0.1",)
        if current[0] == "1.0.1":
            target.executescript(SQLITE_VALIDITY_PATCH.read_text(encoding="utf-8"))
            current = ("1.0.2",)
        if current[0] != "1.0.2":
            raise RuntimeError(f"unsupported financial macro feature version: {current[0]}")
        result = verify_sqlite(target)
        if result["version"] != "1.0.2" or result["sources"] != 2 or len(result["objectsPresent"]) != 3:
            raise RuntimeError(f"SQLite verification failed: {result}")
        if apply:
            target.commit()
        return {"engine": "sqlite", "status": "applied" if apply else "rollback_rehearsal", **result}
    finally:
        target.close()


def migration_body(sql: str) -> str:
    text = sql.strip()
    text = re.sub(r"^BEGIN;\s*", "", text, flags=re.I)
    text = re.sub(r"\s*COMMIT;\s*$", "", text, flags=re.I)
    return text


def postgres_run(env_path: Path, apply: bool) -> dict:
    import psycopg
    env = load_env(env_path)
    dsn = env.get("SUPABASE_DB_URL") or env.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("SUPABASE_DB_URL or DATABASE_URL is required")
    with psycopg.connect(dsn, autocommit=False) as conn:
        current = conn.execute("SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='financial_macro_schema_version'").fetchone()
        if not current:
            conn.execute(migration_body(POSTGRES_SQL.read_text(encoding="utf-8")), prepare=False)
            current = ("1.0.0",)
        if current[0] == "1.0.0":
            conn.execute(migration_body(POSTGRES_PATCH.read_text(encoding="utf-8")), prepare=False)
            current = ("1.0.1",)
        if current[0] == "1.0.1":
            conn.execute(migration_body(POSTGRES_VALIDITY_PATCH.read_text(encoding="utf-8")), prepare=False)
            current = ("1.0.2",)
        if current[0] != "1.0.2":
            raise RuntimeError(f"unsupported financial macro feature version: {current[0]}")
        version = conn.execute("SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='financial_macro_schema_version'").fetchone()[0]
        sources = conn.execute("SELECT count(*) FROM market_intelligence.collection_sources WHERE source_id IN ('src_ny_fed','src_us_treasury')").fetchone()[0]
        table = conn.execute("SELECT to_regclass('market_intelligence.financial_macro_monthly_serving')").fetchone()[0]
        result = {"engine": "postgres", "status": "applied" if apply else "rollback_rehearsal", "version": version, "sources": sources, "table": table}
        if version != "1.0.2" or sources != 2 or not table:
            raise RuntimeError(f"PostgreSQL verification failed: {result}")
        conn.commit() if apply else conn.rollback()
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("sqlite", "postgres"), required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = sqlite_run(args.db, args.apply) if args.engine == "sqlite" else postgres_run(args.env, args.apply)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
