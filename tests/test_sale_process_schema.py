from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"


class SaleProcessSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(":memory:")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(SCHEMA.read_text(encoding="utf-8"))
        self.con.executescript(SEED.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.con.close()

    def test_sale_process_attempt_relations_are_relational_and_unique(self) -> None:
        con = self.con
        for event_id, process_id, code in [
            ("evt_a", "sp_a", "ASSET-2020-A1"),
            ("evt_b", "sp_b", "ASSET-2021-A2"),
        ]:
            con.execute(
                """INSERT INTO events(event_id,canonical_title,primary_category_id,
                           current_stage_code,lifecycle_status,verification_level)
                   VALUES (?,?,'cat_sale','SALE_FAILED','COMPLETED','V2')""",
                (event_id, code),
            )
            con.execute(
                """INSERT INTO sale_processes(
                       sale_process_id,event_id,process_code,sale_method,process_status,
                       evidence_status,review_status)
                   VALUES (?,?,?,'COMPETITIVE_BID','FAILED','MANUAL_VERIFIED','APPROVED')""",
                (process_id, event_id, code),
            )
        con.execute(
            """INSERT INTO sale_process_relations(
                   sale_process_relation_id,from_sale_process_id,to_sale_process_id,
                   relation_type,evidence_status,review_status)
               VALUES ('rel_1','sp_a','sp_b','RELAUNCHED_AS',
                       'MANUAL_VERIFIED','APPROVED')"""
        )
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(
                """INSERT INTO sale_process_relations(
                       sale_process_relation_id,from_sale_process_id,to_sale_process_id,
                       relation_type,evidence_status,review_status)
                   VALUES ('rel_2','sp_a','sp_b','RELAUNCHED_AS',
                           'MANUAL_VERIFIED','APPROVED')"""
            )
        row = con.execute(
            """SELECT from_process_code,to_process_code,relation_type
                 FROM v_sale_process_relations WHERE sale_process_relation_id='rel_1'"""
        ).fetchone()
        self.assertEqual(("ASSET-2020-A1", "ASSET-2021-A2", "RELAUNCHED_AS"), row)

    def test_v25_tables_and_stages_exist(self) -> None:
        expected = {
            "sale_processes",
            "sale_process_relations",
            "sale_process_roles",
            "bid_rounds",
            "bidder_participations",
            "bidder_participation_members",
            "bid_submissions",
            "bid_funding_components",
            "bid_decisions",
            "transaction_milestones",
        }
        actual = {
            row[0]
            for row in self.con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue(expected <= actual)
        stages = {
            row[0]
            for row in self.con.execute(
                "SELECT stage_code FROM event_stages WHERE event_category_id='cat_sale'"
            )
        }
        self.assertTrue(
            {
                "SHORTLISTED",
                "MOU_SIGNED",
                "DUE_DILIGENCE",
                "SPA_SIGNED",
                "CONDITIONS_PENDING",
                "SALE_FAILED",
                "REBID",
            }
            <= stages
        )
        version = self.con.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0]
        self.assertEqual("3.5.0", version)

    def test_competition_funding_preferred_switch_and_closing(self) -> None:
        con = self.con
        for oid, name, kind in [
            ("seller", "매도법인", "COMPANY"),
            ("advisor", "매각자문사", "COMPANY"),
            ("bidder_a", "A자산운용", "COMPANY"),
            ("bidder_b", "B투자자", "COMPANY"),
            ("fund_a", "A블라인드펀드", "FUND"),
            ("spc_a", "A매수SPC", "SPC"),
            ("lender_a", "A인수금융대주단", "FINANCIAL_INSTITUTION"),
        ]:
            con.execute(
                "INSERT INTO organizations(organization_id, canonical_name, organization_type) VALUES (?,?,?)",
                (oid, name, kind),
            )
        con.execute(
            """INSERT INTO events(event_id, canonical_title, primary_category_id,
                       current_stage_code, lifecycle_status, verification_level)
               VALUES ('sale_evt','테스트 자산 매각','cat_sale','CLOSED','COMPLETED','V2')"""
        )
        con.execute(
            """INSERT INTO sale_processes(
                   sale_process_id,event_id,process_code,sale_method,process_status,
                   launched_at,closed_at,evidence_status,review_status)
               VALUES ('sp1','sale_evt','TEST-SALE-2025-01','COMPETITIVE_BID','CLOSED',
                       '2025-01-01','2025-12-20','MANUAL_VERIFIED','APPROVED')"""
        )
        con.execute(
            """INSERT INTO sale_process_roles(
                   process_role_id,sale_process_id,organization_id,role_code,
                   valid_from,evidence_status,review_status)
               VALUES ('role_seller','sp1','seller','SELLER','2025-01-01','MANUAL_VERIFIED','APPROVED'),
                      ('role_advisor','sp1','advisor','SELL_SIDE_ADVISOR','2025-01-01','MANUAL_VERIFIED','APPROVED')"""
        )
        con.execute(
            """INSERT INTO bid_rounds(
                   bid_round_id,sale_process_id,round_no,round_code,round_type,
                   deadline_at,round_status,evidence_status,review_status)
               VALUES ('r1','sp1',1,'PRELIMINARY','PRELIMINARY','2025-03-01','COMPLETED','MANUAL_VERIFIED','APPROVED'),
                      ('r2','sp1',2,'FINAL','FINAL','2025-05-01','COMPLETED','MANUAL_VERIFIED','APPROVED')"""
        )
        for pid, bidder in [("pa","bidder_a"), ("pb","bidder_b")]:
            con.execute(
                """INSERT INTO bidder_participations(
                       participation_id,bid_round_id,bidder_organization_id,participation_status,
                       evidence_status,review_status)
                   VALUES (?,?,?,'FINAL_BID_SUBMITTED','MANUAL_VERIFIED','APPROVED')""",
                (pid, "r2", bidder),
            )
        for mid, pid, org, role in [
            ("m1", "pa", "bidder_a", "LEAD_BIDDER"),
            ("m2", "pa", "fund_a", "MANAGED_FUND"),
            ("m3", "pa", "spc_a", "ACQUISITION_VEHICLE"),
        ]:
            con.execute(
                """INSERT INTO bidder_participation_members(
                       participation_member_id,participation_id,organization_id,member_role,
                       evidence_status,review_status) VALUES (?,?,?,?, 'MANUAL_VERIFIED','APPROVED')""",
                (mid, pid, org, role),
            )
        con.execute(
            """INSERT INTO bid_submissions(
                   bid_submission_id,participation_id,submission_no,bid_amount_decimal,currency_code,
                   comparator_code,amount_precision,price_basis,reported_rank,rank_as_of,
                   evidence_status,review_status)
               VALUES ('sa','pa',1,'100000000000','KRW','EXACT','EXACT','TOTAL_CONSIDERATION',2,
                       '2025-05-01','MANUAL_VERIFIED','APPROVED'),
                      ('sb','pb',1,'105000000000','KRW','EXACT','EXACT','TOTAL_CONSIDERATION',1,
                       '2025-05-01','MANUAL_VERIFIED','APPROVED')"""
        )
        for fid, ftype, provider, vehicle, amount in [
            ("f1", "BLIND_FUND_EQUITY", "fund_a", "spc_a", "40000000000"),
            ("f2", "ACQUISITION_DEBT", "lender_a", "spc_a", "60000000000"),
        ]:
            con.execute(
                """INSERT INTO bid_funding_components(
                       funding_component_id,bid_submission_id,funding_type,provider_organization_id,
                       recipient_vehicle_id,amount_decimal,currency_code,commitment_status,
                       evidence_status,review_status)
                   VALUES (?,?,?,?,?,?,'KRW','COMMITTED','MANUAL_VERIFIED','APPROVED')""",
                (fid, "sa", ftype, provider, vehicle, amount),
            )
        con.execute(
            """INSERT INTO bid_decisions(
                   bid_decision_id,sale_process_id,bid_round_id,participation_id,decision_type,
                   decision_date,decision_status,source_reason,evidence_status,review_status)
               VALUES ('pref_a','sp1','r2','pa','PREFERRED','2025-05-20','SUPERSEDED',
                       '가격 외 조건 포함','MANUAL_VERIFIED','APPROVED')"""
        )
        con.execute(
            """INSERT INTO transaction_milestones(
                   milestone_id,sale_process_id,milestone_code,milestone_status,effective_date,
                   source_note,evidence_status,review_status)
               VALUES ('fail_a','sp1','NEGOTIATION_FAILED','CONFIRMED','2025-07-01',
                       '최초 우협 협상 결렬','MANUAL_VERIFIED','APPROVED')"""
        )
        con.execute(
            """INSERT INTO bid_decisions(
                   bid_decision_id,sale_process_id,bid_round_id,participation_id,decision_type,
                   decision_date,decision_status,source_reason,supersedes_decision_id,
                   evidence_status,review_status)
               VALUES ('pref_b','sp1','r2','pb','PREFERRED','2025-07-02','CURRENT',
                       '차순위자 전환','pref_a','MANUAL_VERIFIED','APPROVED')"""
        )
        con.execute(
            """INSERT INTO transaction_milestones(
                   milestone_id,sale_process_id,milestone_code,milestone_status,effective_date,
                   evidence_status,review_status)
               VALUES ('spa_b','sp1','SPA_SIGNED','CONFIRMED','2025-09-01','MANUAL_VERIFIED','APPROVED'),
                      ('closed_b','sp1','CLOSED','CONFIRMED','2025-12-20','MANUAL_VERIFIED','APPROVED')"""
        )
        con.commit()

        competition = con.execute(
            """SELECT bidder_name,bid_amount_decimal,reported_rank,is_current_preferred
               FROM v_bid_competition WHERE sale_process_id='sp1'
               ORDER BY CAST(bid_amount_decimal AS INTEGER) DESC"""
        ).fetchall()
        self.assertEqual("B투자자", competition[0][0])
        self.assertEqual(1, competition[0][2])
        self.assertEqual(1, competition[0][3])
        self.assertEqual("A자산운용", competition[1][0])
        self.assertEqual(2, competition[1][2])
        self.assertEqual(0, competition[1][3])
        current = con.execute(
            "SELECT current_preferred_bidder,current_milestone FROM v_sale_process_current WHERE sale_process_id='sp1'"
        ).fetchone()
        self.assertEqual(("B투자자", "CLOSED"), current)
        funding = con.execute(
            """SELECT funding_type,provider_name,amount_decimal
               FROM v_bid_funding WHERE bid_submission_id='sa' ORDER BY funding_type"""
        ).fetchall()
        self.assertEqual(2, len(funding))
        self.assertEqual({"A블라인드펀드", "A인수금융대주단"}, {row[1] for row in funding})


if __name__ == "__main__":
    unittest.main()
