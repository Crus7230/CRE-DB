-- Additive, provider-neutral dashboard projections for SQLite/libSQL.
-- Raw archive and security tables are intentionally untouched.

CREATE TABLE IF NOT EXISTS serving_dataset_freshness (
  dataset_code TEXT PRIMARY KEY,
  source_code TEXT NOT NULL,
  source_as_of_date TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  source_status_code TEXT NOT NULL,
  source_row_count INTEGER NOT NULL CHECK (source_row_count >= 0),
  serving_row_count INTEGER NOT NULL CHECK (serving_row_count >= 0),
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
);

CREATE TABLE IF NOT EXISTS serving_row_fingerprints (
  dataset_code TEXT NOT NULL,
  table_name TEXT NOT NULL,
  row_key_json TEXT NOT NULL CHECK (json_valid(row_key_json)),
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  state_code TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (state_code IN ('ACTIVE','RETIRED')),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (dataset_code, table_name, row_key_json)
);

CREATE INDEX IF NOT EXISTS ix_serving_row_fingerprints_table_state
  ON serving_row_fingerprints(dataset_code, table_name, state_code);

CREATE TABLE IF NOT EXISTS serving_daily_article_dates (
  article_date TEXT PRIMARY KEY,
  article_count INTEGER NOT NULL CHECK (article_count >= 0),
  categorized_count INTEGER NOT NULL CHECK (
    categorized_count >= 0 AND categorized_count <= article_count
  ),
  summarized_count INTEGER NOT NULL CHECK (
    summarized_count >= 0 AND summarized_count <= article_count
  ),
  last_collected_at TEXT,
  generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS serving_daily_articles (
  document_id TEXT PRIMARY KEY,
  document_version_id TEXT NOT NULL UNIQUE,
  article_date TEXT NOT NULL,
  title TEXT NOT NULL,
  publisher_name TEXT,
  published_at TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  summary_text TEXT,
  summary_mode TEXT NOT NULL CHECK (
    summary_mode IN ('BODY_EXTRACTIVE','MODEL','NONE')
  ),
  summary_generated_at TEXT,
  canonical_url TEXT,
  document_purpose_code TEXT,
  document_purpose_label TEXT,
  evidence_grade_code TEXT,
  evidence_grade_label TEXT,
  topic_count INTEGER NOT NULL DEFAULT 0 CHECK (topic_count >= 0),
  projection_generated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_serving_daily_articles_date_order
  ON serving_daily_articles(article_date, published_at DESC, document_id);

CREATE TABLE IF NOT EXISTS serving_daily_article_topics (
  document_id TEXT NOT NULL,
  document_version_id TEXT NOT NULL,
  term_code TEXT NOT NULL,
  term_label TEXT NOT NULL,
  status_code TEXT NOT NULL CHECK (status_code IN ('CONFIRMED','CANDIDATE')),
  provenance_code TEXT NOT NULL CHECK (
    provenance_code IN ('APPROVED_CLASSIFICATION','PENDING_CLASSIFICATION')
  ),
  is_primary INTEGER NOT NULL CHECK (is_primary IN (0,1)),
  confidence REAL,
  sort_order INTEGER NOT NULL,
  topic_rank INTEGER NOT NULL CHECK (topic_rank >= 1),
  PRIMARY KEY (document_id, term_code),
  FOREIGN KEY (document_id) REFERENCES serving_daily_articles(document_id),
  FOREIGN KEY (document_version_id)
    REFERENCES serving_daily_articles(document_version_id)
);

CREATE INDEX IF NOT EXISTS ix_serving_daily_article_topics_rank
  ON serving_daily_article_topics(document_id, topic_rank, term_code);

-- Self-contained fallback used when a freshly collected article has reached
-- compact serving before any older raw-history replica. Payloads deliberately
-- omit unprojected signals instead of inventing drawer content.
CREATE TABLE IF NOT EXISTS serving_daily_article_details (
  document_id TEXT PRIMARY KEY,
  document_version_id TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  projection_generated_at TEXT NOT NULL,
  FOREIGN KEY (document_id) REFERENCES serving_daily_articles(document_id),
  FOREIGN KEY (document_version_id)
    REFERENCES serving_daily_articles(document_version_id)
);

CREATE INDEX IF NOT EXISTS ix_serving_daily_article_details_version
  ON serving_daily_article_details(document_version_id);

-- The permit endpoint reads this compact aggregate only. It never falls back
-- to raw permit snapshots, which keeps online row reads bounded and prevents
-- partial snapshots from leaking into the dashboard.
CREATE TABLE IF NOT EXISTS serving_v2_building_permit_monthly (
  source_id TEXT NOT NULL,
  event_month TEXT NOT NULL CHECK (
    event_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
  ),
  event_type TEXT NOT NULL CHECK (
    event_type IN ('PERMIT','ACTUAL_START','USE_APPROVAL')
  ),
  district_name TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  scope_status TEXT NOT NULL,
  construction_action TEXT NOT NULL,
  permit_count INTEGER NOT NULL CHECK (permit_count >= 0),
  total_floor_area_m2 REAL NOT NULL CHECK (total_floor_area_m2 >= 0),
  missing_area_count INTEGER NOT NULL CHECK (missing_area_count >= 0),
  invalid_area_count INTEGER NOT NULL CHECK (invalid_area_count >= 0),
  PRIMARY KEY (
    source_id,event_month,event_type,district_name,asset_type,
    scope_status,construction_action
  )
);

CREATE INDEX IF NOT EXISTS ix_serving_v2_permit_monthly_query
  ON serving_v2_building_permit_monthly(
    source_id,scope_status,event_month,event_type,asset_type,district_name,
    construction_action
  );

INSERT INTO schema_meta(schema_key,schema_value,updated_at)
VALUES(
  'dashboard_serving_schema_version','1.0.0',
  strftime('%Y-%m-%dT%H:%M:%fZ','now')
)
ON CONFLICT(schema_key) DO UPDATE SET
  schema_value=excluded.schema_value,
  updated_at=excluded.updated_at;
