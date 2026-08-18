from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.approved_sale_manifest import (  # noqa: E402
    ManifestValidationError,
    import_manifest,
)

SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"
FIXTURE = ROOT / "fixtures" / "approved-sale-processes" / "hyundai-yeonji-2025.json"
CHEONGNA_FIXTURE = ROOT / "fixtures" / "approved-sale-processes" / "cheongna-logistics-2025.json"


def make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    con.close()


class ApprovedSaleManifestImporterTest(unittest.TestCase):
    def test_manifest_can_link_two_existing_sale_process_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            make_db(db)
            first = json.loads(FIXTURE.read_text(encoding="utf-8"))
            second = json.loads(CHEONGNA_FIXTURE.read_text(encoding="utf-8"))
            second["process_relations"] = [{
                "id": "rel_test_attempts",
                "from_sale_process_id": first["process"]["id"],
                "to_sale_process_id": second["process"]["id"],
                "relation_type": "OTHER",
                "evidence": {"source_ids": [second["sources"][0]["id"]]},
                "metadata": {"test_only": True},
            }]
            import_manifest(db, first)
            import_manifest(db, second)
            repeat = import_manifest(db, second)
            self.assertEqual(0, repeat.inserted_rows)
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT from_sale_process_id,to_sale_process_id,relation_type FROM sale_process_relations"
            ).fetchone()
            con.close()
            self.assertEqual((first["process"]["id"], second["process"]["id"], "OTHER"), row)

    def test_two_manifests_coexist_and_remain_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            make_db(db)
            self.assertGreater(import_manifest(db, FIXTURE).inserted_rows, 0)
            self.assertGreater(import_manifest(db, CHEONGNA_FIXTURE).inserted_rows, 0)
            self.assertEqual(0, import_manifest(db, FIXTURE).inserted_rows)
            self.assertEqual(0, import_manifest(db, CHEONGNA_FIXTURE).inserted_rows)
            con = sqlite3.connect(db)
            self.assertEqual(1, con.execute(
                "SELECT count(*) FROM organizations WHERE organization_id='org_nh_investment_securities'"
            ).fetchone()[0])
            self.assertEqual(2, con.execute("SELECT count(*) FROM sale_processes").fetchone()[0])
            self.assertEqual([], con.execute("PRAGMA foreign_key_check").fetchall())
            con.close()

    def test_approved_fixture_import_is_idempotent_and_preserves_amount_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            make_db(db)

            first = import_manifest(db, FIXTURE)
            second = import_manifest(db, FIXTURE)

            self.assertGreater(first.inserted_rows, 0)
            self.assertEqual(0, second.inserted_rows)
            con = sqlite3.connect(db)
            self.assertEqual(1, con.execute("SELECT count(*) FROM sale_processes").fetchone()[0])
            self.assertEqual(1, con.execute("SELECT count(*) FROM assets").fetchone()[0])
            self.assertEqual(5, con.execute("SELECT count(*) FROM source_documents").fetchone()[0])
            self.assertEqual(2, con.execute("SELECT count(*) FROM bidder_participation_members").fetchone()[0])
            self.assertEqual(3, con.execute("SELECT count(*) FROM bid_funding_components").fetchone()[0])
            amount = con.execute(
                """SELECT s.bid_amount_decimal,s.comparator_code,s.amount_precision,
                          s.evidence_status,s.review_status,c.raw_value,c.comparator_code
                     FROM bid_submissions s JOIN claims c ON c.claim_id=s.source_claim_id"""
            ).fetchone()
            self.assertEqual(
                ("450000000000", "ABOUT", "ROUNDED", "SOURCE_CLAIM", "APPROVED", "약 4,500억원", "ABOUT"),
                amount,
            )
            self.assertEqual([], con.execute("PRAGMA foreign_key_check").fetchall())
            con.close()

    def test_cheongna_calibration_imports_closed_milestone_without_inventing_exact_price(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            make_db(db)
            result = import_manifest(db, CHEONGNA_FIXTURE)
            self.assertGreater(result.inserted_rows, 0)
            con = sqlite3.connect(db)
            row = con.execute(
                """SELECT s.bid_amount_decimal,s.comparator_code,s.amount_precision,m.effective_date
                     FROM bid_submissions s
                     JOIN bidder_participations p ON p.participation_id=s.participation_id
                     JOIN bid_rounds r ON r.bid_round_id=p.bid_round_id
                     JOIN transaction_milestones m ON m.sale_process_id=r.sale_process_id
                    WHERE s.bid_submission_id='submission_cl_kkr_create'"""
            ).fetchone()
            self.assertEqual(("1000000000000", "ABOUT", "ROUNDED", "2025-12-30"), row)
            self.assertEqual(3, con.execute("SELECT count(*) FROM bidder_participation_members").fetchone()[0])
            self.assertEqual(3, con.execute("SELECT count(*) FROM bid_funding_components").fetchone()[0])
            subset = con.execute(
                "SELECT metadata_json FROM bid_funding_components WHERE funding_component_id='fund_cl_japan_subset'"
            ).fetchone()[0]
            self.assertIn('DO_NOT_ADD_TO_PARENT', subset)
            self.assertEqual([], con.execute("PRAGMA foreign_key_check").fetchall())
            con.close()

    def test_dry_run_validates_and_rolls_back_every_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            make_db(db)
            result = import_manifest(db, FIXTURE, dry_run=True)
            self.assertTrue(result.dry_run)
            self.assertGreater(result.inserted_rows, 0)
            con = sqlite3.connect(db)
            self.assertEqual(0, con.execute("SELECT count(*) FROM sale_processes").fetchone()[0])
            self.assertEqual(0, con.execute("SELECT count(*) FROM source_documents").fetchone()[0])
            con.close()

    def test_ambiguous_prose_amount_is_rejected_without_partial_writes(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["submissions"][0]["amount"] = {
            "kind": "APPROX",
            "raw_value": "4,000억원 이상 제시 보도; 최종 약 4,500억원",
            "currency": "KRW",
        }
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            make_db(db)
            with self.assertRaisesRegex(ManifestValidationError, "decimal is required"):
                import_manifest(db, manifest)
            con = sqlite3.connect(db)
            for table in ("events", "assets", "organizations", "source_documents", "sale_processes"):
                self.assertEqual(0, con.execute(f"SELECT count(*) FROM {table}").fetchone()[0], table)
            con.close()

    def test_non_approved_manifest_is_rejected(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["status"] = "DRAFT"
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            make_db(db)
            with self.assertRaisesRegex(ManifestValidationError, "status must be APPROVED"):
                import_manifest(db, manifest)

    def test_database_constraint_error_rolls_back_provenance_and_canonical_rows(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["asset"]["asset_class_id"] = "missing_asset_class"
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            make_db(db)
            with self.assertRaises(sqlite3.IntegrityError):
                import_manifest(db, manifest)
            con = sqlite3.connect(db)
            self.assertEqual(0, con.execute("SELECT count(*) FROM source_documents").fetchone()[0])
            self.assertEqual(0, con.execute("SELECT count(*) FROM assets").fetchone()[0])
            self.assertEqual(0, con.execute("SELECT count(*) FROM events").fetchone()[0])
            con.close()


if __name__ == "__main__":
    unittest.main()
