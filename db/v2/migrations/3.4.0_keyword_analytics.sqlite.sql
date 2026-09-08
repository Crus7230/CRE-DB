-- SQLite V3.4.0: deterministic keyword observations and co-occurrences.
BEGIN IMMEDIATE;

CREATE TEMP TABLE _v34_guard(value TEXT NOT NULL CHECK(value='3.3.0'));
INSERT INTO _v34_guard(value) VALUES((SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'));

CREATE TABLE analytics_refresh_runs (
    analytics_refresh_run_id TEXT PRIMARY KEY,
    pipeline_code TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK(status_code IN ('RUNNING','COMPLETED','FAILED','ROLLED_BACK')),
    algorithm_version TEXT NOT NULL,
    window_start TEXT,
    window_end TEXT,
    source_scope_code TEXT NOT NULL DEFAULT 'ALL',
    input_count INTEGER NOT NULL DEFAULT 0,
    output_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object')
) STRICT;

CREATE TABLE keyword_dictionary (
    keyword_id TEXT PRIMARY KEY,
    normalized_term TEXT NOT NULL,
    display_term TEXT NOT NULL,
    term_kind TEXT NOT NULL CHECK(term_kind IN ('TOKEN','PHRASE','ENTITY')),
    status_code TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status_code IN ('ACTIVE','STOPWORD','DEPRECATED')),
    is_collection_bias INTEGER NOT NULL DEFAULT 0 CHECK(is_collection_bias IN (0,1)),
    algorithm_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(normalized_term,algorithm_version)
) STRICT;

CREATE TABLE keyword_observations_daily (
    keyword_observation_id TEXT PRIMARY KEY,
    bucket_date TEXT NOT NULL,
    keyword_id TEXT NOT NULL REFERENCES keyword_dictionary(keyword_id) ON DELETE RESTRICT,
    source_scope_code TEXT NOT NULL DEFAULT 'ALL',
    document_frequency INTEGER NOT NULL CHECK(document_frequency>=0),
    mention_count INTEGER NOT NULL CHECK(mention_count>=document_frequency),
    baseline_document_frequency REAL NOT NULL DEFAULT 0 CHECK(baseline_document_frequency>=0),
    burst_score REAL NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    source_scope_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(source_scope_json) AND json_type(source_scope_json)='object'),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object')
) STRICT;
CREATE UNIQUE INDEX ux_keyword_observation_identity
ON keyword_observations_daily(bucket_date,keyword_id,source_scope_code,algorithm_version);
CREATE INDEX ix_keyword_observations_trend
ON keyword_observations_daily(keyword_id,bucket_date,algorithm_version);
CREATE INDEX ix_keyword_observations_burst
ON keyword_observations_daily(bucket_date,burst_score DESC,document_frequency DESC);

CREATE TABLE keyword_cooccurrences_daily (
    keyword_cooccurrence_id TEXT PRIMARY KEY,
    bucket_date TEXT NOT NULL,
    keyword_left_id TEXT NOT NULL REFERENCES keyword_dictionary(keyword_id) ON DELETE RESTRICT,
    keyword_right_id TEXT NOT NULL REFERENCES keyword_dictionary(keyword_id) ON DELETE RESTRICT,
    source_scope_code TEXT NOT NULL DEFAULT 'ALL',
    document_frequency INTEGER NOT NULL CHECK(document_frequency>0),
    computed_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    CHECK(keyword_left_id<keyword_right_id)
) STRICT;
CREATE UNIQUE INDEX ux_keyword_cooccurrence_identity ON keyword_cooccurrences_daily(bucket_date,keyword_left_id,keyword_right_id,source_scope_code,algorithm_version);
CREATE INDEX ix_keyword_cooccurrences_left ON keyword_cooccurrences_daily(keyword_left_id,bucket_date);
CREATE INDEX ix_keyword_cooccurrences_right ON keyword_cooccurrences_daily(keyword_right_id,bucket_date);

UPDATE schema_meta SET schema_value='3.4.0' WHERE schema_key='schema_version';
DROP TABLE _v34_guard;
COMMIT;
