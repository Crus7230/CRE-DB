from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "v2" / "migrations" / "2.4.0_sale_process_relations.sql"


class Migrate24Test(unittest.TestCase):
    @staticmethod
    def make_v23(path: Path) -> None:
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY, schema_value TEXT NOT NULL) STRICT;
            INSERT INTO schema_meta VALUES ('schema_version','2.3.0');
            CREATE TABLE claims(claim_id TEXT PRIMARY KEY) STRICT;
            CREATE TABLE sale_processes(
                sale_process_id TEXT PRIMARY KEY,
                process_code TEXT NOT NULL UNIQUE
            ) STRICT;
            INSERT INTO sale_processes VALUES ('sp1','P1'),('sp2','P2');
        """)
        con.close()

    def test_cli_creates_v23_backup_before_applying_v24(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "market.db"
            backup = Path(td) / "pre-v24.db"
            self.make_v23(db)
            result = subprocess.run(
                [sys.executable, str(ROOT / "db" / "v2" / "migrate_2_4.py"), str(db), "--backup", str(backup)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            live = sqlite3.connect(db)
            old = sqlite3.connect(backup)
            self.assertEqual("2.4.0", live.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0])
            self.assertEqual("2.3.0", old.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0])
            self.assertEqual("ok", live.execute("PRAGMA integrity_check").fetchone()[0])
            live.close(); old.close()

    def test_migration_preserves_existing_processes_and_adds_relation_bridge(self) -> None:
        con = sqlite3.connect(":memory:")
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript("""
            CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY, schema_value TEXT NOT NULL) STRICT;
            INSERT INTO schema_meta VALUES ('schema_version','2.3.0');
            CREATE TABLE claims(claim_id TEXT PRIMARY KEY) STRICT;
            CREATE TABLE sale_processes(
                sale_process_id TEXT PRIMARY KEY,
                process_code TEXT NOT NULL UNIQUE
            ) STRICT;
            INSERT INTO sale_processes VALUES ('sp1','P1'),('sp2','P2');
        """)
        con.executescript(MIGRATION.read_text(encoding="utf-8"))
        self.assertEqual(
            "2.4.0",
            con.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0],
        )
        self.assertEqual(2, con.execute("SELECT count(*) FROM sale_processes").fetchone()[0])
        con.execute("""INSERT INTO sale_process_relations(
            sale_process_relation_id,from_sale_process_id,to_sale_process_id,relation_type,
            evidence_status,review_status) VALUES ('r','sp1','sp2','RELAUNCHED_AS','MANUAL_VERIFIED','APPROVED')""")
        self.assertEqual(
            ("P1", "P2"),
            con.execute("SELECT from_process_code,to_process_code FROM v_sale_process_relations").fetchone(),
        )
        con.close()


if __name__ == "__main__":
    unittest.main()
