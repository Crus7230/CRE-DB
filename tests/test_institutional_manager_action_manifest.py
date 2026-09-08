from __future__ import annotations

import copy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.institutional_manager_action_manifest import (
    ManifestValidationError,
    import_manifest,
)


SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"


class InstitutionalManagerActionManifestTest(unittest.TestCase):
    def _db(self, path: Path) -> None:
        con = sqlite3.connect(path)
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(SCHEMA.read_text(encoding="utf-8"))
            con.executescript(SEED.read_text(encoding="utf-8"))
            con.executemany(
                """INSERT INTO organizations(
                       organization_id,organization_type,canonical_name
                   ) VALUES(?,?,?)""",
                [
                    ("org_lp", "FINANCIAL_INSTITUTION", "테스트연기금"),
                    ("org_manager", "FINANCIAL_INSTITUTION", "테스트운용"),
                    ("org_vehicle", "FUND", "테스트블라인드펀드"),
                ],
            )
            con.execute(
                "INSERT INTO assets(asset_id,canonical_name) VALUES('asset_deal','테스트센터')"
            )
            con.execute(
                """INSERT INTO events(
                       event_id,canonical_title,primary_category_id,current_stage_code,
                       event_date_start,date_precision,lifecycle_status,
                       verification_level,overall_confidence,approved_at
                   ) VALUES(
                       'event_mandate','테스트연기금 국내 부동산 위탁운용사 모집',
                       'cat_invest','MANAGER_RFP_OPEN','2026-01-10','DAY','ACTIVE',
                       'V4',1.0,'2026-01-10T00:00:00Z'
                   )"""
            )
            con.execute(
                """INSERT INTO lp_mandates(
                       mandate_id,event_id,lp_organization_id,mandate_code,mandate_name,
                       vintage_year,announced_at,mandate_status,mandate_scope,
                       evidence_status,review_status
                   ) VALUES(
                       'mandate_test','event_mandate','org_lp','LP-2026-RE',
                       '2026 국내 부동산 위탁운용',2026,'2026-01-10','OPEN','DOMESTIC',
                       'MANUAL_VERIFIED','APPROVED'
                   )"""
            )
            con.execute(
                """INSERT INTO lp_mandate_tracks(
                       mandate_track_id,mandate_id,track_code,track_name,strategy_code,
                       geography_code,evidence_status,review_status
                   ) VALUES(
                       'track_test','mandate_test','DOMESTIC_RE','국내 부동산',
                       'REAL_ESTATE','DOMESTIC','MANUAL_VERIFIED','APPROVED'
                   )"""
            )
            con.commit()
        finally:
            con.close()

    def _manifest(self, action_type: str = "BID") -> dict:
        if action_type == "BID":
            action = "본입찰에 참여했다"
            follow_up_action = "FINAL_BID_SUBMITTED"
            funding_basis = "LP_EQUITY"
        else:
            action = "인수를 집행했다"
            follow_up_action = "EXECUTED"
            funding_basis = "LP_SOURCE_DEPLOYMENT"
        exact_text = (
            f"테스트운용은 2026년 6월 20일 테스트연기금의 "
            f"2026 국내 부동산 위탁운용 국내 부동산 트랙의 "
            f"테스트블라인드펀드 자금으로 테스트센터 {action}."
        )
        return {
            "manifest_version": "1.0",
            "manifest_id": f"test-{action_type.lower()}-20260620",
            "action_type": action_type,
            "mandate_code": "LP-2026-RE",
            "track_code": "DOMESTIC_RE",
            "lp_organization_id": "org_lp",
            "manager_organization_id": "org_manager",
            "follow_up_action": follow_up_action,
            "funding_basis": funding_basis,
            "action_date": "2026-06-20",
            "inference_rule_version": "lp-manager-action-v1",
            "linked_vehicle_organization_id": "org_vehicle",
            "linked_deal": {"kind": "ASSET", "id": "asset_deal"},
            "confidence": 0.82,
            "observed_at": "2026-06-21T09:00:00Z",
            "sources": [
                {
                    "id": "source-1",
                    "url": f"https://example.test/{action_type.lower()}",
                    "publisher": "테스트뉴스",
                    "document_type": "ARTICLE",
                    "source_kind": "MEDIA",
                    "published_at": "2026-06-21",
                    "accessed_at": "2026-06-21T09:00:00Z",
                    "rights_status": "EXCERPT_ALLOWED",
                    "content_scope": "FULL_TEXT",
                    "source_family": f"family-{action_type.lower()}-original",
                    "family_relation": "ORIGINAL",
                    "exact_text": exact_text,
                }
            ],
            "evidence": [
                {
                    "source_id": "source-1",
                    "direct_action_text": action,
                    "lp_text": "테스트연기금",
                    "manager_text": "테스트운용",
                    "mandate_text": "2026 국내 부동산 위탁운용",
                    "track_text": "국내 부동산",
                    "vehicle_or_deal_text": "테스트블라인드펀드",
                    "date_text": "2026년 6월 20일",
                    "funding_basis_text": "테스트블라인드펀드 자금",
                }
            ],
        }

    @staticmethod
    def _canonical_counts(con: sqlite3.Connection) -> dict[str, int]:
        tables = (
            "lp_mandate_selections",
            "lp_mandate_selection_vehicles",
            "lp_mandate_deployments",
            "bid_rounds",
            "bid_submissions",
            "bid_funding_components",
            "bid_decisions",
        )
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }

    def test_bid_is_idempotent_and_never_becomes_selection_inference(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("BID")
            first = import_manifest(db, manifest)
            second = import_manifest(db, manifest)
            self.assertGreater(first.inserted_rows, 0)
            self.assertEqual(0, second.inserted_rows)
            self.assertEqual(first.claim_id, second.claim_id)

            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    1,
                    con.execute(
                        """SELECT COUNT(*) FROM claims
                            WHERE predicate_code='LP_MANDATE_MANAGER_BID_PARTICIPANT'
                              AND certainty_code='REPORTED'
                              AND review_status='UNREVIEWED'
                              AND verification_status='PENDING'"""
                    ).fetchone()[0],
                )
                self.assertEqual(
                    0,
                    con.execute(
                        """SELECT COUNT(*) FROM claims
                            WHERE predicate_code='LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT'"""
                    ).fetchone()[0],
                )
                self.assertEqual(set(self._canonical_counts(con).values()), {0})
                roles = {
                    row[0]
                    for row in con.execute(
                        "SELECT role_code FROM claim_arguments WHERE claim_id=?",
                        (first.claim_id,),
                    )
                }
                self.assertTrue(
                    {
                        "MANDATE_CODE",
                        "MANDATE_TRACK",
                        "FOLLOW_UP_ACTION",
                        "FUNDING_BASIS",
                        "LINKED_VEHICLE",
                        "LINKED_DEAL",
                        "INFERENCE_RULE_VERSION",
                    }.issubset(roles),
                )
                self.assertGreaterEqual(
                    con.execute(
                        "SELECT COUNT(*) FROM claim_evidence WHERE claim_id=?",
                        (first.claim_id,),
                    ).fetchone()[0],
                    8,
                )
                self.assertEqual(
                    "ORGANIZATION",
                    con.execute(
                        """SELECT m.mention_type
                             FROM claim_evidence ce
                             JOIN mentions m ON m.mention_id=ce.mention_id
                            WHERE ce.claim_id=? AND m.surface_text='테스트블라인드펀드'""",
                        (first.claim_id,),
                    ).fetchone()[0],
                )
                self.assertEqual([], con.execute("PRAGMA foreign_key_check").fetchall())
            finally:
                con.close()

    def test_secondary_deployment_defaults_to_unreviewed_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            result = import_manifest(db, self._manifest("DEPLOYMENT"))
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    """SELECT certainty_code,review_status,verification_status
                         FROM claims WHERE claim_id=?""",
                    (result.claim_id,),
                ).fetchone()
                self.assertEqual(("INFERRED", "UNREVIEWED", "PENDING"), row)
                self.assertEqual(set(self._canonical_counts(con).values()), {0})
            finally:
                con.close()

    def test_accepted_bid_is_verified_but_never_selection_inference(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("BID")
            manifest["review"] = {
                "reviewer": "reviewer@igisam.com",
                "approved_at": "2026-06-22T10:00:00Z",
                "review_decision": "ACCEPTED",
            }
            result = import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    (
                        "LP_MANDATE_MANAGER_BID_PARTICIPANT",
                        "REPORTED",
                        "ACCEPTED",
                        "VERIFIED",
                        "CALCULATED",
                    ),
                    con.execute(
                        """SELECT predicate_code,certainty_code,review_status,
                                  verification_status,extraction_method
                             FROM claims WHERE claim_id=?""",
                        (result.claim_id,),
                    ).fetchone(),
                )
                self.assertEqual(
                    0,
                    con.execute(
                        """SELECT COUNT(*) FROM claims
                            WHERE predicate_code='LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT'"""
                    ).fetchone()[0],
                )
                self.assertEqual(set(self._canonical_counts(con).values()), {0})
            finally:
                con.close()

    def test_accepted_primary_deployment_is_verified_but_not_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            manifest["sources"][0].update(
                {
                    "publisher": "테스트운용",
                    "document_type": "PRESS_RELEASE",
                    "source_kind": "PARTY_PRIMARY",
                }
            )
            manifest["review"] = {
                "reviewer": "reviewer@igisam.com",
                "approved_at": "2026-06-22T10:00:00Z",
                "review_decision": "ACCEPTED",
            }
            result = import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    """SELECT predicate_code,certainty_code,review_status,verification_status,
                              extraction_method
                         FROM claims WHERE claim_id=?""",
                    (result.claim_id,),
                ).fetchone()
                self.assertEqual(
                    (
                        "LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT",
                        "INFERRED",
                        "ACCEPTED",
                        "VERIFIED",
                        "CALCULATED",
                    ),
                    row,
                )
                self.assertEqual(set(self._canonical_counts(con).values()), {0})
            finally:
                con.close()

    def test_exact_text_failure_rolls_back_every_evidence_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            manifest["evidence"][0]["manager_text"] = "원문에 없는 운용사"
            with self.assertRaisesRegex(
                ManifestValidationError, "not an exact source substring"
            ):
                import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0])
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM mentions").fetchone()[0])
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
                self.assertEqual(set(self._canonical_counts(con).values()), {0})
            finally:
                con.close()

    def test_accepted_snippet_deployment_stays_unreviewed_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            manifest["review"] = {
                "reviewer": "reviewer@igisam.com",
                "approved_at": "2026-06-22T10:00:00Z",
                "review_decision": "ACCEPTED",
            }
            manifest["sources"][0]["content_scope"] = "SNIPPET"
            manifest["sources"][0]["family_relation"] = "SYNDICATED"
            result = import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    ("UNREVIEWED", "PENDING"),
                    con.execute(
                        "SELECT review_status,verification_status FROM claims WHERE claim_id=?",
                        (result.claim_id,),
                    ).fetchone(),
                )
                self.assertEqual(set(self._canonical_counts(con).values()), {0})
            finally:
                con.close()

    def test_accepted_original_full_text_article_can_be_verified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            manifest["review"] = {
                "reviewer": "reviewer@igisam.com",
                "approved_at": "2026-06-22T10:00:00Z",
                "review_decision": "ACCEPTED",
            }
            result = import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    ("ACCEPTED", "VERIFIED"),
                    con.execute(
                        "SELECT review_status,verification_status FROM claims WHERE claim_id=?",
                        (result.claim_id,),
                    ).fetchone(),
                )
                self.assertEqual(set(self._canonical_counts(con).values()), {0})
            finally:
                con.close()

    def test_accepted_single_syndicated_full_text_family_stays_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            manifest["sources"][0]["family_relation"] = "SYNDICATED"
            manifest["review"] = {
                "reviewer": "reviewer@igisam.com",
                "approved_at": "2026-06-22T10:00:00Z",
                "review_decision": "ACCEPTED",
            }
            result = import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    ("UNREVIEWED", "PENDING"),
                    con.execute(
                        "SELECT review_status,verification_status FROM claims WHERE claim_id=?",
                        (result.claim_id,),
                    ).fetchone(),
                )
            finally:
                con.close()

    def test_accepted_full_text_with_missing_core_span_stays_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            del manifest["evidence"][0]["track_text"]
            manifest["review"] = {
                "reviewer": "reviewer@igisam.com",
                "approved_at": "2026-06-22T10:00:00Z",
                "review_decision": "ACCEPTED",
            }
            result = import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    ("UNREVIEWED", "PENDING"),
                    con.execute(
                        "SELECT review_status,verification_status FROM claims WHERE claim_id=?",
                        (result.claim_id,),
                    ).fetchone(),
                )
                self.assertEqual(
                    "DOMESTIC_RE",
                    con.execute(
                        """SELECT text_value FROM claim_arguments
                            WHERE claim_id=? AND role_code='MANDATE_TRACK'""",
                        (result.claim_id,),
                    ).fetchone()[0],
                )
            finally:
                con.close()

    def test_wrong_lp_surface_is_rejected_even_when_it_is_in_exact_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("BID")
            manifest["evidence"][0]["lp_text"] = "테스트운용"
            with self.assertRaisesRegex(ManifestValidationError, "canonical LP"):
                import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
                self.assertEqual(
                    0,
                    con.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0],
                )
            finally:
                con.close()

    def test_partial_canonical_surfaces_are_rejected(self) -> None:
        cases = {
            "lp_text": "테스트",
            "manager_text": "테스트",
            "mandate_text": "국내",
            "track_text": "국내",
            "vehicle_or_deal_text": "테스트",
        }
        for field, partial_surface in cases.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                db = Path(td) / "fixture.db"
                self._db(db)
                manifest = self._manifest("DEPLOYMENT")
                manifest["evidence"][0][field] = partial_surface
                with self.assertRaisesRegex(ManifestValidationError, "canonical|linked"):
                    import_manifest(db, manifest)
                con = sqlite3.connect(db)
                try:
                    self.assertEqual(0, con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
                finally:
                    con.close()

    def test_acquired_is_not_a_supported_deployment_action(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            manifest["follow_up_action"] = "ACQUIRED"
            with self.assertRaisesRegex(ManifestValidationError, "follow_up_action"):
                import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
            finally:
                con.close()

    def test_deal_only_accepted_inference_uses_consumer_entity_columns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            del manifest["linked_vehicle_organization_id"]
            manifest["evidence"][0]["vehicle_or_deal_text"] = "테스트센터"
            manifest["review"] = {
                "reviewer": "reviewer@igisam.com",
                "approved_at": "2026-06-22T10:00:00Z",
                "review_decision": "ACCEPTED",
            }
            result = import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    ("ENTITY", "asset_deal", None),
                    con.execute(
                        """SELECT argument_kind,asset_id,project_id
                             FROM claim_arguments
                            WHERE claim_id=? AND role_code='LINKED_DEAL'""",
                        (result.claim_id,),
                    ).fetchone(),
                )
                self.assertEqual(
                    ("테스트센터", "ACCEPTED", "VERIFIED", "CALCULATED"),
                    con.execute(
                        """SELECT a.canonical_name,c.review_status,c.verification_status,
                                  c.extraction_method
                             FROM claims c
                             JOIN claim_arguments ca ON ca.claim_id=c.claim_id
                             JOIN assets a ON a.asset_id=ca.asset_id
                            WHERE c.claim_id=? AND ca.role_code='LINKED_DEAL'""",
                        (result.claim_id,),
                    ).fetchone(),
                )
                self.assertEqual(
                    "ASSET",
                    con.execute(
                        """SELECT m.mention_type
                             FROM claim_evidence ce
                             JOIN mentions m ON m.mention_id=ce.mention_id
                            WHERE ce.claim_id=? AND m.surface_text='테스트센터'""",
                        (result.claim_id,),
                    ).fetchone()[0],
                )
                self.assertEqual(set(self._canonical_counts(con).values()), {0})
            finally:
                con.close()

    def test_unsupported_deal_kind_is_rejected_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            manifest["linked_deal"] = {"kind": "SALE_PROCESS", "id": "sale_process_1"}
            with self.assertRaisesRegex(ManifestValidationError, "linked_deal.kind"):
                import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
            finally:
                con.close()

    def test_stable_id_content_conflict_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            original = self._manifest("BID")
            first = import_manifest(db, original)
            conflicting = copy.deepcopy(original)
            conflicting["follow_up_action"] = "SHORTLISTED"
            with self.assertRaisesRegex(ManifestValidationError, "conflicting existing row"):
                import_manifest(db, conflicting)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    "FINAL_BID_SUBMITTED",
                    con.execute(
                        """SELECT text_value FROM claim_arguments
                            WHERE claim_id=? AND role_code='FOLLOW_UP_ACTION'""",
                        (first.claim_id,),
                    ).fetchone()[0],
                )
                self.assertEqual(1, con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
            finally:
                con.close()

    def test_non_lp_deployment_basis_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fixture.db"
            self._db(db)
            manifest = self._manifest("DEPLOYMENT")
            manifest["funding_basis"] = "FUND_EQUITY_DEPLOYMENT"
            with self.assertRaisesRegex(ManifestValidationError, "funding_basis"):
                import_manifest(db, manifest)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
            finally:
                con.close()

    def test_known_live_path_is_blocked_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "market.db"
            self._db(db)
            with patch(
                "collector.institutional_manager_action_manifest.LIVE_DB_PATHS",
                {db.resolve()},
            ):
                with self.assertRaisesRegex(ManifestValidationError, "fixture-only"):
                    import_manifest(db, self._manifest("BID"))
            con = sqlite3.connect(db)
            try:
                self.assertEqual(0, con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
