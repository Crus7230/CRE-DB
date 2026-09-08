#!/usr/bin/env python
"""Merge Supabase active serving rows into the local full archive without deletion."""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.refresh_sqlite_sub_from_supabase import (
    activate,
    backup_api,
    base_tables,
    ensure_replica_schema_allowed,
    load_env,
    q,
    validate_table_coverage,
)
from scripts.sync_analytics_serving import TABLE_COLUMNS

DEFAULT_ARCHIVE = ROOT / "data" / "market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
EXPECTED_SCHEMA_VERSION = "3.5.0"
PRESERVED_ANALYTICS_TABLES = frozenset(TABLE_COLUMNS)
STATEMENT_TIMEOUT_MS = 120_000


def merge_table_names(sqlite_tables: set[str], postgres_tables: set[str]) -> list[str]:
    """Check both schemas, while retaining locally computed analytics unchanged."""
    validate_table_coverage(sqlite_tables, postgres_tables)
    missing_source = sorted(sqlite_tables - postgres_tables)
    if missing_source:
        raise RuntimeError("missing Supabase source tables: " + ", ".join(missing_source))
    missing_analytics = sorted(PRESERVED_ANALYTICS_TABLES - sqlite_tables)
    if missing_analytics:
        raise RuntimeError("missing local analytics tables: " + ", ".join(missing_analytics))
    return sorted(sqlite_tables - PRESERVED_ANALYTICS_TABLES)


def require_schema_version(local_version: str | None, source_version: str | None) -> None:
    if local_version != EXPECTED_SCHEMA_VERSION or source_version != local_version:
        raise RuntimeError(
            "archive merge requires matching schema 3.5.0: "
            f"local={local_version or 'missing'}, source={source_version or 'missing'}"
        )


def document_watermark(conn, schema: str | None = None) -> dict:
    prefix = f"{q(schema)}." if schema else ""
    row = conn.execute(
        f"SELECT count(*), max(collected_at), max(published_at) FROM {prefix}document_versions"
    ).fetchone()
    documents = conn.execute(f"SELECT count(*) FROM {prefix}source_documents").fetchone()[0]
    rss_latest = conn.execute(
        f"SELECT max(dv.collected_at) FROM {prefix}document_versions dv "
        f"JOIN {prefix}source_documents sd ON sd.document_id=dv.document_id "
        f"JOIN {prefix}collection_sources cs ON cs.source_id=sd.source_id "
        "WHERE cs.source_code='GOOGLE_NEWS_RSS'"
    ).fetchone()[0]
    return {
        "documents": documents,
        "document_versions": row[0],
        "latest_collected_at": row[1],
        "latest_published_at": row[2],
        "rss_latest_collected_at": rss_latest,
    }


def preserved_analytics_report(before: dict[str, int], after: dict[str, int]) -> dict:
    changed = sorted(table for table in PRESERVED_ANALYTICS_TABLES if before[table] != after[table])
    if changed:
        raise RuntimeError("local analytics preservation failed: " + ", ".join(changed))
    return {
        table: {"rows_before": before[table], "rows_after": after[table]}
        for table in sorted(PRESERVED_ANALYTICS_TABLES)
    }


