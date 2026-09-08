from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest


ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "db/v2/schema.sql"
SEED = ROOT / "db/v2/seed.sql"
SQLITE_MIGRATION = ROOT / "db/v2/migrations/3.8.0_contextual_intelligence.sqlite.sql"
POSTGRES_MIGRATION = ROOT / "db/v2/migrations/3.8.0_contextual_intelligence.sql"

EXPECTED_TABLES = {
    "contextual_processing_campaigns",
    "contextual_rule_sets",
    "contextual_rules",
    "contextual_document_runs",
    "legacy_derived_records",
    "contextual_event_frames",
    "contextual_frame_participants",
    "contextual_frame_targets",
    "contextual_impact_assertions",
    "contextual_review_decisions",
    "contextual_search_records",
}
EXPECTED_DOMAINS = {
    "TRANSACTION",
    "MANAGER_SELECTION",
    "POLICY_REGULATION",
    "MONETARY_POLICY",
    "GEOPOLITICS_TRADE",
    "FINANCING_RESTRUCTURING",
    "INDUSTRY_DEMAND",
    "MARKET_TREND",
    "ASSET_REGIONAL_CHANGE",
}


def baseline_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    return conn


def test_dual_engine_migrations_define_same_contract() -> None:
    sqlite_sql = SQLITE_MIGRATION.read_text(encoding="utf-8")
    postgres_sql = POSTGRES_MIGRATION.read_text(encoding="utf-8")
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {table}" in sqlite_sql
        assert f"CREATE TABLE market_intelligence.{table}" in postgres_sql
    for domain in EXPECTED_DOMAINS:
        assert domain in sqlite_sql
        assert domain in postgres_sql
    assert "contextual_intelligence_schema_version" in sqlite_sql
    assert "contextual_intelligence_schema_version" in postgres_sql


def test_sqlite_fresh_install_is_contextual_and_versioned() -> None:
    conn = baseline_connection()
    try:
        objects = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        assert EXPECTED_TABLES <= objects
        assert conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='contextual_intelligence_schema_version'"
        ).fetchone() == ("1.0.0",)
        assert conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone() == ("3.5.0",)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_rules_require_json_objects_not_arrays_or_scalars() -> None:
    conn = baseline_connection()
    try:
        conn.execute(
            """INSERT INTO contextual_rule_sets(
                 rule_set_id,rule_set_code,version,status_code,approved_by,approved_at
               ) VALUES('rs','CRE_CONTEXTUAL','1.0.0','ACTIVE','reviewer','2026-09-03T00:00:00Z')"""
        )
        for invalid in ("[]", "null", '"scalar"'):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO contextual_rules(
                         rule_id,rule_set_id,rule_code,event_domain,event_type,
                         priority,definition_json,status_code
                       ) VALUES(?,?,?,?,?,?,?,'ACTIVE')""",
                    (f"bad-{invalid}", "rs", f"BAD_{invalid}", "TRANSACTION", "SALE", 1, invalid),
                )
    finally:
        conn.close()


def test_approved_frame_requires_direct_evidence_and_approval_metadata() -> None:
    conn = baseline_connection()
    try:
        conn.execute(
            """INSERT INTO contextual_processing_campaigns(
                 campaign_id,campaign_code,corpus_cutoff_at,taxonomy_version,
                 rule_set_version,model_version,pipeline_version,status_code
               ) VALUES('camp','CAMP','2026-09-03T00:00:00Z','1','1','1','1','RUNNING')"""
        )
        conn.execute(
            """INSERT INTO source_documents(
                 document_id,canonical_url,document_type,first_seen_at,last_seen_at
               ) VALUES('doc','https://example.test/doc','RSS_ITEM',
                        '2026-09-03T00:00:00Z','2026-09-03T00:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO document_versions(
                 document_version_id,document_id,version_no,collected_at,
                 content_sha256,rights_status
               ) VALUES('dv','doc',1,'2026-09-03T00:00:00Z',?, 'EXCERPT_ALLOWED')""",
            ("a" * 64,),
        )
        conn.execute(
            """INSERT INTO contextual_document_runs(
                 contextual_run_id,campaign_id,document_version_id,input_sha256,
                 status_code,completed_at
               ) VALUES('run','camp','dv',?,'COMPLETED','2026-09-03T00:30:00Z')""",
            ("a" * 64,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO contextual_event_frames(
                     frame_id,contextual_run_id,document_version_id,extraction_key,
                     event_domain,event_type,title,temporal_basis,modality_code,
                     polarity_code,source_grade,confidence,review_status,
                     extraction_method,rule_version,model_version,evidence_text
                   ) VALUES('bad','run','dv','bad','TRANSACTION','SALE','매각',
                     'PUBLICATION_DATE','FACTUAL','AFFIRMED','MEDIA_DIRECT',0.9,
                     'APPROVED','RULE','1','1','')"""
            )
        conn.execute(
            """INSERT INTO contextual_event_frames(
                 frame_id,contextual_run_id,document_version_id,extraction_key,
                 event_domain,event_type,title,temporal_basis,modality_code,
                 polarity_code,source_grade,confidence,review_status,
                 extraction_method,rule_version,model_version,evidence_text,
                 approved_by,approved_at
               ) VALUES('ok','run','dv','ok','TRANSACTION','SALE','매각',
                 'PUBLICATION_DATE','FACTUAL','AFFIRMED','MEDIA_DIRECT',0.9,
                 'APPROVED','RULE','1','1','회사는 자산을 매각했다.',
                 'reviewer','2026-09-03T01:00:00Z')"""
        )
    finally:
        conn.close()


def test_legacy_ledger_is_reference_only_and_unique_per_campaign_target() -> None:
    conn = baseline_connection()
    try:
        conn.execute(
            """INSERT INTO contextual_processing_campaigns(
                 campaign_id,campaign_code,corpus_cutoff_at,taxonomy_version,
                 rule_set_version,model_version,pipeline_version,status_code
               ) VALUES('camp','CAMP','2026-09-03T00:00:00Z','1','1','1','1','RUNNING')"""
        )
        conn.execute(
            """INSERT INTO legacy_derived_records(
                 legacy_record_id,campaign_id,target_kind,target_id,source_table,
                 legacy_reason
               ) VALUES('l1','camp','EXTRACTION_RUN','run-1','extraction_runs',
                        'PRE_CONTEXTUAL_PIPELINE')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO legacy_derived_records(
                     legacy_record_id,campaign_id,target_kind,target_id,source_table,
                     legacy_reason
                   ) VALUES('l2','camp','EXTRACTION_RUN','run-1','extraction_runs',
                            'PRE_CONTEXTUAL_PIPELINE')"""
            )
    finally:
        conn.close()
