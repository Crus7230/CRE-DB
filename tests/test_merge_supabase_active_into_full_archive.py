import sqlite3
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
import sys
import tempfile
import types
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.merge_supabase_active_into_full_archive import (
    PRESERVED_ANALYTICS_TABLES,
    document_watermark,
    merge_archive,
    merge_table_names,
    preserved_analytics_report,
    require_schema_version,
    upsert_rows,
)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class FakePostgres:
    """SQLite-backed PG read adapter; records every requested server statement."""
    def __init__(self, source):
        self.source = source
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args=()):
        self.statements.append(sql)
        if sql.startswith("SET "):
            return Rows([])
        if "information_schema.tables" in sql:
            return self.source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if "information_schema.columns" in sql:
            return Rows([(row[1],) for row in self.source.execute(f'PRAGMA table_info("{args[1]}")')])
        return self.source.execute(sql.replace('"market_intelligence".', ''), args)

    def cursor(self, name):
        pg = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                self.result = pg.execute(sql)

            def fetchmany(self, count):
                return self.result.fetchmany(count)

        return Cursor()


def fixture_database(path, *, local):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY, schema_value TEXT);
        INSERT INTO schema_meta VALUES('schema_version','3.5.0');
        CREATE TABLE collection_sources(source_id TEXT PRIMARY KEY, source_code TEXT);
        INSERT INTO collection_sources VALUES('rss','GOOGLE_NEWS_RSS');
        CREATE TABLE source_documents(document_id TEXT PRIMARY KEY, source_id TEXT, canonical_url TEXT UNIQUE);
        CREATE TABLE document_versions(document_version_id TEXT PRIMARY KEY, document_id TEXT, collected_at TEXT, published_at TEXT);
    """)
    distinct = "archive" if local else "new"
    for doc in ("shared", distinct):
        conn.execute("INSERT INTO source_documents VALUES(?, 'rss', ?)", (doc, f"https://example.test/{doc}"))
        collected = "2026-08-20T01:00:00Z" if local else "2026-08-31T01:00:00Z"
        conn.execute("INSERT INTO document_versions VALUES(?,?,?,?)", (f"version-{doc}", doc, collected, collected))
    for table in PRESERVED_ANALYTICS_TABLES:
        conn.execute(f'CREATE TABLE "{table}"(id TEXT PRIMARY KEY, value TEXT)')
        conn.execute(f'INSERT INTO "{table}" VALUES(?,?)', ("shared", "fresh-local" if local else "stale-remote"))
    conn.commit()
    return conn


class ArchiveMergeTests(unittest.TestCase):
    def test_upsert_preserves_archive_only_rows_and_updates_active(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE sample(id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            conn.executemany("INSERT INTO sample VALUES(?,?)", [("archived", "CLOSED"), ("shared", "OLD")])
            upsert_rows(conn, "sample", ["id", "status"], ["id"], [("shared", "ACTIVE"), ("new", "ACTIVE")])
            self.assertEqual(conn.execute("SELECT * FROM sample ORDER BY id").fetchall(), [
                ("archived", "CLOSED"), ("new", "ACTIVE"), ("shared", "ACTIVE"),
            ])

    def test_upsert_serializes_postgres_json_values_for_sqlite(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE sample(id TEXT PRIMARY KEY, metadata_json TEXT, values_json TEXT, amount NUMERIC, observed_at TEXT, external_id TEXT)")
            upsert_rows(conn, "sample", ["id", "metadata_json", "values_json", "amount", "observed_at", "external_id"], ["id"], [
                ("row-1", {"source": "postgres"}, ["A", "B"], Decimal("123.45"),
                 datetime(2026, 9, 3, tzinfo=timezone.utc), UUID("00000000-0000-0000-0000-000000000001")),
            ])
            metadata, values, amount, observed_at, external_id = conn.execute(
                "SELECT metadata_json,values_json,amount,observed_at,external_id FROM sample WHERE id='row-1'"
            ).fetchone()
            self.assertEqual(json.loads(metadata), {"source": "postgres"})
            self.assertEqual(json.loads(values), ["A", "B"])
            self.assertEqual(amount, 123.45)
            self.assertEqual(observed_at, "2026-09-03T00:00:00+00:00")
            self.assertEqual(external_id, "00000000-0000-0000-0000-000000000001")

    def test_secondary_unique_conflict_never_replaces_archive_row(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE sample(id TEXT PRIMARY KEY, url TEXT UNIQUE)")
            conn.execute("INSERT INTO sample VALUES('archive','same-url')")
            with self.assertRaises(sqlite3.IntegrityError):
                upsert_rows(conn, "sample", ["id", "url"], ["id"], [("different-id", "same-url")])
            self.assertEqual(conn.execute("SELECT * FROM sample").fetchall(), [("archive", "same-url")])

    def test_merge_selection_keeps_local_analytics_out_of_remote_overwrites(self):
        tables = set(PRESERVED_ANALYTICS_TABLES) | {"schema_meta", "source_documents"}
        self.assertEqual(merge_table_names(tables, tables | {"_migration_meta"}), ["schema_meta", "source_documents"])
        with self.assertRaisesRegex(RuntimeError, "missing Supabase application tables"):
            merge_table_names(tables, tables | {"unknown_source_table"})
        with self.assertRaisesRegex(RuntimeError, "missing Supabase source tables"):
            merge_table_names(tables, tables - {"source_documents"})

    def test_merge_requires_full_local_analytics_schema(self):
        with self.assertRaisesRegex(RuntimeError, "missing local analytics tables"):
            merge_table_names({"schema_meta"}, {"schema_meta"})

    def test_version_must_be_350_on_both_sides(self):
        require_schema_version("3.5.0", "3.5.0")
        for local, remote in (("3.4.1", "3.5.0"), ("3.5.0", "3.6.0"), (None, "3.5.0")):
            with self.assertRaisesRegex(RuntimeError, "matching schema 3.5.0"):
                require_schema_version(local, remote)

    def test_preservation_report_rejects_changed_local_analytics(self):
        before = {table: 1 for table in PRESERVED_ANALYTICS_TABLES}
        self.assertEqual(len(preserved_analytics_report(before, before)), len(PRESERVED_ANALYTICS_TABLES))
        with self.assertRaisesRegex(RuntimeError, "preservation failed"):
            preserved_analytics_report(before, {**before, "insight_signals": 0})

    def test_candidate_merge_preserves_local_analytics_and_reports_freshness(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "archive.db"
            candidate = Path(folder) / "candidate.db"
            local = fixture_database(archive, local=True)
            local.close()
            remote = fixture_database(":memory:", local=False)
            pg = FakePostgres(remote)
            try:
                with patch.dict(sys.modules, {"psycopg": types.SimpleNamespace(connect=lambda *args, **kwargs: pg)}), patch(
                    "scripts.merge_supabase_active_into_full_archive.load_env", return_value={"SUPABASE_DB_URL": "not-a-real-dsn"}
                ):
                    report = merge_archive(archive, candidate, Path(folder) / ".env")
                with closing(sqlite3.connect(candidate)) as result:
                    self.assertEqual(result.execute("SELECT count(*) FROM source_documents").fetchone()[0], 3)
                    for table in PRESERVED_ANALYTICS_TABLES:
                        self.assertEqual(result.execute(f'SELECT value FROM "{table}"').fetchone()[0], "fresh-local")
                with closing(sqlite3.connect(archive)) as unchanged:
                    self.assertEqual(unchanged.execute("SELECT count(*) FROM source_documents").fetchone()[0], 2)
                self.assertEqual(report["source_freshness"]["document_versions"], 2)
                self.assertEqual(report["candidate_freshness"]["document_versions"], 3)
                self.assertEqual(report["source_freshness"]["rss_latest_collected_at"], "2026-08-31T01:00:00Z")
                self.assertEqual(report["source_freshness"]["rss_latest_collected_at"], report["candidate_freshness"]["rss_latest_collected_at"])
                self.assertEqual(report["source_snapshot"], "repeatable_read_read_only")
                self.assertIn("REPEATABLE READ, READ ONLY", pg.statements[0])
                self.assertTrue(all(sql.startswith(("SET ", "SELECT ")) for sql in pg.statements))
                self.assertTrue(all(table not in report["merged_tables"] for table in PRESERVED_ANALYTICS_TABLES))
            finally:
                remote.close()

    def test_rss_watermark_does_not_take_other_source_timestamp(self):
        conn = fixture_database(":memory:", local=True)
        try:
            conn.execute("INSERT INTO collection_sources VALUES('official','OFFICIAL')")
            conn.execute("INSERT INTO source_documents VALUES('official-doc','official','official-url')")
            conn.execute("INSERT INTO document_versions VALUES('official-version','official-doc','2026-08-31T09:00:00Z',NULL)")
            report = document_watermark(conn)
            self.assertEqual(report["latest_collected_at"], "2026-08-31T09:00:00Z")
            self.assertEqual(report["rss_latest_collected_at"], "2026-08-20T01:00:00Z")
        finally:
            conn.close()

    def test_candidate_conflict_rolls_back_and_leaves_live_archive_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "archive.db"
            candidate = Path(folder) / "candidate.db"
            fixture_database(archive, local=True).close()
            remote = fixture_database(":memory:", local=False)
            remote.execute("UPDATE source_documents SET canonical_url='https://example.test/archive' WHERE document_id='new'")
            pg = FakePostgres(remote)
            try:
                with patch.dict(sys.modules, {"psycopg": types.SimpleNamespace(connect=lambda *args, **kwargs: pg)}), patch(
                    "scripts.merge_supabase_active_into_full_archive.load_env", return_value={"SUPABASE_DB_URL": "not-a-real-dsn"}
                ), self.assertRaisesRegex(RuntimeError, "constraint conflict in source_documents"):
                    merge_archive(archive, candidate, Path(folder) / ".env")
                for path in (archive, candidate):
                    with closing(sqlite3.connect(path)) as conn:
                        self.assertEqual(conn.execute("SELECT document_id FROM source_documents ORDER BY document_id").fetchall(), [("archive",), ("shared",)])
                        self.assertEqual(document_watermark(conn)["latest_collected_at"], "2026-08-20T01:00:00Z")
            finally:
                remote.close()


if __name__ == "__main__":
    unittest.main()
