#!/usr/bin/env python
"""Migrate the canonical SQLite market database to Supabase PostgreSQL.

The script never prints credentials. It uses a SQLite backup-API snapshot, creates
an isolated PostgreSQL schema, copies base tables with COPY, and then restores
constraints, indexes, views, guard triggers, and PostgreSQL full-text search.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE = ROOT / "data" / "market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
BACKUP_DIR = ROOT / "backups"
ARTIFACT_DIR = ROOT / "artifacts"
DOTENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def safe_name(prefix: str, *parts: str) -> str:
    raw = "_".join((prefix, *parts))
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", raw).lower()
    if len(clean) <= 60:
        return clean
    digest = hashlib.sha1(clean.encode()).hexdigest()[:10]
    return clean[:49] + "_" + digest


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


def source_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    result: list[str] = []
    virtual_prefixes: list[str] = []
    for name, sql in rows:
        if (sql or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
            virtual_prefixes.append(name + "_")
            continue
        if any(name.startswith(prefix) for prefix in virtual_prefixes):
            continue
        # FTS shadow tables sort before/after depending on naming; exclude explicitly.
        if name.startswith("document_fts_"):
            continue
        result.append(name)
    return result


def pg_type(sqlite_type: str | None) -> str:
    declared = (sqlite_type or "").upper()
    if "INT" in declared:
        return "BIGINT"
    if any(token in declared for token in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if any(token in declared for token in ("NUM", "DEC")):
        return "NUMERIC"
    if "BLOB" in declared:
        return "BYTEA"
    return "TEXT"


def pg_default(value: str | None, target_type: str) -> str | None:
    if value is None:
        return None
    text = value.strip()
    lower = text.lower().replace(" ", "")
    if lower == "lower(hex(randomblob(16)))":
        return "md5(gen_random_uuid()::text)"
    if lower == "strftime('%y-%m-%dt%h:%m:%fz','now')":
        # Defensive only: SQLite format tokens are case-sensitive.
        return "to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"')"
    if text == "strftime('%Y-%m-%dT%H:%M:%fZ','now')":
        return "to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"')"
    if text.upper() == "CURRENT_TIMESTAMP" and target_type == "TEXT":
        return "CURRENT_TIMESTAMP::text"
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return text
    if text.upper() == "NULL":
        return "NULL"
    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    ):
        if text.startswith('"'):
            return "'" + text[1:-1].replace("'", "''") + "'"
        return text
    raise ValueError(f"unsupported SQLite default: {value!r}")


def extract_checks(create_sql: str) -> list[str]:
    checks: list[str] = []
    offset = 0
    while True:
        match = re.search(r"\bCHECK\s*\(", create_sql[offset:], re.IGNORECASE)
        if not match:
            break
        start = offset + match.end()
        depth = 1
        pos = start
        quote: str | None = None
        while pos < len(create_sql) and depth:
            char = create_sql[pos]
            if quote:
                if char == quote:
                    if pos + 1 < len(create_sql) and create_sql[pos + 1] == quote:
                        pos += 1
                    else:
                        quote = None
            elif char in "'\"":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            pos += 1
        if depth:
            raise ValueError("unbalanced CHECK expression")
        checks.append(create_sql[start : pos - 1].strip())
        offset = pos
    return checks


def translate_check(expr: str) -> str:
    # Keep JSON as source-faithful TEXT while enforcing parseability.
    translated = re.sub(
        r"\bjson_valid\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
        r"(\1::jsonb IS NOT NULL)",
        expr,
        flags=re.IGNORECASE,
    )
    # SQLite treats booleans as 0/1; PostgreSQL requires an explicit cast when
    # a CHECK sums mutually exclusive nullable targets.
    if re.search(r"\)\s*\+\s*\(", translated):
        translated = re.sub(
            r"\(([A-Za-z_][A-Za-z0-9_]*\s+IS\s+NOT\s+NULL)\)",
            r"((\1)::int)",
            translated,
            flags=re.IGNORECASE,
        )
    return translated


def table_ddl(sqlite_conn: sqlite3.Connection, table: str, schema: str) -> str:
    columns = sqlite_conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    definitions: list[str] = []
    pk_columns = [row for row in columns if row[5]]
    pk_columns.sort(key=lambda row: row[5])
    for _, name, declared, not_null, default, pk_order in columns:
        target_type = pg_type(declared)
        bits = [quote_ident(name), target_type]
        if not_null or pk_order:
            bits.append("NOT NULL")
        translated_default = pg_default(default, target_type)
        if translated_default is not None:
            bits.extend(("DEFAULT", translated_default))
        definitions.append(" ".join(bits))
    if pk_columns:
        definitions.append(
            "CONSTRAINT "
            + quote_ident(safe_name("pk", table))
            + " PRIMARY KEY ("
            + ", ".join(quote_ident(row[1]) for row in pk_columns)
            + ")"
        )
    return (
        f"CREATE TABLE {quote_ident(schema)}.{quote_ident(table)} (\n  "
        + ",\n  ".join(definitions)
        + "\n)"
    )


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")]


def unique_constraint_sql(conn: sqlite3.Connection, table: str, schema: str) -> list[str]:
    statements: list[str] = []
    number = 0
    for row in conn.execute(f"PRAGMA index_list({quote_ident(table)})"):
        _, index_name, is_unique, origin, _partial = row[:5]
        if not is_unique or origin != "u":
            continue
        cols = [x[2] for x in conn.execute(f"PRAGMA index_info({quote_ident(index_name)})")]
        if not cols or any(col is None for col in cols):
            raise ValueError(f"unsupported automatic expression unique index: {index_name}")
        number += 1
        name = safe_name("uq", table, str(number))
        statements.append(
            f"CREATE UNIQUE INDEX {quote_ident(name)} ON "
            f"{quote_ident(schema)}.{quote_ident(table)} ("
            + ", ".join(quote_ident(col) for col in cols)
            + ")"
        )
    return statements


def explicit_index_sql(conn: sqlite3.Connection, schema: str) -> list[str]:
    statements: list[str] = []
    rows = conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master "
        "WHERE type='index' AND sql IS NOT NULL ORDER BY name"
    )
    pattern = re.compile(
        r"^\s*CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:\"([^\"]+)\"|`([^`]+)`|\[([^\]]+)\]|([^\s]+))\s+ON\s+"
        r"(?:\"([^\"]+)\"|`([^`]+)`|\[([^\]]+)\]|([^\s(]+))(.*)$",
        re.IGNORECASE | re.DOTALL,
    )
    for name, table, sql in rows:
        if name == "ix_mentions_type_text":
            # PostgreSQL B-tree entries cannot exceed roughly 2.7KB; normalized_text
            # reaches 8.4KB. Separate indexes preserve exact-equality lookup through
            # bitmap combination without truncating or changing source values.
            statements.extend([
                f"CREATE INDEX {quote_ident(name + '_type')} ON "
                f"{quote_ident(schema)}.{quote_ident(table)} ({quote_ident('mention_type')})",
                f"CREATE INDEX {quote_ident(name + '_hash')} ON "
                f"{quote_ident(schema)}.{quote_ident(table)} USING hash ({quote_ident('normalized_text')})",
            ])
            continue
        match = pattern.match(sql)
        if not match:
            raise ValueError(f"cannot parse index SQL: {name}")
        unique = "UNIQUE " if match.group(1) else ""
        suffix = match.group(10)
        statements.append(
            f"CREATE {unique}INDEX {quote_ident(name)} ON "
            f"{quote_ident(schema)}.{quote_ident(table)}{suffix}"
        )
    return statements


def fk_sql(conn: sqlite3.Connection, tables: Iterable[str], schema: str) -> list[str]:
    statements: list[str] = []
    for table in tables:
        grouped: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in conn.execute(f"PRAGMA foreign_key_list({quote_ident(table)})"):
            grouped[row[0]].append(row)
        for fk_id, rows in grouped.items():
            rows.sort(key=lambda row: row[1])
            referred = rows[0][2]
            local_cols = [row[3] for row in rows]
            remote_cols = [row[4] for row in rows]
            on_update = rows[0][5].upper()
            on_delete = rows[0][6].upper()
            name = safe_name("fk", table, str(fk_id), referred)
            sql = (
                f"ALTER TABLE {quote_ident(schema)}.{quote_ident(table)} "
                f"ADD CONSTRAINT {quote_ident(name)} FOREIGN KEY ("
                + ", ".join(quote_ident(x) for x in local_cols)
                + f") REFERENCES {quote_ident(schema)}.{quote_ident(referred)} ("
                + ", ".join(quote_ident(x) for x in remote_cols)
                + ")"
            )
            if on_update != "NO ACTION":
                sql += " ON UPDATE " + on_update
            if on_delete != "NO ACTION":
                sql += " ON DELETE " + on_delete
            statements.append(sql)
    return statements


def check_sql(conn: sqlite3.Connection, tables: Iterable[str], schema: str) -> list[str]:
    statements: list[str] = []
    for table in tables:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        for number, expr in enumerate(extract_checks(row[0] or ""), start=1):
            name = safe_name("ck", table, str(number))
            statements.append(
                f"ALTER TABLE {quote_ident(schema)}.{quote_ident(table)} "
                f"ADD CONSTRAINT {quote_ident(name)} CHECK ({translate_check(expr)})"
            )
    return statements


def view_sql(conn: sqlite3.Connection, schema: str) -> list[str]:
    result: list[str] = []
    rows = list(conn.execute("SELECT name, sql FROM sqlite_master WHERE type='view'"))
    sql_by_name = {name: sql for name, sql in rows}
    remaining = dict(sql_by_name)
    ordered: list[tuple[str, str]] = []
    while remaining:
        ready = []
        for name, sql in remaining.items():
            dependencies = {
                other for other in sql_by_name
                if other != name and re.search(rf"\b{re.escape(other)}\b", sql, re.IGNORECASE)
            }
            if dependencies.issubset({created for created, _ in ordered}):
                ready.append(name)
        if not ready:
            raise ValueError(f"cyclic or unresolved view dependencies: {sorted(remaining)}")
        for name in sorted(ready):
            ordered.append((name, remaining.pop(name)))
    for name, sql in ordered:
        body = re.sub(
            r"^\s*CREATE\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\"[^\"]+\"|\S+)\s+AS\s+",
            "",
            sql,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        body = re.sub(
            r"group_concat\s*\(\s*DISTINCT\s+([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)\s*\)",
            r"string_agg(DISTINCT \1::text, ',')",
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(
            r"\b([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)\s+IS\s+"
            r"([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)\b",
            r"\1 IS NOT DISTINCT FROM \2",
            body,
            flags=re.IGNORECASE,
        )
        # SQLite INTEGER is 64-bit, while PostgreSQL integer is 32-bit. Monetary
        # decimal text in LP views reaches 12–13 digits, so preserve it as numeric.
        body = re.sub(
            r"CAST\s*\(\s*([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*_decimal)\s+AS\s+INTEGER\s*\)",
            r"CAST(\1 AS numeric)",
            body,
            flags=re.IGNORECASE,
        )
        if name == "v_measurement_catalog":
            body = re.sub(
                r"GROUP BY\s+d\.measurement_definition_id\s*$",
                "GROUP BY d.measurement_definition_id, p.code, p.name_ko",
                body,
                flags=re.IGNORECASE,
            )
        elif name == "v_event_feed":
            body = re.sub(
                r"GROUP BY\s+e\.event_id\s*$",
                "GROUP BY e.event_id, ec.code, ec.name_ko",
                body,
                flags=re.IGNORECASE,
            )
        result.append(
            f"CREATE VIEW {quote_ident(schema)}.{quote_ident(name)} AS\n{body}"
        )
    return result


def trigger_sql(schema: str) -> list[str]:
    q = quote_ident(schema)
    return [
        f"""CREATE FUNCTION {q}.raise_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION '%', TG_ARGV[0]; END; $$""",
        f"""CREATE FUNCTION {q}.completed_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF OLD.status_code = 'COMPLETE' THEN RAISE EXCEPTION 'completed snapshot is immutable'; END IF; RETURN NEW; END; $$""",
        f"""CREATE FUNCTION {q}.macro_supersedes_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF NEW.supersedes_observation_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM {q}.macro_observations p WHERE p.macro_observation_id=NEW.supersedes_observation_id
 AND p.macro_series_id=NEW.macro_series_id AND p.period_start=NEW.period_start AND p.period_end=NEW.period_end
) THEN RAISE EXCEPTION 'superseded observation must have the same series and period'; END IF; RETURN NEW; END; $$""",
        f"""CREATE FUNCTION {q}.measurement_dimension_kind_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected TEXT; actual TEXT;
