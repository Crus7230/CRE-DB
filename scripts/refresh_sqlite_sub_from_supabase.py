#!/usr/bin/env python
"""Build a validated local SQLite sub replica from Supabase PostgreSQL main."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
ARTIFACT_DIR = ROOT / "artifacts"
BACKUP_DIR = ROOT / "backups"
DOTENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = DOTENV_RE.match(text)
        if match:
            values[match.group(1)] = match.group(2).strip().strip("\"'")
    return values


def base_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [
        name for name, sql in rows
        if not (sql or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE")
        and not name.startswith("document_fts_")
    ]


def backup_api(source: Path, target: Path) -> None:
    src = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()


def build_replica(template: Path, output: Path, env_path: Path) -> dict:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    env = load_env(env_path)
    dsn = env.get("SUPABASE_DB_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is missing")
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit(f"refusing to overwrite candidate: {output}")
    backup_api(template, output)
    sqlite_conn = sqlite3.connect(output, timeout=60)
    sqlite_conn.execute("PRAGMA busy_timeout=60000")
    trigger_rows = sqlite_conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
    ).fetchall()
    tables = base_tables(sqlite_conn)
    counts: dict[str, int] = {}
    try:
        sqlite_conn.execute("PRAGMA foreign_keys=OFF")
        for name, _sql in trigger_rows:
            sqlite_conn.execute(f"DROP TRIGGER {q(name)}")
        for table in tables:
            sqlite_conn.execute(f"DELETE FROM {q(table)}")
        sqlite_conn.commit()
        with psycopg.connect(dsn, connect_timeout=20) as pg_conn:
            pg_conn.execute("SET statement_timeout TO 0")
            for table in tables:
                sqlite_cols = [row[1] for row in sqlite_conn.execute(f"PRAGMA table_info({q(table)})")]
                pg_cols = [
                    row[0] for row in pg_conn.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                        (schema, table),
                    )
                ]
                if sqlite_cols != pg_cols:
                    raise RuntimeError(f"column mismatch for {table}")
                select_sql = (
                    f"SELECT {', '.join(q(c) for c in pg_cols)} FROM {q(schema)}.{q(table)}"
                )
                insert_sql = (
                    f"INSERT INTO {q(table)} ({', '.join(q(c) for c in sqlite_cols)}) "
                    f"VALUES ({', '.join('?' for _ in sqlite_cols)})"
                )
                count = 0
                with pg_conn.cursor(name=f"replica_{table}") as cursor:
                    cursor.execute(select_sql)
                    while True:
                        rows = cursor.fetchmany(1000)
                        if not rows:
                            break
                        sqlite_conn.executemany(insert_sql, [tuple(row) for row in rows])
                        count += len(rows)
                counts[table] = count
                sqlite_conn.commit()
        for _name, sql in trigger_rows:
            if sql:
                sqlite_conn.execute(sql)
        try:
            sqlite_conn.execute("INSERT INTO document_fts(document_fts) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass
        sqlite_conn.commit()
        sqlite_conn.execute("PRAGMA foreign_keys=ON")
        integrity = sqlite_conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = sqlite_conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk:
            raise RuntimeError(f"replica validation failed: integrity={integrity}, fk={len(fk)}")
        local_counts = {table: sqlite_conn.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0] for table in tables}
        mismatches = [
            {"table": table, "postgres": counts[table], "sqlite": local_counts[table]}
            for table in tables if counts[table] != local_counts[table]
        ]
        if mismatches:
            raise RuntimeError(f"row count mismatch in {len(mismatches)} tables")
        sqlite_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        sqlite_conn.close()
    result = {
        "status": "validated_candidate",
        "direction": "supabase_to_sqlite",
        "schema": schema,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate": str(output.resolve()),
        "tables": len(tables),
        "rows": sum(counts.values()),
        "integrity": integrity,
        "foreign_key_violations": len(fk),
        "row_count_mismatches": mismatches,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    return result


def activate(candidate: Path, live: Path) -> dict:
    if not candidate.exists():
        raise SystemExit(f"candidate not found: {candidate}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"market-pre-sub-activation-{stamp}.db"
    backup_api(live, backup)
    # Clear the previous replica's read-only bit only for atomic replacement.
    if live.exists():
        os.chmod(live, stat.S_IREAD | stat.S_IWRITE)
    # os.replace is atomic on the same volume. Candidate and live are both under data/ by default.
    os.replace(candidate, live)
    # Enforce the sub contract at the filesystem boundary on Windows.
    os.chmod(live, stat.S_IREAD)
    return {
        "activated": True,
        "live": str(live.resolve()),
        "backup": str(backup.resolve()),
        "local_sub_read_only": not os.access(live, os.W_OK),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "market.sub.candidate.db")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument(
        "--activate-existing",
        action="store_true",
        help="activate the already validated candidate after digest and SQLite checks",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact = ARTIFACT_DIR / "supabase-to-sqlite-replica-result.json"
    if args.activate_existing:
        candidate = args.output.resolve()
        if not candidate.exists() or not artifact.exists():
            raise SystemExit("validated candidate or artifact is missing")
        prior = json.loads(artifact.read_text(encoding="utf-8"))
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        conn = sqlite3.connect(f"file:{candidate.as_posix()}?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            conn.close()
        if prior.get("sha256") != digest or integrity != "ok" or fk or prior.get("row_count_mismatches"):
            raise SystemExit("candidate revalidation failed")
        result = prior
        result["activation"] = activate(candidate, args.template.resolve())
        result["status"] = "activated_sub_replica"
        result["activated_at"] = datetime.now(timezone.utc).isoformat()
    else:
        result = build_replica(args.template.resolve(), args.output.resolve(), args.env.resolve())
        if args.activate:
            result["activation"] = activate(args.output.resolve(), args.template.resolve())
            result["status"] = "activated_sub_replica"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["artifact"] = str(artifact.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
