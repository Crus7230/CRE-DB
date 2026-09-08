from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from libsql_client import create_client_sync

from publish_sqlite_to_turso import load_dotenv, quote_identifier, remote_counts


def table_order(source: sqlite3.Connection) -> list[str]:
    tables = {
        str(row[0])
        for row in source.execute(
            "SELECT name FROM pragma_table_list WHERE schema='main' "
            "AND type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    dependencies = {
        table: {
            str(row[2])
            for row in source.execute(f"PRAGMA foreign_key_list({quote_identifier(table)})")
            if str(row[2]) in tables and str(row[2]) != table
        }
        for table in tables
    }
    remaining = set(tables)
    ordered: list[str] = []
    while remaining:
        ready = sorted(table for table in remaining if not dependencies[table].intersection(remaining))
        if not ready:
            raise RuntimeError(f"cyclic table dependencies: {sorted(remaining)}")
        ordered.extend(ready)
        remaining.difference_update(ready)
    virtual = [
        str(row[0])
        for row in source.execute(
            "SELECT name FROM pragma_table_list WHERE schema='main' "
            "AND type='virtual' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return ordered + virtual


def row_batches(cursor: sqlite3.Cursor, size: int) -> Iterator[list[tuple[Any, ...]]]:
    while True:
        rows = cursor.fetchmany(size)
        if not rows:
            return
        yield rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume a compact SQLite publication into Turso over HTTP")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--batch-rows", type=int, default=500)
    args = parser.parse_args()
    if args.batch_rows < 1:
        raise SystemExit("--batch-rows must be positive")

    env = load_dotenv(args.env_file)
    url = env.get("TURSO_DATABASE_URL", "").replace("libsql://", "https://", 1)
    token = env.get("TURSO_AUTH_TOKEN", "")
    if not url or not token:
        raise SystemExit("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required")

    source = sqlite3.connect(f"file:{args.source.resolve().as_posix()}?mode=ro", uri=True)
    client = create_client_sync(url, auth_token=token)
    try:
        source_integrity = str(source.execute("PRAGMA integrity_check").fetchone()[0])
        source_fk = len(source.execute("PRAGMA foreign_key_check").fetchall())
        if source_integrity != "ok" or source_fk:
            raise RuntimeError(f"source validation failed: integrity={source_integrity}, fk={source_fk}")

        order = table_order(source)
        copied: dict[str, int] = {}
        for table in order:
            source_count = int(source.execute(f"SELECT count(*) FROM {quote_identifier(table)}").fetchone()[0])
            remote_count = int(client.execute(f"SELECT count(*) FROM {quote_identifier(table)}").rows[0][0])
            if remote_count == source_count:
                copied[table] = source_count
                print(json.dumps({"table": table, "rows": source_count, "action": "verified_existing"}), flush=True)
                continue
            if remote_count:
                raise RuntimeError(
                    f"partial remote table requires reconciliation: {table} "
                    f"source={source_count} remote={remote_count}"
                )

            columns = [str(row[1]) for row in source.execute(f"PRAGMA table_info({quote_identifier(table)})")]
            column_sql = ",".join(quote_identifier(column) for column in columns)
            placeholders = ",".join("?" for _ in columns)
            insert_sql = f"INSERT INTO {quote_identifier(table)} ({column_sql}) VALUES ({placeholders})"
            cursor = source.execute(f"SELECT {column_sql} FROM {quote_identifier(table)}")
            inserted = 0
            for batch in row_batches(cursor, args.batch_rows):
                client.batch([(insert_sql, row) for row in batch])
                inserted += len(batch)
            verified = int(client.execute(f"SELECT count(*) FROM {quote_identifier(table)}").rows[0][0])
            if verified != source_count:
                raise RuntimeError(f"post-load count mismatch: {table} source={source_count} remote={verified}")
            copied[table] = verified
            print(json.dumps({"table": table, "rows": verified, "action": "inserted"}), flush=True)

        existing_objects = {
            (str(row[0]), str(row[1]))
            for row in client.execute(
                "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).rows
        }
        schema_rows = source.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "AND sql IS NOT NULL AND type IN ('index','trigger','view') "
            "ORDER BY CASE type WHEN 'index' THEN 0 WHEN 'trigger' THEN 1 ELSE 2 END,name"
        ).fetchall()
        missing_sql = [
            str(sql)
            for object_type, name, sql in schema_rows
            if (str(object_type), str(name)) not in existing_objects
        ]
        if missing_sql:
            client.batch(missing_sql)

        remote = remote_counts(client, sorted(copied))
        mismatches = {
            table: {"source": count, "remote": remote.get(table)}
            for table, count in copied.items()
            if remote.get(table) != count
        }
        remote_fk = list(client.execute("PRAGMA foreign_key_check").rows)
        remote_integrity = str(client.execute("PRAGMA integrity_check").rows[0][0])
        object_counts = {
            str(row[0]): int(row[1])
            for row in client.execute(
                "SELECT type,count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                "GROUP BY type ORDER BY type"
            ).rows
        }
        if mismatches or remote_fk or remote_integrity != "ok":
            raise RuntimeError(
                f"remote validation failed: mismatch={len(mismatches)}, "
                f"fk={len(remote_fk)}, integrity={remote_integrity}"
            )

        report = {
            "status": "COMPLETED",
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "source": str(args.source.resolve()),
            "sourceBytes": args.source.stat().st_size,
            "sourceIntegrity": source_integrity,
            "sourceForeignKeyViolations": source_fk,
            "tableCount": len(copied),
            "rowCount": sum(copied.values()),
            "tableRows": copied,
            "remoteObjectCounts": object_counts,
            "remoteIntegrity": remote_integrity,
            "remoteForeignKeyViolations": len(remote_fk),
            "rowCountMismatches": mismatches,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": report["status"],
            "tableCount": report["tableCount"],
            "rowCount": report["rowCount"],
            "remoteIntegrity": report["remoteIntegrity"],
            "remoteForeignKeyViolations": report["remoteForeignKeyViolations"],
        }), flush=True)
    finally:
        client.close()
        source.close()


if __name__ == "__main__":
    main()