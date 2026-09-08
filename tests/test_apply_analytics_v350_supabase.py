"""No-network checks for scoped, transactional analytics serving publication."""
from pathlib import Path
import json
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from scripts import apply_analytics_v350_supabase as apply_sync  # noqa: E402


def payload():
    result = {table: [] for table in apply_sync.TABLE_COLUMNS}
    result["_sync_scope"] = {"keyword_start": "2026-08-01", "keyword_end": "2026-09-01"}
    return result


def row(table, **values):
    return tuple(values.get(column) for column in apply_sync.TABLE_COLUMNS[table])


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, staged=None, version="3.5.0", lock=True):
        self.staged = staged or {table: 0 for table in apply_sync.TABLE_COLUMNS}
        self.totals = dict(self.staged)
        self.matched = dict(self.staged)
        self.window_counts = dict(self.staged)
        self.version, self.lock = version, lock
        self.queries = []
        self.invalid_substring = None
        self.commits = self.rollbacks = 0
        self.closed = False
        self.latest = [("KEYWORD_DAILY", "fresh-run", "2026-08-31T06:30:00Z",
                        "2026-06-01", "2026-09-01", 15000, 3000)]

    def execute(self, sql, parameters=None, **kwargs):
        self.queries.append((sql, parameters))
        if "pg_try_advisory_xact_lock" in sql:
            return Result([(self.lock,)])
        if "SELECT schema_value" in sql:
            return Result([(self.version,)])
        if "to_regclass" in sql:
            return Result([("market_intelligence.analytics_refresh_runs",)])
        if "DISTINCT ON (pipeline_code)" in sql:
            return Result(self.latest)
        if sql.startswith("SELECT count(*) FROM _sync_"):
            table = re.search(r"FROM _sync_(\w+)", sql).group(1)
            return Result([(self.matched[table],)])
        if sql.startswith("SELECT count(*) FROM market_intelligence."):
            table = re.search(r"FROM market_intelligence\.(\w+)", sql).group(1)
            if "JOIN _sync_" in sql:
                invalid = self.invalid_substring is not None and self.invalid_substring in sql
                return Result([(int(invalid),)])
            count = self.window_counts[table] if "WHERE bucket_date" in sql else self.totals[table]
            return Result([(count,)])
        return Result([(None,)])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class ApplyAnalyticsServingTest(unittest.TestCase):
    def invoke(self, conn, source=None, apply=False, sync_only=True):
        source = source or payload()
        counts = {table: len(source[table]) for table in apply_sync.TABLE_COLUMNS}
        fake_psycopg = types.SimpleNamespace(connect=Mock(return_value=conn))
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}), \
             patch.object(apply_sync, "_load_env", return_value={"SUPABASE_DB_URL": "test-only"}), \
             patch.object(apply_sync.sqlite3, "connect"), \
             patch.object(apply_sync, "build_payload", return_value=source), \
             patch.object(apply_sync, "sync_payload", return_value=counts), \
             patch.object(apply_sync, "migration_body", side_effect=AssertionError("no migration DDL allowed")):
            return apply_sync.run(Path("test.env"), Path("test.db"), apply=apply,
                                  sync_only=sync_only, window_days=90)

    def test_sync_only_skips_security_and_schema_migrations_and_reads_back(self):
        conn = Connection()
        result = self.invoke(conn, apply=True)
        self.assertEqual(conn.commits, 1)
        self.assertTrue(conn.closed)
        self.assertFalse(result["migrationDdlApplied"])
        self.assertEqual(result["verification"]["status"], "passed")
        self.assertEqual(result["persistedLatestAnalyticsCompletion"][0]["runId"], "fresh-run")
        sql = "\n".join(query for query, _ in conn.queries)
        self.assertNotIn("app_security", sql)
        self.assertNotIn("CREATE TABLE", sql)
        lock_queries = [args for query, args in conn.queries if "pg_try_advisory_xact_lock" in query]
        self.assertEqual(lock_queries, [apply_sync.ANALYTICS_SYNC_LOCK])

    def test_sync_only_rejects_old_schema_without_ddl(self):
        conn = Connection(version="3.4.1")
        with self.assertRaisesRegex(RuntimeError, "sync-only requires Supabase schema 3.5.0"):
            self.invoke(conn)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_concurrent_sync_is_rejected_before_schema_or_writes(self):
        conn = Connection(lock=False)
        with self.assertRaisesRegex(RuntimeError, "already running"):
            self.invoke(conn)
        self.assertFalse(any("schema_value" in sql for sql, _ in conn.queries))
        self.assertEqual(conn.commits, 0)

    def test_rehearsal_rolls_back_and_reads_persisted_completions(self):
        conn = Connection()
        result = self.invoke(conn)
        self.assertEqual(result["status"], "rollback_rehearsal")
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(sum("DISTINCT ON" in sql for sql, _ in conn.queries), 2)

    def test_missing_staged_primary_key_rejects_and_rolls_back(self):
        source = payload()
        source["insight_signals"] = [row("insight_signals", insight_signal_id="missing-signal")]
        conn = Connection({table: len(source[table]) for table in apply_sync.TABLE_COLUMNS})
        conn.matched["insight_signals"] = 0
        with self.assertRaisesRegex(RuntimeError, "staged primary keys/counts"):
            self.invoke(conn, source, apply=True)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_source_payload_uses_consistent_sqlite_read_transaction(self):
        conn, source = Connection(), Mock()
        with patch.object(apply_sync.sqlite3, "connect", return_value=source), \
             patch.object(apply_sync, "build_payload", side_effect=RuntimeError("test stop")), \
             patch.object(apply_sync, "_load_env", return_value={"SUPABASE_DB_URL": "test-only"}), \
             patch.dict(sys.modules, {"psycopg": types.SimpleNamespace(connect=Mock(return_value=conn))}):
            with self.assertRaisesRegex(RuntimeError, "test stop"):
                apply_sync.run(Path("test.env"), Path("test.db"), apply=False, sync_only=True, window_days=90)
        source.execute.assert_called_once_with("BEGIN")
        source.rollback.assert_called_once_with()
        source.close.assert_called_once_with()

    def test_retained_out_of_window_rows_are_not_count_mismatches(self):
        conn = Connection()
        conn.totals["keyword_observations_daily"] = 2500
        conn.totals["insight_signals"] = 20
        result = self.invoke(conn)
        tables = result["verification"]["tables"]
        self.assertEqual(tables["keyword_observations_daily"]["retainedOutsideScope"], 2500)
        self.assertEqual(tables["keyword_observations_daily"]["targetInScope"], 0)
        self.assertEqual(tables["insight_signals"]["scope"], "staged_primary_keys")
        self.assertEqual(tables["insight_signals"]["retainedOutsideScope"], 20)

    def test_unreconciled_rows_inside_window_fail(self):
        conn = Connection()
        conn.totals["keyword_observations_daily"] = 1
        conn.window_counts["keyword_observations_daily"] = 1
        with self.assertRaisesRegex(RuntimeError, "keyword window reconciliation"):
            self.invoke(conn)

    def test_invalid_keyword_reference_fails(self):
        conn = Connection()
        conn.invalid_substring = "referenced.keyword_id=target.keyword_left_id"
        with self.assertRaisesRegex(RuntimeError, "keyword_cooccurrences_daily.keyword_left_id"):
            self.invoke(conn)

    def test_unresolved_evidence_version_fails(self):
        conn = Connection()
        conn.invalid_substring = "target.metadata_json::jsonb"
        with self.assertRaisesRegex(RuntimeError, "insight_signal_evidence.source_document_version"):
            self.invoke(conn)

    def test_preparation_preserves_original_version_in_metadata_without_source_mutation(self):
        source = payload()
        source["insight_signal_evidence"] = [row(
            "insight_signal_evidence", insight_signal_evidence_id="e1",
            source_document_version_id="archive-version-1", metadata_json='{"source_name":"news"}')]
        prepared = apply_sync.prepare_payload(source)
        metadata = json.loads(prepared["insight_signal_evidence"][0][8])
        self.assertEqual(metadata["source_document_version_id"], "archive-version-1")
        self.assertEqual(metadata["source_name"], "news")
        self.assertEqual(json.loads(source["insight_signal_evidence"][0][8]), {"source_name": "news"})

    def test_duplicate_staged_keys_fail_before_connection(self):
        source = payload()
        item = row("keyword_dictionary", keyword_id="duplicate")
        source["keyword_dictionary"] = [item, item]
        with self.assertRaisesRegex(RuntimeError, "duplicate staged primary key"):
            apply_sync.prepare_payload(source)

    def test_half_open_window_rejects_end_date(self):
        source = payload()
        source["keyword_observations_daily"] = [row(
            "keyword_observations_daily", keyword_observation_id="o1", bucket_date="2026-09-01")]
        with self.assertRaisesRegex(RuntimeError, "outside keyword sync window"):
            apply_sync.prepare_payload(source)

    def test_archive_fallback_requires_current_validated_matching_locator(self):
        sql = apply_sync._archive_exists("DOCUMENT", "staged.source_document_version_id", "source_document_version_id")
        for fragment in ("snapshot.is_current=1", "snapshot.integrity_status='VALIDATED'",
                         "snapshot.foreign_key_violations=0",
                         "snapshot.archive_snapshot_sha256=archived.archive_snapshot_sha256",
                         "length(trim(archived.archive_locator))>0",
                         "archived.source_document_version_id=staged.source_document_version_id"):
            self.assertIn(fragment, sql)


if __name__ == "__main__":
    unittest.main()
