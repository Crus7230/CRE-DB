-- PostgreSQL/Supabase feature migration: contextual intelligence and legacy isolation.
-- Additive only. Existing source and derived rows are not modified.
BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

DO $$
BEGIN
  IF (SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version') <> '3.5.0' THEN
    RAISE EXCEPTION 'contextual intelligence migration requires global schema 3.5.0';
  END IF;
  IF EXISTS (SELECT 1 FROM market_intelligence.schema_meta WHERE schema_key='contextual_intelligence_schema_version') THEN
    RAISE EXCEPTION 'contextual intelligence feature already installed';
  END IF;
END $$;

CREATE TABLE market_intelligence.contextual_processing_campaigns (
    campaign_id text PRIMARY KEY,
    campaign_code text NOT NULL UNIQUE,
    corpus_cutoff_at timestamptz NOT NULL,
    taxonomy_version text NOT NULL,
    rule_set_version text NOT NULL,
    model_version text NOT NULL,
    pipeline_version text NOT NULL,
    status_code text NOT NULL CHECK(status_code IN ('DRAFT','RUNNING','COMPLETED','FAILED','SUPERSEDED')),
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    CHECK(completed_at IS NULL OR started_at IS NOT NULL)
);

CREATE TABLE market_intelligence.contextual_rule_sets (
    rule_set_id text PRIMARY KEY,
    rule_set_code text NOT NULL,
    version text NOT NULL,
    status_code text NOT NULL CHECK(status_code IN ('DRAFT','ACTIVE','DEPRECATED','SUPERSEDED')),
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    UNIQUE(rule_set_code,version),
    CHECK(status_code<>'ACTIVE' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

CREATE TABLE market_intelligence.contextual_rules (
    rule_id text PRIMARY KEY,
    rule_set_id text NOT NULL REFERENCES market_intelligence.contextual_rule_sets(rule_set_id) ON DELETE RESTRICT,
    rule_code text NOT NULL,
    event_domain text NOT NULL CHECK(event_domain IN (
      'TRANSACTION','MANAGER_SELECTION','POLICY_REGULATION','MONETARY_POLICY',
      'GEOPOLITICS_TRADE','FINANCING_RESTRUCTURING','INDUSTRY_DEMAND',
      'MARKET_TREND','ASSET_REGIONAL_CHANGE'
    )),
    event_type text NOT NULL,
    priority integer NOT NULL DEFAULT 100,
    minimum_score double precision NOT NULL DEFAULT 1 CHECK(minimum_score>=0),
    definition_json jsonb NOT NULL CHECK(jsonb_typeof(definition_json)='object'),
    status_code text NOT NULL CHECK(status_code IN ('DRAFT','ACTIVE','DEPRECATED')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(rule_set_id,rule_code)
);

CREATE TABLE market_intelligence.contextual_document_runs (
    contextual_run_id text PRIMARY KEY,
    campaign_id text NOT NULL REFERENCES market_intelligence.contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    document_version_id text NOT NULL REFERENCES market_intelligence.document_versions(document_version_id) ON DELETE RESTRICT,
    input_sha256 text NOT NULL,
    status_code text NOT NULL CHECK(status_code IN (
      'PENDING','RUNNING','COMPLETED','NO_CONTEXTUAL_EVENT','INSUFFICIENT_CONTENT',
      'ENTITY_UNRESOLVED','FAILED','SUPERSEDED'
    )),
    candidate_count integer NOT NULL DEFAULT 0 CHECK(candidate_count>=0),
    approved_count integer NOT NULL DEFAULT 0 CHECK(approved_count>=0 AND approved_count<=candidate_count),
    error_code text,
    error_message text,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    UNIQUE(campaign_id,document_version_id),
    CHECK(status_code NOT IN ('COMPLETED','NO_CONTEXTUAL_EVENT','INSUFFICIENT_CONTENT','ENTITY_UNRESOLVED','FAILED') OR completed_at IS NOT NULL)
);

CREATE TABLE market_intelligence.legacy_derived_records (
    legacy_record_id text PRIMARY KEY,
    campaign_id text NOT NULL REFERENCES market_intelligence.contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    target_kind text NOT NULL CHECK(target_kind IN (
      'EXTRACTION_RUN','RECORD_CLASSIFICATION','ANALYTICS_REFRESH_RUN',
      'INSIGHT_SIGNAL','MODEL_INTERPRETATION'
    )),
    target_id text NOT NULL,
    source_table text NOT NULL CHECK(source_table IN (
      'extraction_runs','record_classifications','analytics_refresh_runs',
      'insight_signals','insight_interpretations'
    )),
    producer_run_id text,
    original_status text,
    legacy_reason text NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    UNIQUE(campaign_id,target_kind,target_id)
);

CREATE TABLE market_intelligence.contextual_event_frames (
    frame_id text PRIMARY KEY,
    contextual_run_id text NOT NULL REFERENCES market_intelligence.contextual_document_runs(contextual_run_id) ON DELETE RESTRICT,
    document_version_id text NOT NULL REFERENCES market_intelligence.document_versions(document_version_id) ON DELETE RESTRICT,
    source_event_mention_id text REFERENCES market_intelligence.event_mentions(event_mention_id) ON DELETE RESTRICT,
    canonical_event_id text REFERENCES market_intelligence.events(event_id) ON DELETE RESTRICT,
    extraction_key text NOT NULL,
    event_domain text NOT NULL CHECK(event_domain IN (
      'TRANSACTION','MANAGER_SELECTION','POLICY_REGULATION','MONETARY_POLICY',
      'GEOPOLITICS_TRADE','FINANCING_RESTRUCTURING','INDUSTRY_DEMAND',
      'MARKET_TREND','ASSET_REGIONAL_CHANGE'
    )),
    event_type text NOT NULL,
    event_subtype text,
    stage_code text,
    process_type text,
    action_code text,
    title text NOT NULL,
    summary text,
    temporal_basis text NOT NULL CHECK(temporal_basis IN (
      'EVENT_DATE','ANNOUNCEMENT_DATE','EFFECTIVE_DATE','PUBLICATION_DATE',
      'EXPECTED_DATE','PERIOD','UNKNOWN'
    )),
    event_date_start date,
    event_date_end date,
    modality_code text NOT NULL CHECK(modality_code IN (
      'FACTUAL','PLANNED','POSSIBLE','FORECAST','REPORTED','HISTORICAL','CONDITIONAL','UNKNOWN'
    )),
    polarity_code text NOT NULL CHECK(polarity_code IN ('AFFIRMED','NEGATED','UNCERTAIN')),
    source_grade text NOT NULL CHECK(source_grade IN (
      'OFFICIAL_DIRECT','OFFICIAL_DERIVED','STRUCTURED_DIRECT','MEDIA_DIRECT',
      'MULTI_SOURCE_CORROBORATED','MODEL_INFERRED','UNVERIFIED'
    )),
    confidence double precision NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    review_status text NOT NULL CHECK(review_status IN ('CANDIDATE','REVIEW_READY','APPROVED','REJECTED','SUPERSEDED')),
    extraction_method text NOT NULL CHECK(extraction_method IN ('RULE','WEIGHTED_MODEL','HYBRID','HUMAN')),
    rule_version text NOT NULL,
    model_version text NOT NULL,
    evidence_text text NOT NULL,
    evidence_start integer,
    evidence_end integer,
    evidence_locator text,
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    UNIQUE(contextual_run_id,extraction_key),
    CHECK(event_date_end IS NULL OR event_date_start IS NULL OR event_date_end>=event_date_start),
    CHECK((evidence_start IS NULL AND evidence_end IS NULL) OR
          (evidence_start IS NOT NULL AND evidence_end IS NOT NULL AND evidence_start>=0 AND evidence_end>evidence_start)),
    CHECK(review_status<>'APPROVED' OR
          (length(btrim(evidence_text))>0 AND approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

CREATE TABLE market_intelligence.contextual_frame_participants (
    frame_participant_id text PRIMARY KEY,
    frame_id text NOT NULL REFERENCES market_intelligence.contextual_event_frames(frame_id) ON DELETE CASCADE,
    role_code text NOT NULL,
    ordinal integer NOT NULL DEFAULT 0 CHECK(ordinal>=0),
    entity_kind text NOT NULL CHECK(entity_kind IN ('ORGANIZATION','PERSON','COUNTRY','AUTHORITY','UNKNOWN')),
    entity_id text,
    surface_text text NOT NULL,
    mention_id text REFERENCES market_intelligence.mentions(mention_id) ON DELETE RESTRICT,
    resolution_status text NOT NULL CHECK(resolution_status IN ('UNRESOLVED','CANDIDATE','RESOLVED','REJECTED')),
    confidence double precision CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    evidence_text text,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    UNIQUE(frame_id,role_code,ordinal),
    CHECK(resolution_status<>'RESOLVED' OR entity_id IS NOT NULL)
);

CREATE TABLE market_intelligence.contextual_frame_targets (
    frame_target_id text PRIMARY KEY,
    frame_id text NOT NULL REFERENCES market_intelligence.contextual_event_frames(frame_id) ON DELETE CASCADE,
    target_kind text NOT NULL CHECK(target_kind IN ('ASSET','ASSET_CLASS','PROJECT','REGION','INDUSTRY','ORGANIZATION','MARKET','POLICY_AREA','COMMODITY')),
    target_id text,
    target_code text,
    surface_text text NOT NULL,
    role_code text NOT NULL DEFAULT 'AFFECTED_TARGET',
    resolution_status text NOT NULL CHECK(resolution_status IN ('UNRESOLVED','CANDIDATE','RESOLVED','REJECTED')),
    confidence double precision CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    UNIQUE(frame_id,target_kind,role_code,surface_text),
    CHECK(resolution_status<>'RESOLVED' OR target_id IS NOT NULL OR target_code IS NOT NULL)
);

CREATE TABLE market_intelligence.contextual_impact_assertions (
    impact_assertion_id text PRIMARY KEY,
    cause_frame_id text NOT NULL REFERENCES market_intelligence.contextual_event_frames(frame_id) ON DELETE CASCADE,
    effect_frame_id text REFERENCES market_intelligence.contextual_event_frames(frame_id) ON DELETE RESTRICT,
    target_kind text NOT NULL CHECK(target_kind IN ('ASSET','ASSET_CLASS','PROJECT','REGION','INDUSTRY','ORGANIZATION','MARKET','COST','DEMAND','SUPPLY','LIQUIDITY','VALUE')),
    target_id text,
    target_code text,
    target_text text NOT NULL,
    mechanism_code text NOT NULL,
    direction_code text NOT NULL CHECK(direction_code IN ('INCREASE','DECREASE','POSITIVE','NEGATIVE','MIXED','UNCERTAIN')),
    horizon_code text NOT NULL CHECK(horizon_code IN ('IMMEDIATE','SHORT_TERM','MEDIUM_TERM','LONG_TERM','UNKNOWN')),
    assertion_basis text NOT NULL CHECK(assertion_basis IN ('DIRECT_FACT','OFFICIAL_FORECAST','INDUSTRY_ASSESSMENT','MODEL_DERIVED','ANALYST_HYPOTHESIS','UNCONFIRMED')),
    confidence double precision NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    review_status text NOT NULL CHECK(review_status IN ('CANDIDATE','REVIEW_READY','APPROVED','REJECTED','SUPERSEDED')),
    evidence_text text NOT NULL,
    source_claim_id text REFERENCES market_intelligence.claims(claim_id) ON DELETE RESTRICT,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    CHECK(review_status<>'APPROVED' OR (length(btrim(evidence_text))>0 AND assertion_basis<>'UNCONFIRMED'))
);

CREATE TABLE market_intelligence.contextual_review_decisions (
    review_decision_id text PRIMARY KEY,
    campaign_id text NOT NULL REFERENCES market_intelligence.contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    target_kind text NOT NULL CHECK(target_kind IN ('FRAME','PARTICIPANT','TARGET','IMPACT_ASSERTION')),
    target_id text NOT NULL,
    decision_code text NOT NULL CHECK(decision_code IN ('APPROVE','CORRECT','REJECT','SUPERSEDE','DEFER')),
    before_json jsonb NOT NULL CHECK(jsonb_typeof(before_json)='object'),
    after_json jsonb NOT NULL CHECK(jsonb_typeof(after_json)='object'),
    reason_code text NOT NULL,
    reviewer text NOT NULL,
    eligible_for_training boolean NOT NULL DEFAULT true,
    reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(target_kind,target_id,reviewed_at)
);

CREATE TABLE market_intelligence.contextual_search_records (
    search_record_id text PRIMARY KEY,
    campaign_id text NOT NULL REFERENCES market_intelligence.contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    frame_id text REFERENCES market_intelligence.contextual_event_frames(frame_id) ON DELETE CASCADE,
    record_mode text NOT NULL CHECK(record_mode IN ('APPROVED','CANDIDATE','LEGACY')),
    source_record_kind text NOT NULL,
    source_record_id text NOT NULL,
    title text NOT NULL,
    summary text,
    event_domain text,
    event_type text,
    event_subtype text,
    stage_code text,
    process_type text,
    action_code text,
    event_date date,
    temporal_basis text,
    participant_roles_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(participant_roles_json)='array'),
    participant_entity_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(participant_entity_ids_json)='array'),
    asset_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(asset_ids_json)='array'),
    region_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(region_ids_json)='array'),
    industry_codes_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(industry_codes_json)='array'),
    impact_directions_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(impact_directions_json)='array'),
    source_grade text,
    confidence double precision CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    review_status text NOT NULL,
    evidence_text text,
    evidence_locator text,
    rule_version text,
    model_version text,
    search_text text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata_json)='object'),
    UNIQUE(campaign_id,record_mode,source_record_kind,source_record_id),
    CHECK((record_mode='APPROVED' AND review_status='APPROVED') OR
          (record_mode='CANDIDATE' AND review_status IN ('CANDIDATE','REVIEW_READY')) OR
          record_mode='LEGACY')
);