def upsert_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    primary_key: list[str],
    rows: list[tuple],
) -> None:
    if not rows:
        return
    if not primary_key:
        raise RuntimeError(f"primary key required for archive merge: {table}")
    update_columns = [column for column in columns if column not in primary_key]
    conflict = ", ".join(q(column) for column in primary_key)
    update = ", ".join(f"{q(column)}=excluded.{q(column)}" for column in update_columns)
    action = f"DO UPDATE SET {update}" if update else "DO NOTHING"
    sql = (
        f"INSERT INTO {q(table)} ({', '.join(q(column) for column in columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT ({conflict}) {action}"
    )
    def sqlite_value(value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        return value

    normalized_rows = [tuple(sqlite_value(value) for value in row) for row in rows]
    conn.executemany(sql, normalized_rows)


def merge_archive(archive: Path, candidate: Path, env_path: Path) -> dict:
    """Build a validated candidate only; callers serialize activation/refresh with a DB lock."""
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    archive = archive.resolve()
    candidate = candidate.resolve()
    if candidate == archive:
        raise SystemExit("archive and candidate must be different files")
    if not archive.is_file():
        raise SystemExit("archive file is missing")
    if candidate.exists():
        raise SystemExit(f"refusing to overwrite candidate: {candidate}")
    env = load_env(env_path)
    dsn = env.get("SUPABASE_DB_URL")
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is missing")
    ensure_replica_schema_allowed(schema)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    backup_api(archive, candidate)
    conn = sqlite3.connect(candidate, timeout=60)
    merged: dict[str, int] = {}
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        triggers = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()
        tables = base_tables(conn)
        before = {table: conn.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0] for table in tables}
        local_version_row = conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()
        local_version = local_version_row[0] if local_version_row else None
        archive_documents_before = document_watermark(conn)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        for name, _ in triggers:
            conn.execute(f"DROP TRIGGER {q(name)}")
        with psycopg.connect(dsn, connect_timeout=20) as pg:
            # Every table must describe one snapshot, even if collection continues.
            pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            pg.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'")
            pg.execute("SET LOCAL lock_timeout = '10s'")
            postgres_tables = {
                row[0] for row in pg.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_type='BASE TABLE'", (schema,)
                )
            }
            merge_tables = merge_table_names(set(tables), postgres_tables)
            source_version_row = pg.execute(
                f"SELECT schema_value FROM {q(schema)}.schema_meta WHERE schema_key='schema_version'"
            ).fetchone()
            source_version = source_version_row[0] if source_version_row else None
            require_schema_version(local_version, source_version)
            source_documents = document_watermark(pg, schema)
            for table in merge_tables:
                info = conn.execute(f"PRAGMA table_info({q(table)})").fetchall()
                columns = [row[1] for row in info]
                primary_key = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
                pg_columns = [
                    row[0] for row in pg.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                        (schema, table),
                    )
                ]
                if columns != pg_columns:
                    raise RuntimeError(f"column mismatch for {table}")
                count = 0
                with pg.cursor(name=f"archive_merge_{table}") as cursor:
                    cursor.execute(f"SELECT {', '.join(q(c) for c in columns)} FROM {q(schema)}.{q(table)}")
                    while True:
                        batch = cursor.fetchmany(1000)
                        if not batch:
                            break
                        try:
                            upsert_rows(conn, table, columns, primary_key, [tuple(row) for row in batch])
                        except sqlite3.IntegrityError as exc:
                            # Never REPLACE/drop archive rows to resolve a second unique key.
                            raise RuntimeError(f"archive merge constraint conflict in {table}") from exc
                        count += len(batch)
                merged[table] = count
        for _, sql in triggers:
            if sql:
                conn.execute(sql)
        fts_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='document_fts' AND type='table'").fetchone()
        if fts_exists:
            conn.execute("INSERT INTO document_fts(document_fts) VALUES('rebuild')")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk:
            raise RuntimeError(f"archive merge validation failed: integrity={integrity}, fk={len(fk)}")
        after = {table: conn.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0] for table in tables}
        shrunk = [table for table in tables if after[table] < before[table]]
        if shrunk:
            raise RuntimeError("full archive rows shrank: " + ", ".join(shrunk))
        preserved = preserved_analytics_report(before, after)
        archive_documents_after = document_watermark(conn)
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and checkpoint[0]:
            raise RuntimeError("candidate WAL checkpoint was blocked")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "status": "validated_full_archive_candidate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate": str(candidate),
        "schema_version": source_version,
        "source_snapshot": "repeatable_read_read_only",
        "tables": len(tables),
        "rows_before": sum(before.values()),
        "rows_after": sum(after.values()),
        "rows_added": sum(after.values()) - sum(before.values()),
        "source_rows_merged": sum(merged.values()),
        "merged_tables": merged,
        "analytics_policy": "preserve_local_derived_tables",
        "preserved_analytics": preserved,
        "source_documents": source_documents,
        "source_freshness": source_documents,
        "candidate_freshness": archive_documents_after,
        "archive_documents_before": archive_documents_before,
        "archive_documents_after": archive_documents_after,
        "integrity": integrity,
        "foreign_key_violations": len(fk),
        "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
    }


def main() -> None:
    p=argparse.ArgumentParser();p.add_argument("--archive",type=Path,default=DEFAULT_ARCHIVE);p.add_argument("--output",type=Path,default=ROOT/"data"/"market.full-archive.candidate.db");p.add_argument("--env",type=Path,default=DEFAULT_ENV);p.add_argument("--activate",action="store_true");args=p.parse_args()
    result=merge_archive(args.archive.resolve(),args.output.resolve(),args.env.resolve())
    if args.activate:
        result["activation"]=activate(args.output.resolve(),args.archive.resolve());result["status"]="activated_full_archive"
    artifact=ROOT/"artifacts"/"supabase-active-to-full-archive-merge-result.json";artifact.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");result["artifact"]=str(artifact.resolve());print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
