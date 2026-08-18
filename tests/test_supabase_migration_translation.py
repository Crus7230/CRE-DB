from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_sqlite_to_supabase.py"
spec = importlib.util.spec_from_file_location("migrate_sqlite_to_supabase", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_type_and_default_translation() -> None:
    assert module.pg_type("INTEGER") == "BIGINT"
    assert module.pg_type("REAL") == "DOUBLE PRECISION"
    assert module.pg_type("TEXT") == "TEXT"
    assert module.pg_default("lower(hex(randomblob(16)))", "TEXT") == "md5(gen_random_uuid()::text)"
    assert "to_char" in module.pg_default("strftime('%Y-%m-%dT%H:%M:%fZ','now')", "TEXT")


def test_check_extraction_and_json_translation() -> None:
    sql = "CREATE TABLE x(a TEXT CHECK (a IN ('x','y')), b TEXT CHECK (b IS NULL OR json_valid(b))) STRICT"
    checks = module.extract_checks(sql)
    assert checks == ["a IN ('x','y')", "b IS NULL OR json_valid(b)"]
    assert module.translate_check(checks[1]) == "b IS NULL OR (b::jsonb IS NOT NULL)"
    boolean_sum = "((asset_id IS NOT NULL) + (project_id IS NOT NULL) = 1)"
    translated = module.translate_check(boolean_sum)
    assert "((asset_id IS NOT NULL)::int)" in translated
    assert "((project_id IS NOT NULL)::int)" in translated


def test_source_tables_excludes_fts_shadow_tables(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE base(id INTEGER PRIMARY KEY, text_value TEXT);"
        "CREATE VIRTUAL TABLE document_fts USING fts5(text_value, content='base');"
    )
    tables = module.source_tables(conn)
    assert tables == ["base"]
    conn.close()


def test_view_translation_uses_numeric_for_decimal_amounts() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE t(a TEXT, amount_decimal TEXT);"
        "CREATE VIEW v AS SELECT group_concat(DISTINCT t.a) AS xs, "
        "CAST(t.amount_decimal AS INTEGER) AS amount FROM t;"
    )
    ddl = module.view_sql(conn, "market_intelligence")[0]
    assert "string_agg(DISTINCT t.a::text, ',')" in ddl
    assert "CAST(t.amount_decimal AS numeric)" in ddl
    conn.close()
