-- SQLite feature migration: contextual event-frame intelligence and legacy isolation.
-- Additive only: source and pre-existing derived records are never mutated here.
BEGIN IMMEDIATE;

CREATE TEMP TABLE _contextual_v100_guard(value TEXT NOT NULL CHECK(value='3.5.0'));
INSERT INTO _contextual_v100_guard(value)
SELECT schema_value FROM schema_meta WHERE schema_key='schema_version';

CREATE TABLE contextual_processing_campaigns (
    campaign_id TEXT PRIMARY KEY,
    campaign_code TEXT NOT NULL UNIQUE,
    corpus_cutoff_at TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    rule_set_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK(status_code IN ('DRAFT','RUNNING','COMPLETED','FAILED','SUPERSEDED')),
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    CHECK(completed_at IS NULL OR started_at IS NOT NULL)
) STRICT;

CREATE TABLE contextual_rule_sets (
    rule_set_id TEXT PRIMARY KEY,
    rule_set_code TEXT NOT NULL,
    version TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK(status_code IN ('DRAFT','ACTIVE','DEPRECATED','SUPERSEDED')),
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(rule_set_code,version),
    CHECK(status_code<>'ACTIVE' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
) STRICT;

CREATE TABLE contextual_rules (
    rule_id TEXT PRIMARY KEY,
    rule_set_id TEXT NOT NULL REFERENCES contextual_rule_sets(rule_set_id) ON DELETE RESTRICT,
    rule_code TEXT NOT NULL,
    event_domain TEXT NOT NULL CHECK(event_domain IN (
      'TRANSACTION','MANAGER_SELECTION','POLICY_REGULATION','MONETARY_POLICY',
      'GEOPOLITICS_TRADE','FINANCING_RESTRUCTURING','INDUSTRY_DEMAND',
      'MARKET_TREND','ASSET_REGIONAL_CHANGE'
    )),
    event_type TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    minimum_score REAL NOT NULL DEFAULT 1 CHECK(minimum_score>=0),
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json) AND json_type(definition_json)='object'),
    status_code TEXT NOT NULL CHECK(status_code IN ('DRAFT','ACTIVE','DEPRECATED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(rule_set_id,rule_code)
) STRICT;

CREATE TABLE contextual_document_runs (
    contextual_run_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    input_sha256 TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK(status_code IN (
      'PENDING','RUNNING','COMPLETED','NO_CONTEXTUAL_EVENT','INSUFFICIENT_CONTENT',
      'ENTITY_UNRESOLVED','FAILED','SUPERSEDED'
    )),
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(candidate_count>=0),
    approved_count INTEGER NOT NULL DEFAULT 0 CHECK(approved_count>=0 AND approved_count<=candidate_count),
    error_code TEXT,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(campaign_id,document_version_id),
    CHECK(status_code NOT IN ('COMPLETED','NO_CONTEXTUAL_EVENT','INSUFFICIENT_CONTENT','ENTITY_UNRESOLVED','FAILED') OR completed_at IS NOT NULL)
) STRICT;

CREATE TABLE legacy_derived_records (
    legacy_record_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    target_kind TEXT NOT NULL CHECK(target_kind IN (
      'EXTRACTION_RUN','RECORD_CLASSIFICATION','ANALYTICS_REFRESH_RUN',
      'INSIGHT_SIGNAL','MODEL_INTERPRETATION'
    )),
    target_id TEXT NOT NULL,
    source_table TEXT NOT NULL CHECK(source_table IN (
      'extraction_runs','record_classifications','analytics_refresh_runs',
      'insight_signals','insight_interpretations'
    )),
    producer_run_id TEXT,
    original_status TEXT,
    legacy_reason TEXT NOT NULL,
    captured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(campaign_id,target_kind,target_id)
) STRICT;

CREATE TABLE contextual_event_frames (
    frame_id TEXT PRIMARY KEY,
    contextual_run_id TEXT NOT NULL REFERENCES contextual_document_runs(contextual_run_id) ON DELETE RESTRICT,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    source_event_mention_id TEXT REFERENCES event_mentions(event_mention_id) ON DELETE RESTRICT,
    canonical_event_id TEXT REFERENCES events(event_id) ON DELETE RESTRICT,
    extraction_key TEXT NOT NULL,
    event_domain TEXT NOT NULL CHECK(event_domain IN (
      'TRANSACTION','MANAGER_SELECTION','POLICY_REGULATION','MONETARY_POLICY',
      'GEOPOLITICS_TRADE','FINANCING_RESTRUCTURING','INDUSTRY_DEMAND',
      'MARKET_TREND','ASSET_REGIONAL_CHANGE'
    )),
    event_type TEXT NOT NULL,
    event_subtype TEXT,
    stage_code TEXT,
    process_type TEXT,
    action_code TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    temporal_basis TEXT NOT NULL CHECK(temporal_basis IN (
      'EVENT_DATE','ANNOUNCEMENT_DATE','EFFECTIVE_DATE','PUBLICATION_DATE',
      'EXPECTED_DATE','PERIOD','UNKNOWN'
    )),
    event_date_start TEXT,
    event_date_end TEXT,
    modality_code TEXT NOT NULL CHECK(modality_code IN (
      'FACTUAL','PLANNED','POSSIBLE','FORECAST','REPORTED','HISTORICAL','CONDITIONAL','UNKNOWN'
    )),
    polarity_code TEXT NOT NULL CHECK(polarity_code IN ('AFFIRMED','NEGATED','UNCERTAIN')),
    source_grade TEXT NOT NULL CHECK(source_grade IN (
      'OFFICIAL_DIRECT','OFFICIAL_DERIVED','STRUCTURED_DIRECT','MEDIA_DIRECT',
      'MULTI_SOURCE_CORROBORATED','MODEL_INFERRED','UNVERIFIED'
    )),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    review_status TEXT NOT NULL CHECK(review_status IN (
      'CANDIDATE','REVIEW_READY','APPROVED','REJECTED','SUPERSEDED'
    )),
    extraction_method TEXT NOT NULL CHECK(extraction_method IN ('RULE','WEIGHTED_MODEL','HYBRID','HUMAN')),
    rule_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    evidence_start INTEGER,
    evidence_end INTEGER,
    evidence_locator TEXT,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(contextual_run_id,extraction_key),
    CHECK(event_date_end IS NULL OR event_date_start IS NULL OR event_date_end>=event_date_start),
    CHECK((evidence_start IS NULL AND evidence_end IS NULL) OR
          (evidence_start IS NOT NULL AND evidence_end IS NOT NULL AND evidence_start>=0 AND evidence_end>evidence_start)),
    CHECK(review_status<>'APPROVED' OR
          (length(trim(evidence_text))>0 AND approved_by IS NOT NULL AND approved_at IS NOT NULL))
) STRICT;

CREATE TABLE contextual_frame_participants (
    frame_participant_id TEXT PRIMARY KEY,
    frame_id TEXT NOT NULL REFERENCES contextual_event_frames(frame_id) ON DELETE CASCADE,
    role_code TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0 CHECK(ordinal>=0),
    entity_kind TEXT NOT NULL CHECK(entity_kind IN ('ORGANIZATION','PERSON','COUNTRY','AUTHORITY','UNKNOWN')),
    entity_id TEXT,
    surface_text TEXT NOT NULL,
    mention_id TEXT REFERENCES mentions(mention_id) ON DELETE RESTRICT,
    resolution_status TEXT NOT NULL CHECK(resolution_status IN ('UNRESOLVED','CANDIDATE','RESOLVED','REJECTED')),
    confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    evidence_text TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(frame_id,role_code,ordinal),
    CHECK(resolution_status<>'RESOLVED' OR entity_id IS NOT NULL)
) STRICT;

CREATE TABLE contextual_frame_targets (
    frame_target_id TEXT PRIMARY KEY,
    frame_id TEXT NOT NULL REFERENCES contextual_event_frames(frame_id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK(target_kind IN (
      'ASSET','ASSET_CLASS','PROJECT','REGION','INDUSTRY','ORGANIZATION','MARKET','POLICY_AREA','COMMODITY'
    )),
    target_id TEXT,
    target_code TEXT,
    surface_text TEXT NOT NULL,
    role_code TEXT NOT NULL DEFAULT 'AFFECTED_TARGET',
    resolution_status TEXT NOT NULL CHECK(resolution_status IN ('UNRESOLVED','CANDIDATE','RESOLVED','REJECTED')),
    confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(frame_id,target_kind,role_code,surface_text),
    CHECK(resolution_status<>'RESOLVED' OR target_id IS NOT NULL OR target_code IS NOT NULL)
) STRICT;

CREATE TABLE contextual_impact_assertions (
    impact_assertion_id TEXT PRIMARY KEY,
    cause_frame_id TEXT NOT NULL REFERENCES contextual_event_frames(frame_id) ON DELETE CASCADE,
    effect_frame_id TEXT REFERENCES contextual_event_frames(frame_id) ON DELETE RESTRICT,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('ASSET','ASSET_CLASS','PROJECT','REGION','INDUSTRY','ORGANIZATION','MARKET','COST','DEMAND','SUPPLY','LIQUIDITY','VALUE')),
    target_id TEXT,
    target_code TEXT,
    target_text TEXT NOT NULL,
    mechanism_code TEXT NOT NULL,
    direction_code TEXT NOT NULL CHECK(direction_code IN ('INCREASE','DECREASE','POSITIVE','NEGATIVE','MIXED','UNCERTAIN')),
    horizon_code TEXT NOT NULL CHECK(horizon_code IN ('IMMEDIATE','SHORT_TERM','MEDIUM_TERM','LONG_TERM','UNKNOWN')),
    assertion_basis TEXT NOT NULL CHECK(assertion_basis IN (
      'DIRECT_FACT','OFFICIAL_FORECAST','INDUSTRY_ASSESSMENT','MODEL_DERIVED','ANALYST_HYPOTHESIS','UNCONFIRMED'
    )),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    review_status TEXT NOT NULL CHECK(review_status IN ('CANDIDATE','REVIEW_READY','APPROVED','REJECTED','SUPERSEDED')),
    evidence_text TEXT NOT NULL,
    source_claim_id TEXT REFERENCES claims(claim_id) ON DELETE RESTRICT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    CHECK(review_status<>'APPROVED' OR (length(trim(evidence_text))>0 AND assertion_basis<>'UNCONFIRMED'))
) STRICT;

CREATE TABLE contextual_review_decisions (
    review_decision_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('FRAME','PARTICIPANT','TARGET','IMPACT_ASSERTION')),
    target_id TEXT NOT NULL,
    decision_code TEXT NOT NULL CHECK(decision_code IN ('APPROVE','CORRECT','REJECT','SUPERSEDE','DEFER')),
    before_json TEXT NOT NULL CHECK(json_valid(before_json) AND json_type(before_json)='object'),
    after_json TEXT NOT NULL CHECK(json_valid(after_json) AND json_type(after_json)='object'),
    reason_code TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    eligible_for_training INTEGER NOT NULL DEFAULT 1 CHECK(eligible_for_training IN (0,1)),
    reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(target_kind,target_id,reviewed_at)
) STRICT;

