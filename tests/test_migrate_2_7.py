from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from schema_fixture_utils import seed_before_contextual

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"
MIGRATION = ROOT / "db" / "v2" / "migrations" / "2.7.0_post_collection_relationships.sql"
CLI = ROOT / "db" / "v2" / "migrate_2_7.py"
sys.path.insert(0, str(CLI.parent))
import migrate_2_7
MARKER = "-- ============================================================================\n-- 14. Post-collection relationship reconciliation (V2.7)"


def schema_26() -> str:
    text = SCHEMA.read_text(encoding="utf-8")
    prefix, rest = text.split(MARKER, 1)
    _, suffix = rest.split("INSERT INTO schema_meta", 1)
    return prefix + "INSERT INTO schema_meta" + suffix.replace("'2.9.0'", "'2.6.0'", 1)


class Migrate27Test(unittest.TestCase):
    def _create_v26(self, path: Path) -> None:
        con = sqlite3.connect(path)
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(schema_26())
        con.executescript(seed_before_contextual(SEED))
        con.execute("DROP TABLE predicate_relationship_rules")
        con.execute("DELETE FROM claim_role_definitions WHERE role_code='SUBJECT_ORGANIZATION'")
        con.execute("UPDATE schema_meta SET schema_value='2.6.0' WHERE schema_key='schema_version'")
        con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES('legacy','COMPANY','기존회사')")
        con.commit(); con.close()

    def test_sql_migration_preserves_v26_and_adds_relationship_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "v26.db"
            self._create_v26(db)
            con = sqlite3.connect(db)
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(MIGRATION.read_text(encoding="utf-8"))
            self.assertEqual('2.7.0', con.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0])
            self.assertEqual('기존회사', con.execute("SELECT canonical_name FROM organizations WHERE organization_id='legacy'").fetchone()[0])
            self.assertIsNotNone(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relationship_resolution_runs'").fetchone())
            self.assertIsNotNone(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='predicate_relationship_rules'").fetchone())
            self.assertIsNotNone(con.execute("SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_relationship_gaps'").fetchone())
            self.assertEqual(8, con.execute("SELECT COUNT(*) FROM predicate_relationship_rules").fetchone()[0])
            self.assertIsNotNone(con.execute("SELECT 1 FROM claim_role_definitions WHERE role_code='SUBJECT_ORGANIZATION'").fetchone())
            self.assertEqual([], con.execute("PRAGMA foreign_key_check").fetchall())
            self.assertEqual('ok', con.execute("PRAGMA integrity_check").fetchone()[0])
            con.close()

    def test_cli_backs_up_before_migration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "v26.db"; backup = Path(td) / "before.db"
            self._create_v26(db)
            run = subprocess.run([sys.executable, str(CLI), str(db), '--backup', str(backup)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertTrue(backup.exists())
            current=sqlite3.connect(db); previous=sqlite3.connect(backup)
            self.assertEqual('2.7.0', current.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0])
            self.assertEqual('2.6.0', previous.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0])
            current.close(); previous.close()

    def test_validation_failure_rolls_back_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "v26.db"
            self._create_v26(db)
            con = migrate_2_7.connect(db)
            impossible = set(migrate_2_7.REQUIRED_RULES) | {
                ('BUSINESS_DOMAIN','TENANT','BUSINESS_ACTIVITY',None,'VERIFIED')
            }
            with mock.patch.object(migrate_2_7, 'REQUIRED_RULES', impossible):
                with self.assertRaises(RuntimeError):
                    try:
                        con.executescript(MIGRATION.read_text(encoding='utf-8'))
                        migrate_2_7.validate_migration(con)
                        con.commit()
                    except Exception:
                        con.rollback()
                        raise
            self.assertEqual('2.6.0', migrate_2_7.version(con))
            self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relationship_resolution_runs'").fetchone())
            con.close()

    def test_already_applied_validation_detects_corrupt_required_rule(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "v26.db"; backup = Path(td) / "before.db"
            self._create_v26(db)
            first = subprocess.run([sys.executable, str(CLI), str(db), '--backup', str(backup)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            con = sqlite3.connect(db)
            con.execute("UPDATE predicate_relationship_rules SET auto_apply=0 WHERE relationship_rule_id='participant-role-tenant'")
            con.commit(); con.close()
            second = subprocess.run([sys.executable, str(CLI), str(db)], cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(0, second.returncode)
            self.assertIn('missing_rules', second.stderr)


if __name__ == '__main__':
    unittest.main()
