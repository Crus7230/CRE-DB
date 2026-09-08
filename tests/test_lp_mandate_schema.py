from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"


class LpMandateSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(":memory:")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(SCHEMA.read_text(encoding="utf-8"))
        self.con.executescript(SEED.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.con.close()

    def _org(self, org_id: str, name: str, org_type: str = "COMPANY") -> None:
        self.con.execute(
            "INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES(?,?,?)",
            (org_id, org_type, name),
        )

    def _base(self) -> None:
        self._org("org_lp", "테스트LP", "GOVERNMENT")
        self._org("org_manager", "테스트자산운용")
        self._org("org_vehicle", "테스트블라인드펀드", "FUND")
        self.con.execute(
            """INSERT INTO lp_mandates(
                   mandate_id,lp_organization_id,mandate_code,mandate_name,vintage_year,
                   mandate_status,mandate_scope,evidence_status,review_status
               ) VALUES('mandate_1','org_lp','LP-2024-RE-01','2024 부동산 위탁운용사 선정',2024,
                        'SELECTED','DOMESTIC','MANUAL_VERIFIED','APPROVED')"""
        )
        self.con.execute(
            """INSERT INTO lp_mandate_tracks(
                   mandate_track_id,mandate_id,track_code,track_name,strategy_code
               ) VALUES('track_1','mandate_1','REAL_ESTATE','국내 부동산','REAL_ESTATE')"""
        )
        self.con.execute(
            """INSERT INTO lp_mandate_selections(
                   mandate_selection_id,mandate_track_id,manager_organization_id,
                   selection_status,selected_at,evidence_status,review_status
               ) VALUES('selection_1','track_1','org_manager','SELECTED','2024-06-01',
                        'MANUAL_VERIFIED','APPROVED')"""
        )
        self.con.execute(
            """INSERT INTO lp_mandate_selection_vehicles(
                   mandate_selection_id,vehicle_organization_id,vehicle_role
               ) VALUES('selection_1','org_vehicle','MANAGED_FUND')"""
        )
        self.con.execute(
            """INSERT INTO events(
                   event_id,canonical_title,primary_category_id,current_stage_code,
                   date_precision,lifecycle_status,verification_level
               ) VALUES('event_deal','테스트 자산 인수','cat_sale','CLOSED',
                        'DAY','COMPLETED','V2')"""
        )
        self.con.execute(
            """INSERT INTO sale_processes(
                   sale_process_id,event_id,process_code,sale_method,process_status,
                   evidence_status,review_status
               ) VALUES('sale_deal','event_deal','TEST-DEAL-1','COMPETITIVE_BID','CLOSED',
                        'MANUAL_VERIFIED','APPROVED')"""
        )

    def test_v25_lp_mandate_tables_exist(self) -> None:
        names = {
            row[0]
            for row in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        expected = {
            "lp_mandates",
            "lp_mandate_tracks",
            "lp_mandate_guidelines",
            "lp_mandate_selections",
            "lp_mandate_selection_members",
            "lp_mandate_selection_vehicles",
            "lp_mandate_amounts",
            "lp_mandate_deployments",
        }
        self.assertTrue(expected.issubset(names))
        version = self.con.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0]
        self.assertEqual("3.5.0", version)
        stages = {
            row[0]
            for row in self.con.execute(
                "SELECT stage_code FROM event_stages WHERE stage_code IN ('MANAGER_RFP_OPEN','MANAGER_SELECTED')"
            )
        }
        self.assertEqual({'MANAGER_RFP_OPEN', 'MANAGER_SELECTED'}, stages)

    def test_exact_lp_commitment_minus_exact_disclosed_deployment_is_untraced_not_dry_powder(self) -> None:
        self._base()
        self.con.execute(
            """INSERT INTO lp_mandate_amounts(
                   mandate_amount_id,mandate_selection_id,amount_basis,amount_decimal,
                   currency_code,comparator_code,amount_status,evidence_status,review_status
               ) VALUES('amt_source','selection_1','SELECTION_LP_COMMITMENT','100000000000',
                        'KRW','EXACT','COMMITTED','MANUAL_VERIFIED','APPROVED')"""
        )
        self.con.execute(
            """INSERT INTO lp_mandate_deployments(
                   mandate_deployment_id,mandate_selection_id,fund_vehicle_organization_id,
                   sale_process_id,deployment_basis,amount_decimal,currency_code,comparator_code,
                   deployment_status,evidence_status,review_status
               ) VALUES('deploy_1','selection_1','org_vehicle','sale_deal','LP_SOURCE_DEPLOYMENT',
                        '40000000000','KRW','EXACT','EXECUTED','MANUAL_VERIFIED','APPROVED')"""
        )
        row = self.con.execute(
            """SELECT source_amount_decimal,disclosed_deployed_decimal,
                      untraced_amount_decimal,balance_semantics
                 FROM v_lp_mandate_source_balance
                WHERE mandate_selection_id='selection_1' AND currency_code='KRW'"""
        ).fetchone()
        self.assertEqual(
            ("100000000000", "40000000000", "60000000000", "UNTRACED_COMMITTED_NOT_CONFIRMED_AVAILABLE"),
            row,
        )

    def test_target_fund_size_cannot_be_used_as_lp_source_balance(self) -> None:
        self._base()
        self.con.execute(
            """INSERT INTO lp_mandate_amounts(
                   mandate_amount_id,mandate_selection_id,amount_basis,amount_decimal,
                   currency_code,comparator_code,amount_status,evidence_status,review_status
               ) VALUES('amt_target','selection_1','TARGET_FUND_SIZE','300000000000',
                        'KRW','EXACT','ANNOUNCED','MANUAL_VERIFIED','APPROVED')"""
        )
        count = self.con.execute(
            "SELECT COUNT(*) FROM v_lp_mandate_source_balance WHERE mandate_selection_id='selection_1'"
        ).fetchone()[0]
        self.assertEqual(0, count)

    def test_guideline_preserves_return_basis_and_raw_wording(self) -> None:
        self._base()
        self.con.execute(
            """INSERT INTO lp_mandate_guidelines(
                   mandate_guideline_id,mandate_track_id,term_type,requirement_level,
                   raw_text,value_kind,value_decimal_text,unit_code,return_basis,
                   evidence_status,review_status
               ) VALUES('guide_1','track_1','TARGET_RETURN','MINIMUM',
                        '순IRR 8% 이상','PERCENT','8','PERCENT','NET_IRR',
                        'MANUAL_VERIFIED','APPROVED')"""
        )
        row = self.con.execute(
            "SELECT raw_text,value_decimal_text,return_basis FROM lp_mandate_guidelines"
        ).fetchone()
        self.assertEqual(("순IRR 8% 이상", "8", "NET_IRR"), row)
        self.con.execute(
            """INSERT INTO lp_mandate_guidelines(
                   mandate_guideline_id,mandate_track_id,term_type,requirement_level,
                   raw_text,value_kind,text_value,evidence_status,review_status
               ) VALUES('guide_risk','track_1','RISK_PROFILE','REQUIRED',
                        '코어·코어플러스','TEXT','CORE_CORE_PLUS',
                        'MANUAL_VERIFIED','APPROVED')"""
        )
        self.assertEqual(
            "CORE_CORE_PLUS",
            self.con.execute(
                "SELECT text_value FROM lp_mandate_guidelines WHERE mandate_guideline_id='guide_risk'"
            ).fetchone()[0],
        )

    def test_amount_target_is_exactly_one_scope(self) -> None:
        self._base()
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                """INSERT INTO lp_mandate_amounts(
                       mandate_amount_id,mandate_id,mandate_track_id,amount_basis,
                       amount_decimal,currency_code,comparator_code,amount_status
                   ) VALUES('bad','mandate_1','track_1','PROGRAM_TOTAL','1','KRW','EXACT','ANNOUNCED')"""
            )


if __name__ == "__main__":
    unittest.main()