CREATE INDEX ix_contextual_campaign_status ON market_intelligence.contextual_processing_campaigns(status_code,corpus_cutoff_at);
CREATE INDEX ix_contextual_runs_campaign_status ON market_intelligence.contextual_document_runs(campaign_id,status_code,document_version_id);
CREATE INDEX ix_contextual_legacy_campaign_kind ON market_intelligence.legacy_derived_records(campaign_id,target_kind,source_table);
CREATE INDEX ix_contextual_frames_mode ON market_intelligence.contextual_event_frames(review_status,event_domain,event_type,event_date_start);
CREATE INDEX ix_contextual_frames_document ON market_intelligence.contextual_event_frames(document_version_id,review_status);
CREATE INDEX ix_contextual_frames_canonical ON market_intelligence.contextual_event_frames(canonical_event_id,review_status);
CREATE INDEX ix_contextual_participants_lookup ON market_intelligence.contextual_frame_participants(role_code,entity_id,resolution_status);
CREATE INDEX ix_contextual_targets_lookup ON market_intelligence.contextual_frame_targets(target_kind,target_code,target_id);
CREATE INDEX ix_contextual_impacts_lookup ON market_intelligence.contextual_impact_assertions(direction_code,target_kind,review_status);
CREATE INDEX ix_contextual_search_filters ON market_intelligence.contextual_search_records(record_mode,event_domain,event_type,stage_code,event_date);
CREATE INDEX ix_contextual_search_grade ON market_intelligence.contextual_search_records(record_mode,source_grade,review_status);
CREATE INDEX ix_contextual_search_text_trgm ON market_intelligence.contextual_search_records USING gin (search_text gin_trgm_ops);