CREATE TABLE contextual_search_records (
    search_record_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    frame_id TEXT REFERENCES contextual_event_frames(frame_id) ON DELETE CASCADE,
    record_mode TEXT NOT NULL CHECK(record_mode IN ('APPROVED','CANDIDATE','LEGACY')),
    source_record_kind TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    event_domain TEXT,
    event_type TEXT,
    event_subtype TEXT,
    stage_code TEXT,
    process_type TEXT,
    action_code TEXT,
    event_date TEXT,
    temporal_basis TEXT,
    participant_roles_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(participant_roles_json) AND json_type(participant_roles_json)='array'),
    participant_entity_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(participant_entity_ids_json) AND json_type(participant_entity_ids_json)='array'),
    asset_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(asset_ids_json) AND json_type(asset_ids_json)='array'),
    region_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(region_ids_json) AND json_type(region_ids_json)='array'),
    industry_codes_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(industry_codes_json) AND json_type(industry_codes_json)='array'),
    impact_directions_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(impact_directions_json) AND json_type(impact_directions_json)='array'),
    source_grade TEXT,
    confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    review_status TEXT NOT NULL,
    evidence_text TEXT,
    evidence_locator TEXT,
    rule_version TEXT,
    model_version TEXT,
    search_text TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(campaign_id,record_mode,source_record_kind,source_record_id),
    CHECK((record_mode='APPROVED' AND review_status='APPROVED') OR
          (record_mode='CANDIDATE' AND review_status IN ('CANDIDATE','REVIEW_READY')) OR
          record_mode='LEGACY')
) STRICT;