BEGIN SELECT value_kind INTO expected FROM {q}.measurement_dimension_definitions WHERE measurement_dimension_id=NEW.measurement_dimension_id;
actual := CASE WHEN NEW.option_id IS NOT NULL THEN 'OPTION' WHEN NEW.text_value IS NOT NULL THEN 'TEXT'
 WHEN NEW.decimal_value_text IS NOT NULL THEN 'DECIMAL' WHEN NEW.integer_value IS NOT NULL THEN 'INTEGER'
 WHEN NEW.boolean_value IS NOT NULL THEN 'BOOLEAN' WHEN NEW.date_value IS NOT NULL THEN 'DATE'
 WHEN NEW.spatial_unit_value_id IS NOT NULL THEN 'SPATIAL_UNIT' END;
IF expected IS DISTINCT FROM actual THEN RAISE EXCEPTION 'measurement dimension value kind mismatch'; END IF; RETURN NEW; END; $$""",
        f"""CREATE FUNCTION {q}.measurement_unit_dimension_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF EXISTS (SELECT 1 FROM {q}.measurement_definitions d JOIN {q}.units s ON s.unit_code=NEW.source_unit_code
 JOIN {q}.units n ON n.unit_code=NEW.normalized_unit_code WHERE d.measurement_definition_id=NEW.measurement_definition_id
 AND (s.dimension_code<>d.dimension_code OR n.dimension_code<>d.dimension_code))
