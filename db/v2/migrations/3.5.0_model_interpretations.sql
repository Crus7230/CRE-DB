-- PostgreSQL V3.5.0: versioned model/embedding interpretation boundary.
BEGIN;
DO $$ DECLARE current_version TEXT; BEGIN
  SELECT schema_value INTO current_version FROM market_intelligence.schema_meta WHERE schema_key='schema_version';
  IF current_version IS DISTINCT FROM '3.4.1' THEN RAISE EXCEPTION 'Expected schema 3.4.1, found %',COALESCE(current_version,'missing'); END IF;
END $$;

CREATE TABLE market_intelligence.analytics_model_registry (
    model_registry_id TEXT PRIMARY KEY,
    task_code TEXT NOT NULL CHECK(task_code IN ('TOPIC_INTERPRETATION','SIGNAL_SUMMARY','EMBEDDING')),
    provider_code TEXT NOT NULL CHECK(length(provider_code)>0),
    model_name TEXT NOT NULL CHECK(length(model_name)>0),
    model_version TEXT NOT NULL CHECK(length(model_version)>0),
    embedding_version TEXT NOT NULL CHECK(length(embedding_version)>0),
    prompt_version TEXT NOT NULL CHECK(length(prompt_version)>0),
    prompt_hash TEXT NOT NULL CHECK(length(prompt_hash)=64),
    status_code TEXT NOT NULL DEFAULT 'DISABLED' CHECK(status_code IN ('ENABLED','DISABLED','RETIRED')),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(config_json::jsonb)='object'),
    created_at TEXT NOT NULL,
    retired_at TEXT,
    UNIQUE(task_code,provider_code,model_name,model_version,embedding_version,prompt_version,prompt_hash)
);
CREATE TABLE market_intelligence.analytics_model_runs (
    model_run_id TEXT PRIMARY KEY,
    model_registry_id TEXT NOT NULL REFERENCES market_intelligence.analytics_model_registry(model_registry_id) ON DELETE RESTRICT,
    status_code TEXT NOT NULL CHECK(status_code IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')),
    input_count BIGINT NOT NULL DEFAULT 0 CHECK(input_count>=0), output_count BIGINT NOT NULL DEFAULT 0 CHECK(output_count>=0),
    input_token_count BIGINT CHECK(input_token_count IS NULL OR input_token_count>=0), output_token_count BIGINT CHECK(output_token_count IS NULL OR output_token_count>=0),
    started_at TEXT NOT NULL,completed_at TEXT,error_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata_json::jsonb)='object')
);
CREATE INDEX ix_analytics_model_runs_registry ON market_intelligence.analytics_model_runs(model_registry_id,started_at DESC);
CREATE TABLE market_intelligence.insight_interpretations (
    interpretation_id TEXT PRIMARY KEY,
    insight_signal_id TEXT NOT NULL REFERENCES market_intelligence.insight_signals(insight_signal_id) ON DELETE CASCADE,
    model_registry_id TEXT NOT NULL REFERENCES market_intelligence.analytics_model_registry(model_registry_id) ON DELETE RESTRICT,
    model_run_id TEXT NOT NULL REFERENCES market_intelligence.analytics_model_runs(model_run_id) ON DELETE RESTRICT,
    interpretation_status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(interpretation_status IN ('DRAFT','IN_REVIEW','APPROVED','REJECTED','SUPERSEDED')),
    headline TEXT NOT NULL,narrative_text TEXT NOT NULL,
    topic_labels_json TEXT NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(topic_labels_json::jsonb)='array'),
    input_hash TEXT NOT NULL CHECK(length(input_hash)=64),output_hash TEXT NOT NULL CHECK(length(output_hash)=64),
    generated_at TEXT NOT NULL,reviewed_at TEXT,reviewed_by TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata_json::jsonb)='object'),
    UNIQUE(insight_signal_id,model_registry_id,input_hash,output_hash)
);
CREATE INDEX ix_insight_interpretations_signal ON market_intelligence.insight_interpretations(insight_signal_id,interpretation_status,generated_at DESC);
CREATE INDEX ix_insight_interpretations_registry ON market_intelligence.insight_interpretations(model_registry_id,generated_at DESC);
CREATE INDEX ix_insight_interpretations_run ON market_intelligence.insight_interpretations(model_run_id);
CREATE TABLE market_intelligence.insight_interpretation_evidence (
    interpretation_evidence_id TEXT PRIMARY KEY,
    interpretation_id TEXT NOT NULL REFERENCES market_intelligence.insight_interpretations(interpretation_id) ON DELETE CASCADE,
    insight_signal_evidence_id TEXT NOT NULL REFERENCES market_intelligence.insight_signal_evidence(insight_signal_evidence_id) ON DELETE RESTRICT,
    evidence_role TEXT NOT NULL CHECK(evidence_role IN ('GROUNDING','CONTEXT','CONTRADICTING')),
    created_at TEXT NOT NULL,
    UNIQUE(interpretation_id,insight_signal_evidence_id,evidence_role)
);
CREATE INDEX ix_interpretation_evidence_interpretation ON market_intelligence.insight_interpretation_evidence(interpretation_id);
CREATE INDEX ix_interpretation_evidence_signal_evidence ON market_intelligence.insight_interpretation_evidence(insight_signal_evidence_id);
UPDATE market_intelligence.schema_meta SET schema_value = '3.5.0' WHERE schema_key='schema_version';
COMMIT;
