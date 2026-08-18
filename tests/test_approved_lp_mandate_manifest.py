from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.approved_lp_mandate_manifest import (  # noqa: E402
    ManifestValidationError,
    import_manifest,
)
SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"


def fixture() -> dict:
    return {
        "manifest_version": "1.0",
        "manifest_id": "approved-lp-mandate-test-2024",
        "status": "APPROVED",
        "review": {
            "reviewed_by": "qa-reviewer",
            "reviewed_at": "2026-08-16T00:00:00Z",
            "approved_by": "qa-approver",
            "approved_at": "2026-08-16T00:01:00Z",
        },
        "sources": [
            {
                "id": "src_lp_test_official",
                "url": "https://example.go.kr/official/manager-rfp-2024",
                "publisher": "테스트LP",
                "document_type": "NOTICE",
                "title": "2024 국내 부동산 위탁운용사 선정 공고",
                "published_at": "2024-04-01",
                "accessed_at": "2026-08-16T00:00:00Z",
                "rights_status": "EXCERPT_ALLOWED",
                "exact_text": "국내 부동산 부문 총 2,000억원, 2개 운용사를 선정하며 운용사별 1,000억원을 출자한다. 목표 순IRR 8% 이상. 테스트자산운용을 선정하였다. 테스트부동산펀드는 가상 거래에 LP 재원 400억원을 집행하였다.",
            }
        ],
        "organizations": [
            {"id": "org_lp_test", "organization_type": "GOVERNMENT", "canonical_name": "테스트LP"},
            {"id": "org_manager_test", "organization_type": "COMPANY", "canonical_name": "테스트자산운용"},
        ],
        "event": {
            "id": "event_lp_test_2024",
            "canonical_title": "테스트LP 2024 국내 부동산 위탁운용사 선정",
            "current_stage_code": "MANAGER_SELECTED",
            "event_date_start": "2024-04-01",
            "date_precision": "DAY",
            "lifecycle_status": "COMPLETED",
            "evidence": {"source_ids": ["src_lp_test_official"]},
        },
        "mandate": {
            "id": "mandate_lp_test_2024",
            "lp_organization_id": "org_lp_test",
            "mandate_code": "TESTLP-2024-DOMESTIC-RE",
            "mandate_name": "2024 국내 부동산 위탁운용사 선정",
            "vintage_year": 2024,
            "announced_at": "2024-04-01",
            "application_deadline": "2024-04-30",
            "selected_at": "2024-06-01",
            "mandate_status": "SELECTED",
            "mandate_scope": "DOMESTIC",
            "evidence": {"source_ids": ["src_lp_test_official"]},
        },
        "tracks": [
            {
                "id": "track_lp_test_re",
                "track_code": "DOMESTIC_REAL_ESTATE",
                "track_name": "국내 부동산",
                "strategy_code": "REAL_ESTATE",
                "geography_code": "DOMESTIC",
                "target_manager_count": 2,
                "evidence": {"source_ids": ["src_lp_test_official"]},
            }
        ],
        "guidelines": [
            {
                "id": "guide_lp_test_return",
                "track_id": "track_lp_test_re",
                "term_type": "TARGET_RETURN",
                "requirement_level": "MINIMUM",
                "raw_text": "목표 순IRR 8% 이상",
                "value_kind": "PERCENT",
                "value_decimal_text": "8",
                "unit_code": "PERCENT",
                "comparator_code": "AT_LEAST",
                "return_basis": "NET_IRR",
                "evidence": {"source_ids": ["src_lp_test_official"]},
            },
            {
                "id": "guide_lp_test_sector",
                "track_id": "track_lp_test_re",
                "term_type": "SECTOR",
                "requirement_level": "REQUIRED",
                "raw_text": "국내 부동산",
                "value_kind": "TEXT",
                "text_value": "국내 부동산",
                "evidence": {"source_ids": ["src_lp_test_official"]},
            },
        ],
        "selections": [
            {
                "id": "selection_lp_test_manager",
                "track_id": "track_lp_test_re",
                "manager_organization_id": "org_manager_test",
                "selection_status": "SELECTED",
                "selected_at": "2024-06-01",
                "evidence": {"source_ids": ["src_lp_test_official"]},
            }
        ],
        "selection_members": [],
        "selection_vehicles": [],
        "amounts": [
            {
                "id": "amount_lp_test_program",
                "scope_type": "MANDATE",
                "scope_id": "mandate_lp_test_2024",
                "amount_basis": "PROGRAM_TOTAL",
                "amount": {"kind": "EXACT", "decimal": "200000000000", "currency": "KRW", "raw_value": "총 2,000억원"},
                "amount_status": "ANNOUNCED",
                "evidence": {"source_ids": ["src_lp_test_official"]},
            },
            {
                "id": "amount_lp_test_selection",
                "scope_type": "SELECTION",
                "scope_id": "selection_lp_test_manager",
                "amount_basis": "ALLOCATION_PER_MANAGER",
                "amount": {"kind": "EXACT", "decimal": "100000000000", "currency": "KRW", "raw_value": "운용사별 1,000억원"},
                "amount_status": "AWARDED",
                "evidence": {"source_ids": ["src_lp_test_official"]},
            },
        ],
        "deployments": [],
    }


class ApprovedLpMandateManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.db"
        con = sqlite3.connect(self.db)
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.executescript(SEED.read_text(encoding="utf-8"))
        con.execute(
            """INSERT INTO events(
                   event_id,canonical_title,primary_category_id,current_stage_code,
                   event_date_start,event_date_end,date_precision,lifecycle_status,
                   verification_level,overall_confidence,approved_at
               ) VALUES('event_lp_test_deal','가상 부동산 거래','cat_sale','CLOSED',
                        '2024-12-31','2024-12-31','DAY','COMPLETED','V3',0.99,
                        '2025-01-01T00:00:00Z')"""
        )
        con.execute(
            "INSERT INTO sale_processes(sale_process_id,event_id,process_code,sale_method,process_status) VALUES('sp_lp_test_deal','event_lp_test_deal','LP-TEST-DEAL','COMPETITIVE_BID','CLOSED')"
        )
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_approved_manifest_is_idempotent_and_preserves_typed_terms(self) -> None:
        first = import_manifest(self.db, fixture())
        second = import_manifest(self.db, fixture())
        self.assertGreater(first.inserted_rows, 0)
        self.assertEqual(0, second.inserted_rows)
        con = sqlite3.connect(self.db)
        self.assertEqual(1, con.execute("SELECT COUNT(*) FROM lp_mandates").fetchone()[0])
        self.assertEqual(1, con.execute("SELECT COUNT(*) FROM lp_mandate_selections").fetchone()[0])
        self.assertEqual(
            ("8", "NET_IRR"),
            con.execute(
                "SELECT value_decimal_text,return_basis FROM lp_mandate_guidelines WHERE term_type='TARGET_RETURN'"
            ).fetchone(),
        )
        self.assertEqual(
            ("운용사별 1,000억원", "100000000000"),
            con.execute(
                """SELECT c.raw_value,c.value_decimal_text
                     FROM lp_mandate_amounts a JOIN claims c ON c.claim_id=a.source_claim_id
                    WHERE a.amount_basis='ALLOCATION_PER_MANAGER'"""
            ).fetchone(),
        )
        self.assertEqual(
            ("100000000000", "0", "100000000000", "UNTRACED_AWARDED_NOT_CONFIRMED_COMMITTED_OR_AVAILABLE"),
            con.execute("SELECT source_amount_decimal,disclosed_deployed_decimal,untraced_amount_decimal,balance_semantics FROM v_lp_mandate_source_balance").fetchone(),
        )
        con.close()

    def test_dry_run_rolls_back_all_rows(self) -> None:
        result = import_manifest(self.db, fixture(), dry_run=True)
        self.assertTrue(result.dry_run)
        con = sqlite3.connect(self.db)
        self.assertEqual(0, con.execute("SELECT COUNT(*) FROM lp_mandates").fetchone()[0])
        self.assertEqual(0, con.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0])
        con.close()

    def test_nonapproved_or_ambiguous_amount_is_rejected(self) -> None:
        bad = fixture()
        bad["status"] = "REVIEW_ONLY"
        with self.assertRaises(ManifestValidationError):
            import_manifest(self.db, bad)
        bad = fixture()
        bad["amounts"][0]["amount"]["decimal"] = "약 2천억원"
        with self.assertRaises(ManifestValidationError):
            import_manifest(self.db, bad)

    def test_news_only_selected_manager_is_rejected(self) -> None:
        bad = fixture()
        bad["sources"][0]["document_type"] = "ARTICLE"
        with self.assertRaisesRegex(
            ManifestValidationError,
            "official or party-primary source",
        ):
            import_manifest(self.db, bad)

    def test_explicit_vehicle_and_deal_deployment_updates_only_untraced_projection(self) -> None:
        manifest = fixture()
        manifest["organizations"].append({
            "id": "org_lp_test_vehicle", "organization_type": "FUND",
            "canonical_name": "테스트부동산펀드",
        })
        manifest["selection_vehicles"] = [{
            "selection_id": "selection_lp_test_manager",
            "vehicle_organization_id": "org_lp_test_vehicle",
            "vehicle_role": "MANAGED_FUND",
            "evidence": {"source_ids": ["src_lp_test_official"]},
        }]
        manifest["amounts"][1]["amount_basis"] = "SELECTION_LP_COMMITMENT"
        manifest["amounts"][1]["amount_status"] = "COMMITTED"
        manifest["deployments"] = [{
            "id": "deployment_lp_test_deal",
            "selection_id": "selection_lp_test_manager",
            "fund_vehicle_organization_id": "org_lp_test_vehicle",
            "sale_process_id": "sp_lp_test_deal",
            "deployment_basis": "LP_SOURCE_DEPLOYMENT",
            "amount": {
                "kind": "EXACT", "decimal": "40000000000", "currency": "KRW",
                "raw_value": "LP 재원 400억원",
            },
            "deployment_status": "EXECUTED",
            "evidence": {"source_ids": ["src_lp_test_official"]},
        }]

        result = import_manifest(self.db, manifest)
        self.assertGreater(result.inserted_rows, 0)
        con = sqlite3.connect(self.db)
        self.assertEqual(
            ("100000000000", "40000000000", "60000000000", "UNTRACED_COMMITTED_NOT_CONFIRMED_AVAILABLE"),
            con.execute("SELECT source_amount_decimal,disclosed_deployed_decimal,untraced_amount_decimal,balance_semantics FROM v_lp_mandate_source_balance").fetchone(),
        )
        self.assertEqual(
            ("테스트LP", "테스트자산운용", "테스트부동산펀드", "sp_lp_test_deal", "40000000000"),
            con.execute(
                "SELECT lp_name,manager_name,fund_vehicle_name,sale_process_id,amount_decimal FROM v_lp_mandate_deal_sources"
            ).fetchone(),
        )
        con.close()

    def test_conflicting_stable_id_rolls_back(self) -> None:
        import_manifest(self.db, fixture())
        conflict = copy.deepcopy(fixture())
        conflict["mandate"]["mandate_name"] = "충돌하는 이름"
        with self.assertRaises(ManifestValidationError):
            import_manifest(self.db, conflict)
        con = sqlite3.connect(self.db)
        self.assertEqual(
            "2024 국내 부동산 위탁운용사 선정",
            con.execute("SELECT mandate_name FROM lp_mandates").fetchone()[0],
        )
        con.close()


if __name__ == "__main__":
    unittest.main()
