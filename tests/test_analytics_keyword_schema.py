from pathlib import Path
import sqlite3
import pytest

ROOT = Path(__file__).parents[1]
SQLITE = ROOT / "db" / "v2" / "migrations" / "3.4.0_keyword_analytics.sqlite.sql"
POSTGRES = ROOT / "db" / "v2" / "migrations" / "3.4.0_keyword_analytics.sql"
SCHEMA = ROOT / "db" / "v2" / "schema.sql"


def migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL);
      INSERT INTO schema_meta VALUES('schema_version','3.3.0');
      CREATE TABLE collection_sources(source_id TEXT PRIMARY KEY);
    """)
    conn.executescript(SQLITE.read_text(encoding="utf-8"))
    return conn


def test_analytics_migrations_are_additive_and_version_gated() -> None:
    sqlite_sql = SQLITE.read_text(encoding="utf-8")
    postgres_sql = POSTGRES.read_text(encoding="utf-8")
    assert "value='3.3.0'" in sqlite_sql
    assert "Expected schema 3.3.0" in postgres_sql
    for name in ("analytics_refresh_runs", "keyword_dictionary", "keyword_observations_daily", "keyword_cooccurrences_daily"):
        assert f"CREATE TABLE {name}" in sqlite_sql
        assert f"CREATE TABLE market_intelligence.{name}" in postgres_sql
    for protected in ("source_documents", "document_versions", "record_classifications"):
        assert f"DROP TABLE {protected}" not in sqlite_sql
    assert "DELETE FROM market_intelligence.source_documents" not in postgres_sql
    assert "schema_value='3.4.0'" in sqlite_sql
    assert "schema_value = '3.4.0'" in postgres_sql


def test_keyword_tables_preserve_algorithm_window_scope_and_idempotency_keys() -> None:
    conn = migrated()
    try:
        assert conn.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()[0] == "3.4.0"
        names = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
        assert {"analytics_refresh_runs", "keyword_dictionary", "keyword_observations_daily", "keyword_cooccurrences_daily"} <= names
        indexes = {row[1] for row in conn.execute("pragma index_list('keyword_observations_daily')")}
        assert "ux_keyword_observation_identity" in indexes
        columns = {row[1] for row in conn.execute("pragma table_info('keyword_observations_daily')")}
        assert {"computed_at", "window_start", "window_end", "algorithm_version", "source_scope_code", "document_frequency", "burst_score"} <= columns
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("insert into analytics_refresh_runs(analytics_refresh_run_id,pipeline_code,status_code,algorithm_version,started_at,metadata_json) values('bad','X','COMPLETED','V1','2026-08-22T00:00:00Z','[]')")
    finally:
        conn.close()


def test_fresh_schema_contains_keyword_analytics_contract() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    for name in ("analytics_refresh_runs", "keyword_dictionary", "keyword_observations_daily", "keyword_cooccurrences_daily"):
        assert f"CREATE TABLE {name}" in sql
    assert "('schema_version', '3.5.0')" in sql
