from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.research_candidate_manifest import CandidateValidationError, import_candidate

SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"
CANDIDATE = ROOT / "artifacts" / "lp-mandate-speculative" / "2020-2025" / "cw-2022-domestic-re-debt-selected-managers.json"


class ResearchCandidateManifestTest(unittest.TestCase):
    def _db(self, path: Path) -> None:
        con = sqlite3.connect(path)
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(SCHEMA.read_text(encoding="utf-8"))
            con.executescript(SEED.read_text(encoding="utf-8"))
            con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES('org_cw','FINANCIAL_INSTITUTION','건설근로자공제회')")
            candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
            for index, name in enumerate(candidate["claim_payload"]["reported_selected_managers"]):
                con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES(?, 'FINANCIAL_INSTITUTION', ?)", (f'org_manager_{index}', name))
            con.execute("INSERT INTO events(event_id,canonical_title,primary_category_id,current_stage_code,event_date_start,date_precision,lifecycle_status,verification_level,overall_confidence,approved_at) VALUES('event_cw_2022','건설근로자공제회 2022 국내 부동산 대출형 블라인드 펀드','cat_invest','MANAGER_RFP_OPEN','2022-10-17','DAY','ACTIVE','V4',1.0,'2026-08-16T00:00:00Z')")
            con.execute("INSERT INTO lp_mandates(mandate_id,event_id,lp_organization_id,mandate_code,mandate_name,vintage_year,announced_at,mandate_status,mandate_scope,evidence_status,review_status) VALUES('mandate_cw_2022','event_cw_2022','org_cw','CW-2022-DOMESTIC-RE-DEBT','2022 국내 부동산 대출형 블라인드 펀드',2022,'2022-10-17','OPEN','DOMESTIC','MANUAL_VERIFIED','APPROVED')")
            con.execute("INSERT INTO lp_mandate_tracks(mandate_track_id,mandate_id,track_code,track_name,strategy_code,geography_code,evidence_status,review_status) VALUES('track_cw_2022','mandate_cw_2022','DOMESTIC_RE_DEBT','국내 부동산 대출형','REAL_ESTATE','DOMESTIC','MANUAL_VERIFIED','APPROVED')")
            con.commit()
        finally:
            con.close()

    def test_likely_candidate_is_relational_but_not_canonical_selection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "market.db"
            self._db(db)
            candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
            first = import_candidate(db, candidate)
            second = import_candidate(db, candidate)
            con = sqlite3.connect(db)
            self.assertGreater(first.inserted_rows, 0)
            self.assertEqual(0, second.inserted_rows)
            self.assertEqual(0, con.execute("SELECT COUNT(*) FROM lp_mandate_selections").fetchone()[0])
            self.assertEqual(2, con.execute("SELECT COUNT(*) FROM claims WHERE predicate_code='LP_MANDATE_REPORTED_SELECTED_MANAGER' AND verification_status='PENDING' AND certainty_code='REPORTED'").fetchone()[0])
            self.assertEqual(2, con.execute("SELECT COUNT(*) FROM claims WHERE predicate_code='LP_MANDATE_REPORTED_MANAGER_ALLOCATION' AND verification_status='PENDING' AND value_decimal_text IS NOT NULL").fetchone()[0])
            self.assertEqual(2, con.execute("SELECT COUNT(*) FROM v_lp_manager_best_available WHERE mandate_code='CW-2022-DOMESTIC-RE-DEBT' AND value_status='LIKELY_REPORTED_PENDING_PRIMARY' AND reported_allocation_decimal IS NOT NULL").fetchone()[0])
            self.assertEqual(1, con.execute("SELECT COUNT(*) FROM document_families WHERE family_type='SYNDICATED'").fetchone()[0])
            self.assertGreaterEqual(con.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0], 2)
            self.assertEqual([], con.execute("PRAGMA foreign_key_check").fetchall())
            con.close()

    def test_unknown_manager_does_not_create_canonical_identity_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "candidate.db"
            self._db(db)
            candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
            candidate["claim_payload"]["reported_selected_managers"].append("미승인 신규운용사")
            with self.assertRaises(CandidateValidationError):
                import_candidate(db, candidate)
            con = sqlite3.connect(db)
            self.assertEqual(0, con.execute("SELECT COUNT(*) FROM organizations WHERE canonical_name='미승인 신규운용사'").fetchone()[0])
            self.assertEqual(0, con.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0])
            con.close()


if __name__ == "__main__":
    unittest.main()
