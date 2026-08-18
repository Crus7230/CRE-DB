from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.post_collection_relationships import reconcile_relationships

SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"


class PostCollectionRelationshipsTest(unittest.TestCase):
    def _db(self, path: Path) -> sqlite3.Connection:
        con = sqlite3.connect(path)
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.executescript(SEED.read_text(encoding="utf-8"))
        con.execute("INSERT INTO collection_sources(source_id,source_code,source_name,source_kind,collection_policy) VALUES('src','TEST','Test','MANUAL','METADATA_ONLY')")
        con.execute("INSERT INTO collection_jobs(job_id,job_code,job_version,job_kind,source_id,cadence_code,valid_from) VALUES('job','JOB',1,'CATEGORY_SEARCH','src','MANUAL','2025-01-01')")
        con.execute("INSERT INTO collection_runs(run_id,job_id,started_at,completed_at,status_code) VALUES('run','job','2025-01-01','2025-01-01','COMPLETED')")
        con.execute("INSERT INTO source_documents(document_id,source_id,canonical_url,document_type,first_seen_at,last_seen_at) VALUES('doc','src','https://example.test/1','ARTICLE','2025-01-01','2025-01-01')")
        con.execute("INSERT INTO document_versions(document_version_id,document_id,version_no,title,collected_at,content_sha256,rights_status) VALUES('ver','doc',1,'관계 테스트','2025-01-01',?, 'EXCERPT_ALLOWED')", ('a' * 64,))
        con.execute("INSERT INTO run_documents(run_id,document_version_id,discovered_at) VALUES('run','ver','2025-01-01')")
        con.execute("INSERT INTO extraction_runs(extraction_run_id,document_version_id,pipeline_version,status_code) VALUES('ext','ver','test','COMPLETED')")
        return con

    def _mention(self, con: sqlite3.Connection, mention_id: str, surface: str, start: int) -> None:
        con.execute(
            "INSERT INTO mentions(mention_id,extraction_run_id,mention_type,char_start,char_end,surface_text,normalized_text,confidence,review_status) VALUES(?, 'ext','ORGANIZATION',?,?,?,?,0.95,'ACCEPTED')",
            (mention_id, start, start + len(surface), surface, surface),
        )

    def test_resolves_unique_canonical_and_alias_names_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db.sqlite"
            con = self._db(db)
            con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES('org_a','COMPANY','알파기업')")
            con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES('org_b','COMPANY','베타기업')")
            con.execute("INSERT INTO organization_aliases(organization_alias_id,organization_id,alias_text,normalized_alias,alias_type) VALUES('alias_b','org_b','베타','베타','SHORT_NAME')")
            self._mention(con, 'm1', '알파기업', 0)
            self._mention(con, 'm2', '베타', 10)
            self._mention(con, 'm3', '미확인회사', 20)
            con.commit(); con.close()

            first = reconcile_relationships(db, collection_run_id='run')
            second = reconcile_relationships(db, collection_run_id='run')

            con = sqlite3.connect(db)
            rows = con.execute("SELECT mention_id,organization_id,method_code,selected FROM mention_resolutions ORDER BY mention_id").fetchall()
            self.assertEqual([('m1','org_a','ALIAS',1), ('m2','org_b','ALIAS',1)], rows)
            self.assertEqual(2, first.resolved_mentions)
            self.assertEqual(0, second.resolved_mentions)
            self.assertEqual(1, con.execute("SELECT COUNT(*) FROM v_relationship_gaps WHERE gap_code='UNRESOLVED_ORGANIZATION_MENTION'").fetchone()[0])
            self.assertEqual(2, con.execute("SELECT COUNT(*) FROM relationship_resolution_runs").fetchone()[0])
            con.close()

    def test_ambiguous_alias_creates_candidates_and_one_review_task(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db.sqlite"
            con = self._db(db)
            for oid, name in [('org_a','알파자산운용'),('org_b','알파투자운용')]:
                con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES(?, 'COMPANY', ?)", (oid,name))
                con.execute("INSERT INTO organization_aliases(organization_alias_id,organization_id,alias_text,normalized_alias,alias_type) VALUES(?,?,?,?, 'SHORT_NAME')", ('alias_'+oid,oid,'알파','알파'))
            self._mention(con, 'm1', '알파', 0)
            con.commit(); con.close()

            result = reconcile_relationships(db, collection_run_id='run')

            con = sqlite3.connect(db)
            self.assertEqual(2, con.execute("SELECT COUNT(*) FROM mention_resolutions WHERE mention_id='m1' AND resolution_status='AMBIGUOUS' AND selected=0").fetchone()[0])
            self.assertEqual(1, con.execute("SELECT COUNT(*) FROM review_tasks WHERE target_kind='MENTION' AND target_id='m1' AND review_type='ORGANIZATION_RESOLUTION_REVIEW' AND status_code='PENDING'").fetchone()[0])
            self.assertEqual(1, result.ambiguous_mentions)
            con.close()

    def test_ambiguity_task_closes_and_reopens_as_new_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db.sqlite"
            con = self._db(db)
            for oid, name in [('org_a','알파자산운용'),('org_b','알파투자운용')]:
                con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES(?, 'COMPANY', ?)", (oid,name))
                con.execute("INSERT INTO organization_aliases(organization_alias_id,organization_id,alias_text,normalized_alias,alias_type) VALUES(?,?,?,?, 'SHORT_NAME')", ('alias_'+oid,oid,'알파','알파'))
            self._mention(con, 'm1', '알파', 0)
            con.commit(); con.close()
            reconcile_relationships(db, collection_run_id='run')
            con = sqlite3.connect(db)
            con.execute("UPDATE organizations SET status_code='INACTIVE' WHERE organization_id='org_b'")
            con.commit(); con.close()
            reconcile_relationships(db, collection_run_id='run')
            con = sqlite3.connect(db)
            self.assertEqual(1, con.execute("SELECT COUNT(*) FROM review_tasks WHERE target_id='m1' AND status_code='APPROVED'").fetchone()[0])
            con.execute("UPDATE organizations SET status_code='ACTIVE' WHERE organization_id='org_b'")
            con.execute("UPDATE mention_resolutions SET selected=0,resolution_status='CANDIDATE' WHERE mention_id='m1' AND selected=1")
            con.commit(); con.close()
            reconcile_relationships(db, collection_run_id='run')
            con = sqlite3.connect(db)
            self.assertEqual(2, con.execute("SELECT COUNT(*) FROM review_tasks WHERE target_id='m1'").fetchone()[0])
            self.assertEqual(1, con.execute("SELECT COUNT(*) FROM review_tasks WHERE target_id='m1' AND status_code='PENDING'").fetchone()[0])
            con.close()

    def test_promotes_verified_tenant_claim_and_materializes_occupancy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db.sqlite"
            con = self._db(db)
            con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES('tenant','COMPANY','테넌트기업')")
            con.execute("INSERT INTO assets(asset_id,canonical_name) VALUES('asset','테스트센터')")
            category = con.execute("SELECT event_category_id FROM event_categories WHERE code='LEASE'").fetchone()[0]
            con.execute("INSERT INTO events(event_id,canonical_title,primary_category_id,current_stage_code,event_date_start,date_precision,lifecycle_status,verification_level) VALUES('event','테넌트기업 임대차',?,'LEASE_SIGNED','2025-01-01','DAY','ACTIVE','V3')", (category,))
            con.execute("INSERT INTO event_assets(event_id,asset_id,role_code,confidence) VALUES('event','asset','LEASED_ASSET',1.0)")
            con.execute("INSERT INTO event_mentions(event_mention_id,extraction_run_id,extraction_key,event_category_id,status_code,confidence) VALUES('em','ext','lease',?,'APPROVED',0.95)", (category,))
            con.execute("INSERT INTO event_mention_links(event_mention_id,event_id,relation_code) VALUES('em','event','PRIMARY')")
            con.execute("UPDATE predicate_relationship_rules SET minimum_verification_status='PENDING' WHERE relationship_rule_id='participant-role-tenant'")
            con.execute("INSERT INTO claims(claim_id,event_mention_id,predicate_code,value_kind,raw_value,object_organization_id,confidence,verification_status,review_status,extraction_method) VALUES('claim','em','PARTICIPANT_ROLE','ORGANIZATION_REF','테넌트기업은 임차인','tenant',0.95,'PENDING','ACCEPTED','MANUAL')")
            con.execute("INSERT INTO claim_arguments(claim_argument_id,claim_id,role_code,argument_kind,organization_id,confidence) VALUES('arg','claim','TENANT','ENTITY','tenant',0.95)")
            con.commit(); con.close()

            result = reconcile_relationships(db, collection_run_id='run')

            con = sqlite3.connect(db)
            self.assertEqual(('event','tenant','TENANT','claim'), con.execute("SELECT event_id,organization_id,role_code,supporting_claim_id FROM event_participants WHERE event_id='event'").fetchone())
            self.assertEqual(('tenant','asset','UNKNOWN','TENANT','CONTRACTED','event','claim','PENDING','PENDING'), con.execute("SELECT organization_id,asset_id,occupancy_type,tenure_type,occupancy_status,event_id,source_claim_id,verification_status,review_status FROM organization_property_occupancies").fetchone())
            self.assertEqual(1, result.event_participants_created)
            self.assertEqual(1, result.occupancies_created)
            con.execute("UPDATE claims SET verification_status='CONTRADICTED' WHERE claim_id='claim'")
            con.commit(); con.close()
            reconcile_relationships(db, collection_run_id='run')
            con = sqlite3.connect(db)
            self.assertEqual(0, con.execute("SELECT COUNT(*) FROM event_participants WHERE supporting_claim_id='claim'").fetchone()[0])
            self.assertEqual(('CONTRADICTED','SUPERSEDED'), con.execute("SELECT verification_status,review_status FROM organization_property_occupancies WHERE source_claim_id='claim'").fetchone())
            con.close()

    def test_materializes_verified_business_domain_with_explicit_subject(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db.sqlite"
            con = self._db(db)
            self.assertIsNotNone(con.execute("SELECT 1 FROM claim_role_definitions WHERE role_code='SUBJECT_ORGANIZATION'").fetchone())
            con.execute("INSERT INTO organizations(organization_id,organization_type,canonical_name) VALUES('company','COMPANY','사업기업')")
            category = con.execute("SELECT event_category_id FROM event_categories WHERE code='INVESTMENT'").fetchone()[0]
            con.execute("INSERT INTO event_mentions(event_mention_id,extraction_run_id,extraction_key,event_category_id,status_code,confidence) VALUES('em','ext','business',?,'APPROVED',0.95)", (category,))
            con.execute("INSERT INTO claims(claim_id,event_mention_id,predicate_code,value_kind,raw_value,text_value,date_start,date_precision,confidence,verification_status,review_status,extraction_method) VALUES('business_claim','em','BUSINESS_DOMAIN','TEXT','데이터센터 운영','데이터센터 운영','2025-01-01','DAY',0.95,'VERIFIED','ACCEPTED','MANUAL')")
            con.execute("INSERT INTO claim_arguments(claim_argument_id,claim_id,role_code,argument_kind,organization_id,confidence) VALUES('business_arg','business_claim','SUBJECT_ORGANIZATION','ENTITY','company',0.95)")
            con.commit(); con.close()

            first = reconcile_relationships(db, collection_run_id='run')
            second = reconcile_relationships(db, collection_run_id='run')

            con = sqlite3.connect(db)
            self.assertEqual(('company','데이터센터 운영','2025-01-01','business_claim','VERIFIED','APPROVED'), con.execute("SELECT organization_id,activity_name,valid_from,source_claim_id,verification_status,review_status FROM organization_business_activities").fetchone())
            self.assertEqual(1, first.business_activities_created)
            self.assertEqual(0, second.business_activities_created)
            con.close()

    def test_failed_reconciliation_is_preserved_in_run_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db.sqlite"
            con = self._db(db)
            con.execute("DROP TABLE predicate_relationship_rules")
            con.commit(); con.close()
            with self.assertRaises(sqlite3.OperationalError):
                reconcile_relationships(db)
            con = sqlite3.connect(db)
            self.assertEqual(('FAILED',), con.execute("SELECT status_code FROM relationship_resolution_runs").fetchone())
            error = json.loads(con.execute("SELECT metadata_json FROM relationship_resolution_runs").fetchone()[0])
            self.assertEqual('OperationalError', error['error_type'])
            con.close()


if __name__ == '__main__':
    unittest.main()
