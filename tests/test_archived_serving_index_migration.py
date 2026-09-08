from pathlib import Path
import sqlite3

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.2.0_active_serving_archive_index.sql"
SQLITE_MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.2.0_active_serving_archive_index.sqlite.sql"
SCHEMA = ROOT / "db" / "v2" / "schema.sql"


def test_archive_index_migration_is_version_gated_and_self_contained() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "Expected schema 3.1.0" in sql
    assert "CREATE TABLE market_intelligence.archive_snapshots" in sql
    assert "CREATE TABLE market_intelligence.archived_serving_index" in sql
    assert "archive_snapshot_sha256" in sql
    assert "archive_locator" in sql
    assert "UNIQUE(record_kind, record_id)" in sql
    assert "REFERENCES market_intelligence.archive_snapshots" in sql
    assert "REFERENCES market_intelligence.source_documents" not in sql
    assert "REFERENCES market_intelligence.events" not in sql
    assert "schema_value = '3.2.0'" in sql


def test_fresh_schema_supports_compact_archive_index() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE TABLE archive_snapshots" in sql
    assert "CREATE TABLE archived_serving_index" in sql
    assert "archive_locator TEXT NOT NULL" in sql
    assert "UNIQUE(record_kind, record_id)" in sql
    assert "('schema_version', '3.5.0')" in sql


def test_existing_sqlite_archive_can_migrate_from_31(tmp_path: Path) -> None:
    db = tmp_path / "archive.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY, schema_value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES('schema_version','3.1.0');
        """)
        conn.executescript(SQLITE_MIGRATION.read_text(encoding="utf-8"))
        version = conn.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()[0]
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
        assert version == "3.2.0"
        assert {"archive_snapshots", "archived_serving_index"} <= tables
    finally:
        conn.close()


def test_fresh_sqlite_schema_builds_archive_index_tables(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
        assert {"archive_snapshots", "archived_serving_index"} <= tables
        version = conn.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()[0]
        assert version == "3.5.0"
    finally:
        conn.close()