THEN RAISE EXCEPTION 'measurement unit dimension mismatch'; END IF; RETURN NEW; END; $$""",
        f"""CREATE FUNCTION {q}.measurement_selection_target_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF NOT EXISTS (SELECT 1 FROM {q}.measurement_facts f WHERE f.measurement_fact_id=NEW.selected_measurement_fact_id
 AND f.measurement_definition_id=NEW.measurement_definition_id AND f.asset_id IS NOT DISTINCT FROM NEW.asset_id
 AND f.project_id IS NOT DISTINCT FROM NEW.project_id AND f.spatial_unit_id IS NOT DISTINCT FROM NEW.spatial_unit_id
 AND f.event_id IS NOT DISTINCT FROM NEW.event_id AND f.region_id IS NOT DISTINCT FROM NEW.region_id)
THEN RAISE EXCEPTION 'selected measurement fact definition or target mismatch'; END IF; RETURN NEW; END; $$""",
        f"CREATE TRIGGER completed_snapshot_no_update BEFORE UPDATE ON {q}.snapshots FOR EACH ROW EXECUTE FUNCTION {q}.completed_snapshot_guard()",
        f"CREATE TRIGGER snapshot_no_delete BEFORE DELETE ON {q}.snapshots FOR EACH ROW EXECUTE FUNCTION {q}.raise_immutable('snapshot history is append-only')",
        f"CREATE TRIGGER document_version_no_update BEFORE UPDATE ON {q}.document_versions FOR EACH ROW EXECUTE FUNCTION {q}.raise_immutable('document version is immutable; insert a new version')",
        f"CREATE TRIGGER document_version_no_delete BEFORE DELETE ON {q}.document_versions FOR EACH ROW EXECUTE FUNCTION {q}.raise_immutable('document version is immutable')",
        f"CREATE TRIGGER macro_observation_no_update BEFORE UPDATE ON {q}.macro_observations FOR EACH ROW EXECUTE FUNCTION {q}.raise_immutable('macro observation is append-only; insert a revision')",
        f"CREATE TRIGGER macro_observation_no_delete BEFORE DELETE ON {q}.macro_observations FOR EACH ROW EXECUTE FUNCTION {q}.raise_immutable('macro observation is append-only')",
        f"CREATE TRIGGER macro_release_no_update BEFORE UPDATE ON {q}.macro_releases FOR EACH ROW EXECUTE FUNCTION {q}.raise_immutable('macro release is append-only')",
        f"CREATE TRIGGER macro_release_no_delete BEFORE DELETE ON {q}.macro_releases FOR EACH ROW EXECUTE FUNCTION {q}.raise_immutable('macro release is append-only')",
        f"CREATE TRIGGER macro_observation_supersedes_guard BEFORE INSERT ON {q}.macro_observations FOR EACH ROW EXECUTE FUNCTION {q}.macro_supersedes_guard()",
        f"CREATE TRIGGER measurement_fact_dimension_kind_guard BEFORE INSERT ON {q}.measurement_fact_dimensions FOR EACH ROW EXECUTE FUNCTION {q}.measurement_dimension_kind_guard()",
        f"CREATE TRIGGER measurement_fact_unit_dimension_guard BEFORE INSERT ON {q}.measurement_facts FOR EACH ROW EXECUTE FUNCTION {q}.measurement_unit_dimension_guard()",
        f"CREATE TRIGGER measurement_selection_target_guard BEFORE INSERT ON {q}.measurement_fact_selections FOR EACH ROW EXECUTE FUNCTION {q}.measurement_selection_target_guard()",
    ]


def fts_sql(schema: str) -> list[str]:
    q = quote_ident(schema)
    return [
        f"""CREATE VIEW {q}.document_fts AS