INSERT INTO market_intelligence.contextual_rule_sets(
  rule_set_id,rule_set_code,version,status_code,approved_by,approved_at,metadata_json
) VALUES(
  'rule-set-contextual-v1','CRE_CONTEXTUAL_EVENT_FRAME','1.0.0','ACTIVE',
  'SYSTEM_GOVERNED_SEED',clock_timestamp(),
  '{"description":"Context-combination candidate rules; never auto-approve"}'::jsonb
);

INSERT INTO market_intelligence.contextual_rules(
  rule_id,rule_set_id,rule_code,event_domain,event_type,priority,minimum_score,definition_json,status_code
) VALUES
 ('rule-context-transaction','rule-set-contextual-v1','TRANSACTION_CONTEXT','TRANSACTION','TRANSACTION',10,2,'{"requires":["transaction_action"],"supports":["asset","party_role","process_stage"],"blocks":["negated_only"]}'::jsonb,'ACTIVE'),
 ('rule-context-manager','rule-set-contextual-v1','MANAGER_SELECTION_CONTEXT','MANAGER_SELECTION','MANAGER_SELECTION',20,2,'{"requires":["manager_selection_action"],"supports":["appointing_entity","manager_role","selection_stage"]}'::jsonb,'ACTIVE'),
 ('rule-context-policy','rule-set-contextual-v1','POLICY_CONTEXT','POLICY_REGULATION','POLICY_ACTION',30,2,'{"requires":["policy_actor","policy_action"],"supports":["effective_date","policy_target"]}'::jsonb,'ACTIVE'),
 ('rule-context-monetary','rule-set-contextual-v1','MONETARY_CONTEXT','MONETARY_POLICY','RATE_DECISION',40,2,'{"requires":["rate_subject","rate_action"],"supports":["effective_date","rate_value"]}'::jsonb,'ACTIVE'),
 ('rule-context-geopolitics','rule-set-contextual-v1','GEOPOLITICS_CONTEXT','GEOPOLITICS_TRADE','GEOPOLITICAL_ACTION',50,2,'{"requires":["geopolitical_action","actor_or_geography"],"supports":["affected_industry","impact_channel"]}'::jsonb,'ACTIVE'),
 ('rule-context-financing','rule-set-contextual-v1','FINANCING_CONTEXT','FINANCING_RESTRUCTURING','FINANCING_ACTION',60,2,'{"requires":["financing_action"],"supports":["borrower","lender","amount","maturity"]}'::jsonb,'ACTIVE'),
 ('rule-context-industry','rule-set-contextual-v1','INDUSTRY_CONTEXT','INDUSTRY_DEMAND','INDUSTRY_SHIFT',70,3,'{"requires":["industry","change_action","cre_target"],"supports":["transmission_channel"]}'::jsonb,'ACTIVE'),
 ('rule-context-trend','rule-set-contextual-v1','MARKET_TREND_CONTEXT','MARKET_TREND','MARKET_TREND',80,3,'{"requires":["market_metric","direction","period_or_comparison"],"supports":["region","asset_class"]}'::jsonb,'ACTIVE'),
 ('rule-context-place','rule-set-contextual-v1','ASSET_REGION_CONTEXT','ASSET_REGIONAL_CHANGE','ASSET_REGIONAL_CHANGE',90,3,'{"requires":["asset_or_region","change_action"],"supports":["tenant","supply","infrastructure"]}'::jsonb,'ACTIVE');

INSERT INTO market_intelligence.schema_meta(schema_key,schema_value)
VALUES('contextual_intelligence_schema_version','1.0.0');

COMMIT;
