-- SQLite V3.5.0: versioned model/embedding interpretation boundary.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _v350_guard(value TEXT NOT NULL CHECK(value='3.4.1'));
INSERT INTO _v350_guard(value) VALUES((SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'));

CREATE TABLE analytics_model_registry (
    model_registry_id TEXT PRIMARY KEY,
    task_code TEXT NOT NULL CHECK(task_code IN ('TOPIC_INTERPRETATION','SIGNAL_SUMMARY','EMBEDDING')),
    provider_code TEXT NOT NULL CHECK(length(provider_code)>0),
    model_name TEXT NOT NULL CHECK(length(model_name)>0),
    model_version TEXT NOT NULL CHECK(length(model_version)>0),
    embedding_version TEXT NOT NULL CHECK(length(embedding_version)>0),
    prompt_version TEXT NOT NULL CHECK(length(prompt_version)>0),
    prompt_hash TEXT NOT NULL CHECK(length(prompt_hash)=64),
    status_code TEXT NOT NULL DEFAULT 'DISABLED' CHECK(status_code IN ('ENABLED','DISABLED','RETIRED')),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json) AND json_type(config_json)='object'),
    created_at TEXT NOT NULL,
    retired_at TEXT,
    UNIQUE(task_code,provider_code,model_name,model_version,embedding_version,prompt_version,prompt_hash)
) STRICT;

CREATE TABLE analytics_model_runs (
    model_run_id TEXT PRIMARY KEY,
    model_registry_id TEXT NOT NULL REFERENCES analytics_model_registry(model_registry_id) ON DELETE RESTRICT,
    status_code TEXT NOT NULL CHECK(status_code IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')),
    input_count INTEGER NOT NULL DEFAULT 0 CHECK(input_count>=0),
    output_count INTEGER NOT NULL DEFAULT 0 CHECK(output_count>=0),
    input_token_count INTEGER CHECK(input_token_count IS NULL OR input_token_count>=0),
    output_token_count INTEGER CHECK(output_token_count IS NULL OR output_token_count>=0),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object')
) STRICT;
CREATE INDEX ix_analytics_model_runs_registry ON analytics_model_runs(model_registry_id,started_at DESC);

CREATE TABLE insight_interpretations (
    interpretation_id TEXT PRIMARY KEY,
    insight_signal_id TEXT NOT NULL REFERENCES insight_signals(insight_signal_id) ON DELETE CASCADE,
    model_registry_id TEXT NOT NULL REFERENCES analytics_model_registry(model_registry_id) ON DELETE RESTRICT,
    model_run_id TEXT NOT NULL REFERENCES analytics_model_runs(model_run_id) ON DELETE RESTRICT,
    interpretation_status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(interpretation_status IN ('DRAFT','IN_REVIEW','APPROVED','REJECTED','SUPERSEDED')),
    headline TEXT NOT NULL,
    narrative_text TEXT NOT NULL,
    topic_labels_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(topic_labels_json) AND json_type(topic_labels_json)='array'),
    input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
    output_hash TEXT NOT NULL CHECK(length(output_hash)=64),
    generated_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(insight_signal_id,model_registry_id,input_hash,output_hash)
) STRICT;
CREATE INDEX ix_insight_interpretations_signal ON insight_interpretations(insight_signal_id,interpretation_status,generated_at DESC);
CREATE INDEX ix_insight_interpretations_registry ON insight_interpretations(model_registry_id,generated_at DESC);
CREATE INDEX ix_insight_interpretations_run ON insight_interpretations(model_run_id);

CREATE TABLE insight_interpretation_evidence (
    interpretation_evidence_id TEXT PRIMARY KEY,
    interpretation_id TEXT NOT NULL REFERENCES insight_interpretations(interpretation_id) ON DELETE CASCADE,
    insight_signal_evidence_id TEXT NOT NULL REFERENCES insight_signal_evidence(insight_signal_evidence_id) ON DELETE RESTRICT,
    evidence_role TEXT NOT NULL CHECK(evidence_role IN ('GROUNDING','CONTEXT','CONTRADICTING')),
    created_at TEXT NOT NULL,
    UNIQUE(interpretation_id,insight_signal_evidence_id,evidence_role)
) STRICT;
CREATE INDEX ix_interpretation_evidence_interpretation ON insight_interpretation_evidence(interpretation_id);
CREATE INDEX ix_interpretation_evidence_signal_evidence ON insight_interpretation_evidence(insight_signal_evidence_id);

UPDATE schema_meta SET schema_value='3.5.0' WHERE schema_key='schema_version';
DROP TABLE _v350_guard;
COMMIT;