SELECT dv.document_version_id AS rowid,
       dv.document_version_id,
       dv.title,
       coalesce(dv.stored_text, dv.snippet_text, '') AS body,
       setweight(to_tsvector('simple', coalesce(dv.title,'')), 'A') ||
       setweight(to_tsvector('simple', coalesce(dv.stored_text, dv.snippet_text, '')), 'B') AS search_vector
FROM {q}.document_versions dv""",
    ]


def create_backup(source: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"market-pre-supabase-migration-{stamp}.db"
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def execute_many(pg_conn, statements: Iterable[str], phase: str) -> int:
    count = 0
    for statement in statements:
        try:
            pg_conn.execute(statement)
            count += 1
        except Exception as exc:
            raise RuntimeError(f"{phase} failed at statement {count + 1}: {exc}") from exc
    return count


def copy_table(sqlite_conn: sqlite3.Connection, pg_conn, schema: str, table: str) -> int:
    columns = table_columns(sqlite_conn, table)
    select_sql = "SELECT " + ", ".join(quote_ident(c) for c in columns) + " FROM " + quote_ident(table)
    copy_sql = (
        f"COPY {quote_ident(schema)}.{quote_ident(table)} ("
        + ", ".join(quote_ident(c) for c in columns)
        + ") FROM STDIN"
    )
    count = 0
    cursor = sqlite_conn.execute(select_sql)
    with pg_conn.cursor().copy(copy_sql) as copier:
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                copier.write_row(tuple(row))
                count += 1
    return count


def source_inventory(conn: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    return {table: conn.execute(f"SELECT count(*) FROM {quote_ident(table)}").fetchone()[0] for table in tables}


def verify(pg_conn, schema: str, expected: dict[str, int]) -> dict:
    actual: dict[str, int] = {}
    mismatches: list[dict] = []
    for table, source_count in expected.items():
        target_count = pg_conn.execute(
            f"SELECT count(*) FROM {quote_ident(schema)}.{quote_ident(table)}"
        ).fetchone()[0]
        actual[table] = target_count
        if target_count != source_count:
            mismatches.append({"table": table, "source": source_count, "target": target_count})
    fk_invalid = pg_conn.execute(
        "SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
        "WHERE n.nspname=%s AND c.contype='f' AND NOT c.convalidated", (schema,)
    ).fetchone()[0]
    return {
        "expected_tables": len(expected),
        "row_count_mismatches": mismatches,
        "source_rows": sum(expected.values()),
        "target_rows": sum(actual.values()),
        "unvalidated_foreign_keys": fk_invalid,
    }


def migrate(args: argparse.Namespace) -> dict:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required; run with uv --with 'psycopg[binary]'") from exc
    env = load_env(args.env)
    dsn = env.get("SUPABASE_DB_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is missing")
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise SystemExit("unsafe SUPABASE_DB_SCHEMA")
    snapshot = create_backup(args.sqlite)
    sqlite_conn = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row
    tables = source_tables(sqlite_conn)
    inventory = source_inventory(sqlite_conn, tables)
    result: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": str(snapshot),
        "schema": schema,
        "tables": len(tables),
        "source_rows": sum(inventory.values()),
        "phases": {},
    }
    with psycopg.connect(dsn, connect_timeout=20) as pg_conn:
        pg_conn.execute("SET statement_timeout TO 0")
        exists = pg_conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (schema,)
        ).fetchone()
        if exists:
            table_count = pg_conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema=%s", (schema,)
            ).fetchone()[0]
            if not args.replace:
                raise SystemExit(f"target schema already exists with {table_count} tables; use --replace only after review")
            pg_conn.execute(f"DROP SCHEMA {quote_ident(schema)} CASCADE")
            pg_conn.commit()
        pg_conn.execute(f"CREATE SCHEMA {quote_ident(schema)}")
        pg_conn.execute(f"CREATE EXTENSION IF NOT EXISTS pgcrypto")
        result["phases"]["tables_created"] = execute_many(
            pg_conn, (table_ddl(sqlite_conn, table, schema) for table in tables), "create tables"
        )
        pg_conn.commit()
        copied: dict[str, int] = {}
        for table in tables:
            copied[table] = copy_table(sqlite_conn, pg_conn, schema, table)
            pg_conn.commit()
        result["phases"]["rows_copied"] = sum(copied.values())
        result["phases"]["automatic_unique_indexes"] = execute_many(
            pg_conn,
            (stmt for table in tables for stmt in unique_constraint_sql(sqlite_conn, table, schema)),
            "automatic unique indexes",
        )
        result["phases"]["explicit_indexes"] = execute_many(
            pg_conn, explicit_index_sql(sqlite_conn, schema), "explicit indexes"
        )
        result["phases"]["checks"] = execute_many(
            pg_conn, check_sql(sqlite_conn, tables, schema), "check constraints"
        )
        result["phases"]["foreign_keys"] = execute_many(
            pg_conn, fk_sql(sqlite_conn, tables, schema), "foreign keys"
        )
        pg_conn.execute("SELECT set_config('search_path', %s, true)", (f"{schema},public",))
        result["phases"]["views"] = execute_many(pg_conn, view_sql(sqlite_conn, schema), "views")
        result["phases"]["triggers_and_functions"] = execute_many(
            pg_conn, trigger_sql(schema), "triggers"
        )
        result["phases"]["fts_objects"] = execute_many(pg_conn, fts_sql(schema), "fts")
        pg_conn.execute(
            f"CREATE TABLE {quote_ident(schema)}._migration_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        meta = {
            "source_sqlite": str(args.sqlite),
            "source_snapshot": str(snapshot),
            "schema_version": "2.7.0",
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "direction": "sqlite_to_supabase_initial_load",
        }
        for key, value in meta.items():
            pg_conn.execute(
                f"INSERT INTO {quote_ident(schema)}._migration_meta(key,value) VALUES (%s,%s)",
                (key, value),
            )
        pg_conn.commit()
        result["verification"] = verify(pg_conn, schema, inventory)
    sqlite_conn.close()
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = ARTIFACT_DIR / "supabase-initial-migration-result.json"
    artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["artifact"] = str(artifact)
    return result


def finalize(args: argparse.Namespace) -> dict:
    """Finish a reviewed partial migration after all base-table COPY commits succeeded."""
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required; run with uv --with 'psycopg[binary]'") from exc
    env = load_env(args.env)
    dsn = env.get("SUPABASE_DB_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is missing")
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    snapshots = sorted(BACKUP_DIR.glob("market-pre-supabase-migration-*.db"), key=lambda p: p.stat().st_mtime)
    if not snapshots:
        raise SystemExit("no pre-migration snapshot found")
    snapshot = snapshots[-1]
    sqlite_conn = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row
    tables = source_tables(sqlite_conn)
    inventory = source_inventory(sqlite_conn, tables)
    result = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": str(snapshot),
        "schema": schema,
        "tables": len(tables),
        "source_rows": sum(inventory.values()),
        "mode": "finalize_partial_copy",
        "phases": {},
    }
    with psycopg.connect(dsn, connect_timeout=20) as pg_conn:
        pg_conn.execute("SET statement_timeout TO 0")
        if not pg_conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (schema,)
        ).fetchone():
            raise SystemExit("target schema does not exist; run migrate")
        precheck = verify(pg_conn, schema, inventory)
        if precheck["row_count_mismatches"]:
            raise SystemExit("partial COPY row counts do not match; rerun migrate --replace")
        result["pre_finalize_verification"] = precheck
        result["phases"]["automatic_unique_indexes"] = execute_many(
            pg_conn,
            (stmt for table in tables for stmt in unique_constraint_sql(sqlite_conn, table, schema)),
            "automatic unique indexes",
        )
        result["phases"]["explicit_indexes"] = execute_many(
            pg_conn, explicit_index_sql(sqlite_conn, schema), "explicit indexes"
        )
        result["phases"]["checks"] = execute_many(
            pg_conn, check_sql(sqlite_conn, tables, schema), "check constraints"
        )
        result["phases"]["foreign_keys"] = execute_many(
            pg_conn, fk_sql(sqlite_conn, tables, schema), "foreign keys"
        )
        pg_conn.execute("SELECT set_config('search_path', %s, true)", (f"{schema},public",))
        result["phases"]["views"] = execute_many(pg_conn, view_sql(sqlite_conn, schema), "views")
        result["phases"]["triggers_and_functions"] = execute_many(
            pg_conn, trigger_sql(schema), "triggers"
        )
        result["phases"]["fts_objects"] = execute_many(pg_conn, fts_sql(schema), "fts")
        pg_conn.execute(
            f"CREATE TABLE {quote_ident(schema)}._migration_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        meta = {
            "source_sqlite": str(args.sqlite),
            "source_snapshot": str(snapshot),
            "schema_version": "2.7.0",
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "direction": "sqlite_to_supabase_initial_load",
        }
        for key, value in meta.items():
            pg_conn.execute(
                f"INSERT INTO {quote_ident(schema)}._migration_meta(key,value) VALUES (%s,%s)",
                (key, value),
            )
        pg_conn.commit()
        result["verification"] = verify(pg_conn, schema, inventory)
    sqlite_conn.close()
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = ARTIFACT_DIR / "supabase-initial-migration-result.json"
    artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["artifact"] = str(artifact)
    return result


def dry_run(args: argparse.Namespace) -> dict:
    conn = sqlite3.connect(f"file:{args.sqlite.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    tables = source_tables(conn)
    env = load_env(args.env)
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    report = {
        "tables": len(tables),
        "rows": sum(source_inventory(conn, tables).values()),
        "table_ddls": len([table_ddl(conn, table, schema) for table in tables]),
        "automatic_unique_indexes": sum(len(unique_constraint_sql(conn, table, schema)) for table in tables),
        "explicit_indexes": len(explicit_index_sql(conn, schema)),
        "checks": len(check_sql(conn, tables, schema)),
        "foreign_keys": len(fk_sql(conn, tables, schema)),
        "views": len(view_sql(conn, schema)),
        "trigger_statements": len(trigger_sql(schema)),
        "fts_objects": len(fts_sql(schema)),
    }
    conn.close()
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("dry-run", "migrate", "finalize"))
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "dry-run":
        result = dry_run(args)
    elif args.command == "finalize":
        result = finalize(args)
    else:
        result = migrate(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