CREATE INDEX ix_contextual_campaign_status ON contextual_processing_campaigns(status_code,corpus_cutoff_at);
CREATE INDEX ix_contextual_runs_campaign_status ON contextual_document_runs(campaign_id,status_code,document_version_id);
CREATE INDEX ix_contextual_legacy_campaign_kind ON legacy_derived_records(campaign_id,target_kind,source_table);
CREATE INDEX ix_contextual_frames_mode ON contextual_event_frames(review_status,event_domain,event_type,event_date_start);
CREATE INDEX ix_contextual_frames_document ON contextual_event_frames(document_version_id,review_status);
CREATE INDEX ix_contextual_frames_canonical ON contextual_event_frames(canonical_event_id,review_status);
CREATE INDEX ix_contextual_participants_lookup ON contextual_frame_participants(role_code,entity_id,resolution_status);
CREATE INDEX ix_contextual_targets_lookup ON contextual_frame_targets(target_kind,target_code,target_id);
CREATE INDEX ix_contextual_impacts_lookup ON contextual_impact_assertions(direction_code,target_kind,review_status);
CREATE INDEX ix_contextual_search_filters ON contextual_search_records(record_mode,event_domain,event_type,stage_code,event_date);
CREATE INDEX ix_contextual_search_grade ON contextual_search_records(record_mode,source_grade,review_status);

