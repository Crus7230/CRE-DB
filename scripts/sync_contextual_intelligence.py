"""Upsert contextual-intelligence projections from authority SQLite to Supabase."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_contextual_intelligence_migration import DEFAULT_ENV, load_env

DEFAULT_DB = ROOT / "data" / "market.db"
SCHEMA = "market_intelligence"
SYNC_TABLES = [
    "contextual_rule_sets",
    "contextual_rules",
    "contextual_processing_campaigns",
    "contextual_document_runs",
    "legacy_derived_records",
    "contextual_event_frames",
    "contextual_frame_participants",
    "contextual_frame_targets",
    "contextual_impact_assertions",
    "contextual_review_decisions",
    "contextual_search_records",
]
JSON_COLUMNS = {
    "rule_scope_json", "metadata_json", "definition_json", "lineage_json",
    "participant_roles_json", "participant_entity_ids_json", "asset_ids_json",
    "region_ids_json", "industry_codes_json", "impact_directions_json",
}
BOOL_COLUMNS = {("contextual_rules", "is_active")}


def upsert_sql(table: str, columns: list[str], primary_key: list[str]) -> str:
    if table not in SYNC_TABLES or not primary_key:
        raise ValueError("unsafe contextual sync target")
    update_columns = [column for column in columns if column not in primary_key]
    conflict = ",".join(primary_key)
    action = "DO NOTHING" if not update_columns else "DO UPDATE SET " + ",".join(
        f"{column}=EXCLUDED.{column}" for column in update_columns
    )
    return (
        f"INSERT INTO {SCHEMA}.{table} ({','.join(columns)}) "
        f"VALUES ({','.join('%s' for _ in columns)}) "
        f"ON CONFLICT ({conflict}) {action}"
    )


def _chunks(rows: list[tuple], size: int = 1000) -> Iterable[list[tuple]]:
    for offset in range(0, len(rows), size):
        yield rows[offset:offset + size]


def _table_info(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[str]]:
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = [row[1] for row in info]
    primary_key = [row[1] for row in sorted(info, key=lambda item: item[5]) if row[5]]
    return columns, primary_key


def _convert_rows(table: str, columns: list[str], rows: list[tuple], Jsonb) -> list[tuple]:
    converted = []
    for row in rows:
        values = []
        for column, value in zip(columns, row):
            if value is not None and column in JSON_COLUMNS:
                value = Jsonb(json.loads(value) if isinstance(value, str) else value)
            elif (table, column) in BOOL_COLUMNS and value is not None:
                value = bool(value)
            values.append(value)
        converted.append(tuple(values))
    return converted


def _canonical_value(table: str, column: str, value):
    if value is None:
        return None
    if column in JSON_COLUMNS:
        return json.loads(value) if isinstance(value, str) else value
    if (table, column) in BOOL_COLUMNS:
        return bool(value)
    if isinstance(value, str) and column.endswith("_at"):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
        except ValueError:
            pass
    if isinstance(value, str) and value.endswith("+00:00"):
        return value[:-6] + "Z"
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if value.__class__.__module__ in {"decimal", "uuid"} else value


def canonical_rows_hash(table: str, columns: list[str], rows: list[tuple]) -> str:
    normalized = [
        [_canonical_value(table, column, value) for column, value in zip(columns, row)]
        for row in rows
    ]
    normalized.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, default=str))
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sync_contextual(db_path: Path, env_path: Path, *, apply: bool) -> dict:
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    env = load_env(env_path)
    dsn = env.get("SUPABASE_DB_URL")
    schema = env.get("SUPABASE_DB_SCHEMA", SCHEMA)
    if schema != SCHEMA or not dsn:
        raise SystemExit("market_intelligence Supabase DSN is required")
    local = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    report: dict[str, object] = {"mode": "apply" if apply else "rollback_rehearsal", "tables": {}}
    try:
        local_versions = [row[0] for row in local.execute("SELECT document_version_id FROM contextual_document_runs")]
        with psycopg.connect(dsn, connect_timeout=20, application_name="contextual-intelligence-sync") as pg:
            pg.execute("SET LOCAL statement_timeout = '300000ms'")
            pg.execute("SET LOCAL lock_timeout = '10000ms'")
            pg.execute("SELECT pg_advisory_xact_lock(hashtext('market_intelligence.contextual_intelligence_sync'))")
            feature = pg.execute(
                f"SELECT schema_value FROM {SCHEMA}.schema_meta WHERE schema_key='contextual_intelligence_schema_version'"
            ).fetchone()
            if not feature or feature[0] != "1.0.0":
                raise RuntimeError("Supabase contextual schema 1.0.0 is required")
            remote_versions: set[str] = set()
            for batch in _chunks([(item,) for item in local_versions], 2000):
                ids = [item[0] for item in batch]
                remote_versions.update(row[0] for row in pg.execute(
                    f"SELECT document_version_id FROM {SCHEMA}.document_versions WHERE document_version_id=ANY(%s)",
                    (ids,),
                ))
            missing_versions = sorted(set(local_versions) - remote_versions)
            report["missing_document_versions"] = len(missing_versions)
            if missing_versions:
                raise RuntimeError(f"Supabase is missing {len(missing_versions)} contextual source versions")

            for table in SYNC_TABLES:
                columns, primary_key = _table_info(local, table)
                remote_columns = [row[0] for row in pg.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                    (SCHEMA, table),
                )]
                if columns != remote_columns:
                    raise RuntimeError(f"column mismatch for {table}")
                rows = local.execute(
                    f'SELECT {",".join(chr(34)+column+chr(34) for column in columns)} FROM "{table}"'
                ).fetchall()
                sql = upsert_sql(table, columns, primary_key)
                with pg.cursor() as cursor:
                    for batch in _chunks(rows):
                        cursor.executemany(sql, _convert_rows(table, columns, batch, Jsonb))
                remote_count = pg.execute(f"SELECT count(*) FROM {SCHEMA}.{table}").fetchone()[0]
                if remote_count < len(rows):
                    raise RuntimeError(f"row count validation failed for {table}")
                if len(primary_key) != 1:
                    raise RuntimeError(f"content parity requires a single primary key for {table}")
                primary_index = columns.index(primary_key[0])
                remote_rows: list[tuple] = []
                for ids in _chunks([(row[primary_index],) for row in rows], 2000):
                    key_values = [item[0] for item in ids]
                    remote_rows.extend(pg.execute(
                        f"SELECT {','.join(columns)} FROM {SCHEMA}.{table} WHERE {primary_key[0]}=ANY(%s)",
                        (key_values,),
                    ).fetchall())
                content_match = (
                    len(remote_rows) == len(rows)
                    and canonical_rows_hash(table, columns, rows)
                    == canonical_rows_hash(table, columns, remote_rows)
                )
                if not content_match:
                    raise RuntimeError(f"canonical row parity failed for {table}")
                report["tables"][table] = {
                    "local": len(rows),
                    "remote_after": remote_count,
                    "remote_extra": remote_count - len(rows),
                    "content_match": True,
                }
            if apply:
                pg.commit()
                report["status"] = "applied"
            else:
                pg.rollback()
                report["status"] = "rollback_rehearsal_passed"
    finally:
        local.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(sync_contextual(args.db, args.env, apply=args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
