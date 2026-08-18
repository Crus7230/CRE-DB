#!/usr/bin/env python
"""Independent source/target QA for the SQLite→Supabase migration."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
MIGRATION_RESULT = ROOT / "artifacts" / "supabase-initial-migration-result.json"
OUTPUT = ROOT / "artifacts" / "supabase-migration-qa.json"
DOTENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        match = DOTENV_RE.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip().strip("\"'")
    return values


def normalize(value):
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, Decimal):
        return str(value)
    return value


def digest_rows(rows) -> str:
    payload = [[normalize(v) for v in row] for row in rows]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def source_tables(conn: sqlite3.Connection) -> list[str]:
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
    migration = json.loads(MIGRATION_RESULT.read_text(encoding="utf-8"))
    snapshot = Path(migration["source_snapshot"])
    env = load_env()
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    sqlite_conn = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row
    tables = source_tables(sqlite_conn)
    row_mismatches = []
    sample_mismatches = []
    with psycopg.connect(env["SUPABASE_DB_URL"], connect_timeout=20) as pg_conn:
        for table in tables:
            source_count = sqlite_conn.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0]
            target_count = pg_conn.execute(
                f"SELECT count(*) FROM {q(schema)}.{q(table)}"
            ).fetchone()[0]
            if source_count != target_count:
                row_mismatches.append({"table": table, "source": source_count, "target": target_count})
            cols = [row[1] for row in sqlite_conn.execute(f"PRAGMA table_info({q(table)})")]
            pk_rows = [row for row in sqlite_conn.execute(f"PRAGMA table_info({q(table)})") if row[5]]
            pk_rows.sort(key=lambda row: row[5])
            order_cols = [row[1] for row in pk_rows] or cols[:1]
            select_cols = ",".join(q(c) for c in cols)
            order = ",".join(q(c) for c in order_cols)
            source_rows = sqlite_conn.execute(
                f"SELECT {select_cols} FROM {q(table)} ORDER BY {order} LIMIT 3"
            ).fetchall()
            if pk_rows:
                indexes = {name: index for index, name in enumerate(cols)}
                target_rows = []
                where = " AND ".join(f"{q(name)}=%s" for name in order_cols)
                for source_row in source_rows:
                    key = tuple(source_row[indexes[name]] for name in order_cols)
                    target_row = pg_conn.execute(
                        f"SELECT {select_cols} FROM {q(schema)}.{q(table)} WHERE {where}", key
                    ).fetchone()
                    target_rows.append(target_row)
            else:
                target_rows = pg_conn.execute(
                    f"SELECT {select_cols} FROM {q(schema)}.{q(table)} ORDER BY {order} LIMIT 3"
                ).fetchall()
            if None in target_rows or digest_rows(source_rows) != digest_rows(target_rows):
                sample_mismatches.append({"table": table, "sample": "first_3_by_pk"})
        objects = dict(
            pg_conn.execute(
                "SELECT 'tables',count(*) FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' "
                "UNION ALL SELECT 'views',count(*) FROM information_schema.views WHERE table_schema=%s "
                "UNION ALL SELECT 'triggers',count(*) FROM information_schema.triggers WHERE trigger_schema=%s "
                "UNION ALL SELECT 'indexes',count(*) FROM pg_indexes WHERE schemaname=%s",
                (schema, schema, schema, schema),
            ).fetchall()
        )
        constraints = dict(
            pg_conn.execute(
                "SELECT contype,count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
                "WHERE n.nspname=%s GROUP BY contype", (schema,)
            ).fetchall()
        )
        invalid_constraints = pg_conn.execute(
            "SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
            "WHERE n.nspname=%s AND NOT c.convalidated", (schema,)
        ).fetchone()[0]
        # Prove write permission without leaving an object or row behind.
        pg_conn.execute("SAVEPOINT qa_write")
        pg_conn.execute(f"CREATE TABLE {q(schema)}._qa_write_smoke(id BIGINT PRIMARY KEY)")
        pg_conn.execute(f"INSERT INTO {q(schema)}._qa_write_smoke VALUES (1)")
        write_readback = pg_conn.execute(
            f"SELECT id FROM {q(schema)}._qa_write_smoke"
        ).fetchone()[0]
        pg_conn.execute("ROLLBACK TO SAVEPOINT qa_write")
        pg_conn.commit()
        meta_present = bool(
            pg_conn.execute(
                f"SELECT 1 FROM {q(schema)}._migration_meta WHERE key='schema_version' AND value='2.7.0'"
            ).fetchone()
        )
    integrity = sqlite_conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_source = len(sqlite_conn.execute("PRAGMA foreign_key_check").fetchall())
    sqlite_conn.close()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "schema": schema,
        "source_snapshot": str(snapshot),
        "tables_compared": len(tables),
        "row_count_mismatches": row_mismatches,
        "sample_hash_mismatches": sample_mismatches,
        "postgres_objects": objects,
        "postgres_constraints": constraints,
        "postgres_invalid_constraints": invalid_constraints,
        "transactional_write_readback": write_readback,
        "migration_meta_present": meta_present,
        "source_integrity": integrity,
        "source_fk_violations": fk_source,
    }
    report["passed"] = not any((
        row_mismatches,
        sample_mismatches,
        invalid_constraints,
        integrity != "ok",
        fk_source,
        write_readback != 1,
        not meta_present,
    ))
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
