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
MIGRATION = ROOT / "db" / "v2" / "migrations" / "2.6.0_company_tenant_intelligence.sql"
CLI = ROOT / "db" / "v2" / "migrate_2_6.py"
MARKER = "-- ============================================================================\n-- 13. Point-in-time company universe, industry and property occupancy"


def schema_25() -> str:
    text = SCHEMA.read_text(encoding="utf-8")
    prefix, rest = text.split(MARKER, 1)
    _, suffix = rest.split("INSERT INTO schema_meta", 1)
    return prefix + "INSERT INTO schema_meta" + suffix.replace("'3.5.0'", "'2.5.0'", 1)


class Migrate26Test(unittest.TestCase):
    def _create_v25(self, path: Path) -> None:
        con = sqlite3.connect(path)
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(schema_25())
            con.executescript(seed_before_contextual(SEED))
            con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES('legacy_company','COMPANY','기존기업')")
            con.commit()
        finally:
            con.close()

    def test_sql_migration_preserves_v25_rows_and_adds_company_intelligence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "v25.db"
            self._create_v25(db)
            con = sqlite3.connect(db)
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(MIGRATION.read_text(encoding="utf-8"))
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            views = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='view'")}
            self.assertEqual("2.6.0", con.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0])
            self.assertEqual("기존기업", con.execute("SELECT canonical_name FROM organizations WHERE organization_id='legacy_company'").fetchone()[0])
            self.assertTrue({"industry_taxonomies", "industry_nodes", "organization_industry_assignments", "market_universe_snapshots", "market_universe_members", "organization_business_activities", "organization_property_occupancies"}.issubset(tables))
            self.assertTrue({"v_company_universe_current", "v_company_real_estate_timeline", "v_company_event_universe_context"}.issubset(views))
            self.assertEqual(0, con.execute("SELECT COUNT(*) FROM v_company_real_estate_timeline").fetchone()[0])
            self.assertEqual(1, con.execute("SELECT COUNT(*) FROM event_categories WHERE code='CORPORATE_RELOCATION'").fetchone()[0])
            self.assertEqual(6, con.execute("SELECT COUNT(*) FROM event_stages WHERE stage_code LIKE 'RELOCATION_%'").fetchone()[0])
            self.assertEqual(7, con.execute("SELECT COUNT(*) FROM predicate_definitions WHERE predicate_code IN ('BUSINESS_DOMAIN','INVESTMENT_PLAN_AMOUNT','INVESTMENT_PLAN_DESCRIPTION','HEADCOUNT_PLAN','RELOCATION_ORIGIN','RELOCATION_DESTINATION','EXPECTED_MOVE_IN_DATE')").fetchone()[0])
            self.assertEqual([], con.execute("PRAGMA foreign_key_check").fetchall())
            self.assertEqual("ok", con.execute("PRAGMA integrity_check").fetchone()[0])
            con.close()

    def test_cli_backs_up_before_migration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "v25.db"
            backup = Path(td) / "before.db"
            self._create_v25(db)
            run = subprocess.run([sys.executable, str(CLI), str(db), "--backup", str(backup)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertTrue(backup.exists())
            current = sqlite3.connect(db); previous = sqlite3.connect(backup)
            self.assertEqual("2.6.0", current.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0])
            self.assertEqual("2.5.0", previous.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0])
            current.close(); previous.close()


if __name__ == "__main__":
    unittest.main()