INSERT INTO contextual_rule_sets(
  rule_set_id,rule_set_code,version,status_code,approved_by,approved_at,metadata_json
) VALUES(
  'rule-set-contextual-v1','CRE_CONTEXTUAL_EVENT_FRAME','1.0.0','ACTIVE',
  'SYSTEM_GOVERNED_SEED',strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  '{"description":"Context-combination candidate rules; never auto-approve"}'
);

INSERT INTO contextual_rules(
  rule_id,rule_set_id,rule_code,event_domain,event_type,priority,minimum_score,definition_json,status_code
) VALUES
 ('rule-context-transaction','rule-set-contextual-v1','TRANSACTION_CONTEXT','TRANSACTION','TRANSACTION',10,2,'{"requires":["transaction_action"],"supports":["asset","party_role","process_stage"],"blocks":["negated_only"]}','ACTIVE'),
 ('rule-context-manager','rule-set-contextual-v1','MANAGER_SELECTION_CONTEXT','MANAGER_SELECTION','MANAGER_SELECTION',20,2,'{"requires":["manager_selection_action"],"supports":["appointing_entity","manager_role","selection_stage"]}','ACTIVE'),
 ('rule-context-policy','rule-set-contextual-v1','POLICY_CONTEXT','POLICY_REGULATION','POLICY_ACTION',30,2,'{"requires":["policy_actor","policy_action"],"supports":["effective_date","policy_target"]}','ACTIVE'),
 ('rule-context-monetary','rule-set-contextual-v1','MONETARY_CONTEXT','MONETARY_POLICY','RATE_DECISION',40,2,'{"requires":["rate_subject","rate_action"],"supports":["effective_date","rate_value"]}','ACTIVE'),
 ('rule-context-geopolitics','rule-set-contextual-v1','GEOPOLITICS_CONTEXT','GEOPOLITICS_TRADE','GEOPOLITICAL_ACTION',50,2,'{"requires":["geopolitical_action","actor_or_geography"],"supports":["affected_industry","impact_channel"]}','ACTIVE'),
 ('rule-context-financing','rule-set-contextual-v1','FINANCING_CONTEXT','FINANCING_RESTRUCTURING','FINANCING_ACTION',60,2,'{"requires":["financing_action"],"supports":["borrower","lender","amount","maturity"]}','ACTIVE'),
 ('rule-context-industry','rule-set-contextual-v1','INDUSTRY_CONTEXT','INDUSTRY_DEMAND','INDUSTRY_SHIFT',70,3,'{"requires":["industry","change_action","cre_target"],"supports":["transmission_channel"]}','ACTIVE'),
 ('rule-context-trend','rule-set-contextual-v1','MARKET_TREND_CONTEXT','MARKET_TREND','MARKET_TREND',80,3,'{"requires":["market_metric","direction","period_or_comparison"],"supports":["region","asset_class"]}','ACTIVE'),
 ('rule-context-place','rule-set-contextual-v1','ASSET_REGION_CONTEXT','ASSET_REGIONAL_CHANGE','ASSET_REGIONAL_CHANGE',90,3,'{"requires":["asset_or_region","change_action"],"supports":["tenant","supply","infrastructure"]}','ACTIVE');

INSERT INTO schema_meta(schema_key,schema_value)
VALUES('contextual_intelligence_schema_version','1.0.0');

DROP TABLE _contextual_v100_guard;
COMMIT;
