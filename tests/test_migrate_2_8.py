from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sqlite3
import tempfile

import pytest

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "db" / "v2" / "migrate_2_8.py"
SPEC = spec_from_file_location("migrate_2_8", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
migrate = MODULE.migrate


def test_v28_sqlite_migration_adds_version_bound_enrichment():
    with tempfile.TemporaryDirectory() as temp_dir:
        db = Path(temp_dir) / "market.db"
        connection = sqlite3.connect(db)
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY, schema_value TEXT NOT NULL) STRICT;
            INSERT INTO schema_meta VALUES('schema_version','2.7.0');
            CREATE TABLE document_versions(document_version_id TEXT PRIMARY KEY) STRICT;
            """
        )
        connection.close()
        result = migrate(db)
        connection = sqlite3.connect(db)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(document_enrichments)")}
        version = connection.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0]
        assert result["integrity"] == "ok"
        assert version == "2.8.0"
        assert {"document_version_id", "summary_text", "safe_excerpt", "pipeline_version"} <= columns
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.close()


def test_migration_is_atomic_on_sql_failure():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "market.db"
        migration_path = Path(temp_dir) / "broken.sql"
        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE schema_meta (schema_key TEXT PRIMARY KEY, schema_value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '2.7.0');
            CREATE TABLE document_versions (document_version_id TEXT PRIMARY KEY);
            """
        )
        connection.close()
        migration_path.write_text(
            """
            CREATE TABLE partial_table (id TEXT PRIMARY KEY);
            SELECT * FROM table_that_does_not_exist;
            UPDATE schema_meta SET schema_version='2.8.0' WHERE schema_name='market_intelligence_v2';
            """,
            encoding="utf-8",
        )

        original_migration = MODULE.MIGRATION
        MODULE.MIGRATION = migration_path
        try:
            with pytest.raises(sqlite3.OperationalError):
                migrate(db_path)
        finally:
            MODULE.MIGRATION = original_migration

        connection = sqlite3.connect(db_path)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='partial_table'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0] == "2.7.0"
        connection.close()


def test_migration_rejects_preexisting_incomplete_table():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "market.db"
        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            CREATE TABLE schema_meta (schema_key TEXT PRIMARY KEY, schema_value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '2.7.0');
            CREATE TABLE document_versions (document_version_id TEXT PRIMARY KEY);
            CREATE TABLE document_enrichments (
                document_enrichment_id TEXT PRIMARY KEY,
                document_version_id TEXT NOT NULL,
                status_code TEXT NOT NULL,
                review_status TEXT NOT NULL
            );
            """
        )
        connection.close()

        with pytest.raises(RuntimeError, match="PREEXISTING_DOCUMENT_ENRICHMENTS_TABLE"):
            migrate(db_path)

        connection = sqlite3.connect(db_path)
        columns = [row[1] for row in connection.execute("PRAGMA table_info(document_enrichments)")]
        assert columns == ["document_enrichment_id", "document_version_id", "status_code", "review_status"]
        assert connection.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0] == "2.7.0"
        connection.close()
