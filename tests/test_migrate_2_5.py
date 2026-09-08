from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from schema_fixture_utils import seed_before_contextual

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"
MIGRATION = ROOT / "db" / "v2" / "migrations" / "2.5.0_lp_mandates.sql"
CLI = ROOT / "db" / "v2" / "migrate_2_5.py"
MARKER = "-- ============================================================================\n-- 12. Institutional LP manager mandates, awards and disclosed deployments"


def schema_24() -> str:
    text = SCHEMA.read_text(encoding="utf-8")
    prefix, rest = text.split(MARKER, 1)
    _, suffix = rest.split("INSERT INTO schema_meta", 1)
    return prefix + "INSERT INTO schema_meta" + suffix.replace("'3.5.0'", "'2.4.0'", 1)


class Migrate25Test(unittest.TestCase):
    def _create_v24(self, path: Path) -> None:
        con = sqlite3.connect(path)
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(schema_24())
        con.executescript(seed_before_contextual(SEED, legacy_version="2.4.0"))
        con.execute(
            "INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES('legacy_org','COMPANY','기존조직')"
        )
        con.commit()
        con.close()

    def test_sql_migration_preserves_v24_rows_and_adds_lp_tables(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "v24.db"
            self._create_v24(db)
            con = sqlite3.connect(db)
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(MIGRATION.read_text(encoding="utf-8"))
            version = con.execute(
                "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
            ).fetchone()[0]
            legacy = con.execute(
                "SELECT canonical_name FROM organizations WHERE organization_id='legacy_org'"
            ).fetchone()[0]
            tables = {
                row[0]
                for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertEqual("2.5.0", version)
            self.assertEqual("기존조직", legacy)
            self.assertIn("lp_mandates", tables)
            self.assertEqual(
                {"MANAGER_RFP_OPEN", "MANAGER_SELECTED"},
                {row[0] for row in con.execute(
                    "SELECT stage_code FROM event_stages WHERE stage_code IN ('MANAGER_RFP_OPEN','MANAGER_SELECTED')"
                )},
            )
            self.assertEqual(
                8,
                con.execute(
                    "SELECT COUNT(*) FROM predicate_definitions WHERE predicate_code LIKE 'LP_MANDATE_%'"
                ).fetchone()[0],
            )
            self.assertEqual([], con.execute("PRAGMA foreign_key_check").fetchall())
            self.assertEqual("ok", con.execute("PRAGMA integrity_check").fetchone()[0])
            con.close()

    def test_cli_creates_v24_backup_before_applying_v25(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "live.db"
            backup = Path(td) / "before.db"
            self._create_v24(db)
            run = subprocess.run(
                [sys.executable, str(CLI), str(db), "--backup", str(backup)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertTrue(backup.exists())
            current = sqlite3.connect(db)
            previous = sqlite3.connect(backup)
            self.assertEqual(
                "2.5.0",
                current.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0],
            )
            self.assertEqual(
                "2.4.0",
                previous.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0],
            )
            current.close()
            previous.close()


if __name__ == "__main__":
    unittest.main()
