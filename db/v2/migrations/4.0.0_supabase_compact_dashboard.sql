-- Isolated, immutable serving store for the CRE dashboard on the new Supabase project.
-- Raw collection history, wide source documents, MOLIT transactions, and embeddings
-- deliberately remain local.  All runtime reads go through bounded public RPCs.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('cre-dashboard-schema-v1', 0));

CREATE SCHEMA IF NOT EXISTS cre_system;
CREATE SCHEMA IF NOT EXISTS cre_news;
CREATE SCHEMA IF NOT EXISTS cre_timeseries;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;

REVOKE ALL ON SCHEMA cre_system, cre_news, cre_timeseries FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS cre_system.schema_meta (
  schema_key text PRIMARY KEY,
  schema_value text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS cre_system.dataset_versions (
  dataset_version text PRIMARY KEY
    CHECK (dataset_version ~ '^cre-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}$'),
  schema_version text NOT NULL,
  status_code text NOT NULL
    CHECK (status_code IN ('LOADING', 'READY', 'ACTIVE', 'RETIRED', 'FAILED')),
  source_as_of_at timestamptz NOT NULL,
  source_snapshot jsonb NOT NULL,
  source_manifest_sha256 text NOT NULL CHECK (source_manifest_sha256 ~ '^[a-f0-9]{64}$'),
  row_counts jsonb NOT NULL,
  table_hashes jsonb NOT NULL,
  facets jsonb NOT NULL,
  package_bytes bigint NOT NULL CHECK (package_bytes >= 0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ready_at timestamptz,
  activated_at timestamptz,
  CHECK (jsonb_typeof(source_snapshot) = 'object'),
  CHECK (jsonb_typeof(row_counts) = 'object'),
  CHECK (jsonb_typeof(table_hashes) = 'object'),
  CHECK (jsonb_typeof(facets) = 'object')
);

CREATE TABLE IF NOT EXISTS cre_system.active_manifest (
  slot text PRIMARY KEY CHECK (slot = 'dashboard'),
  dataset_version text NOT NULL
    REFERENCES cre_system.dataset_versions(dataset_version) ON DELETE RESTRICT,
  switched_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS cre_system.dataset_lineage (
  dataset_version text NOT NULL
    REFERENCES cre_system.dataset_versions(dataset_version) ON DELETE CASCADE,
  dataset_code text NOT NULL,
  source_code text NOT NULL,
  source_as_of_date date NOT NULL,
  generated_at timestamptz NOT NULL,
  source_status_code text NOT NULL,
  source_row_count bigint NOT NULL CHECK (source_row_count >= 0),
  serving_row_count bigint NOT NULL CHECK (serving_row_count >= 0),
  source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[a-f0-9]{64}$'),
  metadata jsonb NOT NULL,
  PRIMARY KEY (dataset_version, dataset_code),
  CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE IF NOT EXISTS cre_system.authorized_subjects (
  subject_id text PRIMARY KEY CHECK (length(subject_id) BETWEEN 1 AND 160),
  email_normalized text NOT NULL UNIQUE
    CHECK (email_normalized = lower(btrim(email_normalized))),
  approved boolean NOT NULL DEFAULT true,
  approved_at timestamptz NOT NULL,
  approved_by text,
  revoked_at timestamptz,
  revoked_by text,
  access_expires_at timestamptz,
  authz_version bigint NOT NULL DEFAULT 1 CHECK (authz_version > 0),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((approved AND revoked_at IS NULL) OR NOT approved OR revoked_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_cre_authorized_subjects_email_active
  ON cre_system.authorized_subjects (email_normalized)
  WHERE approved AND revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS cre_system.login_rate_limits (
  rate_limit_key text PRIMARY KEY CHECK (length(rate_limit_key) BETWEEN 1 AND 256),
  window_started_at timestamptz NOT NULL,
  attempt_count integer NOT NULL CHECK (attempt_count BETWEEN 1 AND 1000000),
  blocked_until timestamptz,
  updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_cre_login_rate_limits_updated
  ON cre_system.login_rate_limits (updated_at);

CREATE TABLE IF NOT EXISTS cre_news.article_dates (
  dataset_version text NOT NULL
    REFERENCES cre_system.dataset_versions(dataset_version) ON DELETE CASCADE,
  article_date date NOT NULL,
  article_count integer NOT NULL CHECK (article_count >= 0),
  categorized_count integer NOT NULL CHECK (categorized_count >= 0),
  summarized_count integer NOT NULL CHECK (summarized_count >= 0),
  last_collected_at timestamptz,
  generated_at timestamptz NOT NULL,
  PRIMARY KEY (dataset_version, article_date),
  CHECK (categorized_count <= article_count),
  CHECK (summarized_count <= article_count)
);

CREATE INDEX IF NOT EXISTS ix_cre_article_dates_latest
  ON cre_news.article_dates (dataset_version, article_date DESC);

CREATE TABLE IF NOT EXISTS cre_news.articles (
  dataset_version text NOT NULL
    REFERENCES cre_system.dataset_versions(dataset_version) ON DELETE CASCADE,
  document_id text NOT NULL,
  document_version_id text NOT NULL,
  article_date date NOT NULL,
  title text NOT NULL,
  publisher_name text,
  published_at timestamptz NOT NULL,
  collected_at timestamptz NOT NULL,
  summary_text text,
  summary_mode text NOT NULL,
  summary_generated_at timestamptz,
  canonical_url text,
  document_purpose_code text,
  document_purpose_label text,
  evidence_grade_code text,
  evidence_grade_label text,
  topic_count integer NOT NULL CHECK (topic_count >= 0),
  projection_generated_at timestamptz NOT NULL,
  evidence_text text NOT NULL,
  search_text text NOT NULL,
  PRIMARY KEY (dataset_version, document_id),
  UNIQUE (dataset_version, document_version_id)
);

CREATE INDEX IF NOT EXISTS ix_cre_articles_date_order
  ON cre_news.articles (dataset_version, article_date, published_at DESC, document_id);
CREATE INDEX IF NOT EXISTS ix_cre_articles_publisher_date
  ON cre_news.articles (dataset_version, publisher_name, article_date DESC);
CREATE INDEX IF NOT EXISTS ix_cre_articles_search_trgm
  ON cre_news.articles USING gin (search_text extensions.gin_trgm_ops);

CREATE TABLE IF NOT EXISTS cre_news.article_topics (
  dataset_version text NOT NULL,
  document_id text NOT NULL,
  document_version_id text NOT NULL,
  term_code text NOT NULL,
  term_label text NOT NULL,
  status_code text NOT NULL,
  provenance_code text NOT NULL,
  is_primary boolean NOT NULL,
  confidence double precision,
  sort_order integer NOT NULL,
  topic_rank integer NOT NULL,
  PRIMARY KEY (dataset_version, document_id, term_code),
  FOREIGN KEY (dataset_version, document_id)
    REFERENCES cre_news.articles(dataset_version, document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_cre_article_topics_topic
  ON cre_news.article_topics (dataset_version, term_code, document_id);
CREATE INDEX IF NOT EXISTS ix_cre_article_topics_rank
  ON cre_news.article_topics (dataset_version, document_id, topic_rank, term_code);

CREATE TABLE IF NOT EXISTS cre_news.article_search_documents (
  dataset_version text NOT NULL,
  document_id text NOT NULL,
  terms text[] NOT NULL CHECK (cardinality(terms) > 0),
  PRIMARY KEY (dataset_version, document_id),
  FOREIGN KEY (dataset_version, document_id)
    REFERENCES cre_news.articles(dataset_version, document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_cre_article_search_documents_terms
  ON cre_news.article_search_documents USING gin (terms);

CREATE TABLE IF NOT EXISTS cre_news.article_details (
  dataset_version text NOT NULL,
  document_id text NOT NULL,
  document_version_id text NOT NULL,
  payload jsonb NOT NULL,
  projection_generated_at timestamptz NOT NULL,
  PRIMARY KEY (dataset_version, document_id),
  UNIQUE (dataset_version, document_version_id),
  FOREIGN KEY (dataset_version, document_id)
    REFERENCES cre_news.articles(dataset_version, document_id) ON DELETE CASCADE,
  CHECK (jsonb_typeof(payload) = 'object')
);

CREATE TABLE IF NOT EXISTS cre_timeseries.macro_series (
  dataset_version text NOT NULL
    REFERENCES cre_system.dataset_versions(dataset_version) ON DELETE CASCADE,
  macro_series_id text NOT NULL,
  series_code text NOT NULL,
  series_name_ko text NOT NULL,
  metric_code text NOT NULL,
  source_id text,
  source_name text,
  external_series_key text,
  frequency_code text NOT NULL,
  unit_code text NOT NULL,
  region_id text,
  asset_class_id text,
  adjustment_code text NOT NULL,
  aggregation_code text,
  definition_text text NOT NULL,
  valid_from date,
  valid_to date,
  is_active boolean NOT NULL,
  metadata jsonb NOT NULL,
  PRIMARY KEY (dataset_version, macro_series_id),
  UNIQUE (dataset_version, series_code),
  CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE IF NOT EXISTS cre_timeseries.macro_monthly (
  dataset_version text NOT NULL,
  series_code text NOT NULL,
  source_id text NOT NULL,
  region_id text,
  observation_month date NOT NULL,
  numeric_value numeric NOT NULL,
  observation_count integer NOT NULL CHECK (observation_count >= 0),
  aggregation_code text NOT NULL,
  unit_code text NOT NULL,
  source_vintage_at timestamptz NOT NULL,
  published_at timestamptz NOT NULL,
  PRIMARY KEY (dataset_version, series_code, observation_month),
  FOREIGN KEY (dataset_version, series_code)
    REFERENCES cre_timeseries.macro_series(dataset_version, series_code) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_cre_macro_monthly_range
  ON cre_timeseries.macro_monthly (dataset_version, series_code, observation_month);

CREATE TABLE IF NOT EXISTS cre_timeseries.permit_monthly (
  dataset_version text NOT NULL
    REFERENCES cre_system.dataset_versions(dataset_version) ON DELETE CASCADE,
  source_id text NOT NULL,
  event_month date NOT NULL,
  event_type text NOT NULL,
  district_name text NOT NULL,
  asset_type text NOT NULL,
  construction_action text NOT NULL,
  permit_count integer NOT NULL CHECK (permit_count >= 0),
  total_floor_area_m2 numeric NOT NULL CHECK (total_floor_area_m2 >= 0),
  missing_area_count integer NOT NULL CHECK (missing_area_count >= 0),
  invalid_area_count integer NOT NULL CHECK (invalid_area_count >= 0),
  PRIMARY KEY (
    dataset_version, event_month, event_type, district_name, asset_type,
    construction_action
  )
);

CREATE INDEX IF NOT EXISTS ix_cre_permit_event_type
  ON cre_timeseries.permit_monthly (dataset_version, event_type, event_month);
CREATE INDEX IF NOT EXISTS ix_cre_permit_asset_type
  ON cre_timeseries.permit_monthly (dataset_version, asset_type, event_month);
CREATE INDEX IF NOT EXISTS ix_cre_permit_district
  ON cre_timeseries.permit_monthly (dataset_version, district_name, event_month);
CREATE INDEX IF NOT EXISTS ix_cre_permit_action
  ON cre_timeseries.permit_monthly (dataset_version, construction_action, event_month);

CREATE TABLE IF NOT EXISTS cre_timeseries.market_pulse (
  dataset_version text PRIMARY KEY
    REFERENCES cre_system.dataset_versions(dataset_version) ON DELETE CASCADE,
  as_of_period date NOT NULL,
  payload jsonb NOT NULL,
  source_content_sha256 text NOT NULL CHECK (source_content_sha256 ~ '^[a-f0-9]{64}$'),
  generated_at timestamptz NOT NULL,
  CHECK (jsonb_typeof(payload) = 'object')
);

ALTER TABLE cre_system.schema_meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_system.dataset_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_system.active_manifest ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_system.dataset_lineage ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_system.authorized_subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_system.login_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_news.article_dates ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_news.articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_news.article_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_news.article_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_news.article_search_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_timeseries.macro_series ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_timeseries.macro_monthly ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_timeseries.permit_monthly ENABLE ROW LEVEL SECURITY;
ALTER TABLE cre_timeseries.market_pulse ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA cre_system, cre_news, cre_timeseries
  FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.dashboard_serving_manifest()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system
AS $$
  SELECT jsonb_build_object(
    'datasetVersion', version.dataset_version,
    'schemaVersion', version.schema_version,
    'sourceAsOfAt', version.source_as_of_at,
    'activatedAt', version.activated_at,
    'rowCounts', version.row_counts,
    'tableHashes', version.table_hashes,
    'facets', version.facets,
    'packageBytes', version.package_bytes,
    'sourceManifestSha256', version.source_manifest_sha256,
    'lineage', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'datasetCode', lineage.dataset_code,
        'sourceCode', lineage.source_code,
        'sourceAsOfDate', lineage.source_as_of_date,
        'generatedAt', lineage.generated_at,
        'sourceStatusCode', lineage.source_status_code,
        'sourceRowCount', lineage.source_row_count,
        'servingRowCount', lineage.serving_row_count,
        'sourceContentSha256', lineage.source_content_sha256,
        'metadata', lineage.metadata
      ) ORDER BY lineage.dataset_code)
      FROM cre_system.dataset_lineage lineage
      WHERE lineage.dataset_version = version.dataset_version
    ), '[]'::jsonb)
  )
  FROM cre_system.active_manifest active
  JOIN cre_system.dataset_versions version USING (dataset_version)
  WHERE active.slot = 'dashboard' AND version.status_code = 'ACTIVE';
$$;

CREATE OR REPLACE FUNCTION public.dashboard_daily_articles(
  p_date date DEFAULT NULL,
  p_limit integer DEFAULT 200,
  p_dataset_version text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system, cre_news
AS $$
DECLARE
  v_version text;
  v_selected date;
  v_latest date;
  v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 200), 1), 200);
  v_payload jsonb;
BEGIN
  SELECT version.dataset_version INTO v_version
  FROM cre_system.dataset_versions version
  WHERE version.dataset_version = COALESCE(
      p_dataset_version,
      (SELECT dataset_version FROM cre_system.active_manifest WHERE slot = 'dashboard')
    )
    AND version.status_code IN ('ACTIVE', 'RETIRED');
  IF v_version IS NULL THEN RAISE EXCEPTION 'dashboard dataset unavailable'; END IF;

  SELECT max(article_date) INTO v_latest
  FROM cre_news.article_dates WHERE dataset_version = v_version;
  v_selected := COALESCE(p_date, v_latest);

  WITH selected_articles AS MATERIALIZED (
    SELECT article.*
    FROM cre_news.articles article
    WHERE article.dataset_version = v_version
      AND article.article_date = v_selected
    ORDER BY article.published_at DESC, article.document_id
    LIMIT v_limit
  )
  SELECT jsonb_build_object(
    'datasetVersion', v_version,
    'selectedDate', v_selected,
    'latestAvailableDate', v_latest,
    'lastCollectedAt', (
      SELECT last_collected_at FROM cre_news.article_dates
      WHERE dataset_version = v_version AND last_collected_at IS NOT NULL
      ORDER BY article_date DESC LIMIT 1
    ),
    'generatedAt', clock_timestamp(),
    'total', COALESCE((
      SELECT article_count FROM cre_news.article_dates
      WHERE dataset_version = v_version AND article_date = v_selected
    ), 0),
    'returned', (SELECT count(*) FROM selected_articles),
    'articles', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'id', article.document_id,
        'title', article.title,
        'publisher', article.publisher_name,
        'publishedAt', article.published_at,
        'collectedAt', article.collected_at,
        'summary', article.summary_text,
        'summaryMode', article.summary_mode,
        'summaryGeneratedAt', article.summary_generated_at,
        'href', article.canonical_url,
        'topics', COALESCE((
          SELECT jsonb_agg(jsonb_build_object(
            'key', topic.term_code,
            'label', topic.term_label,
            'status', topic.status_code,
            'provenance', topic.provenance_code
          ) ORDER BY topic.topic_rank, topic.term_code)
          FROM cre_news.article_topics topic
          WHERE topic.dataset_version = v_version
            AND topic.document_id = article.document_id
        ), '[]'::jsonb),
        'documentPurpose', CASE WHEN article.document_purpose_code IS NULL THEN NULL
          ELSE jsonb_build_object('code', article.document_purpose_code,
                                  'label', article.document_purpose_label) END,
        'evidenceGrade', CASE WHEN article.evidence_grade_code IS NULL THEN NULL
          ELSE jsonb_build_object('code', article.evidence_grade_code,
                                  'label', article.evidence_grade_label) END
      ) ORDER BY article.published_at DESC, article.document_id)
      FROM selected_articles article
    ), '[]'::jsonb)
  ) INTO v_payload;
  RETURN v_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.dashboard_article_detail(
  p_document_id text,
  p_dataset_version text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system, cre_news
AS $$
  SELECT detail.payload || jsonb_build_object('datasetVersion', detail.dataset_version)
  FROM cre_system.dataset_versions version
  JOIN cre_news.article_details detail USING (dataset_version)
  WHERE detail.dataset_version = COALESCE(
      p_dataset_version,
      (SELECT dataset_version FROM cre_system.active_manifest WHERE slot = 'dashboard')
    )
    AND version.status_code IN ('ACTIVE', 'RETIRED')
    AND detail.document_id = p_document_id
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.dashboard_macro_timeseries(
  p_dataset_version text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system, cre_timeseries
AS $$
  WITH registry(series_code, group_code, display_order) AS (
    VALUES
      ('BOK_BASE_RATE_MONTHLY','KOREA',10),
      ('KR_CD_91D','KOREA',20),
      ('KR_GOVT_BOND_3Y','KOREA',30),
      ('KR_GOVT_BOND_10Y','KOREA',40),
      ('KR_CORP_BOND_AA_MINUS_3Y','KOREA',50),
      ('US_FED_TARGET_LOWER','US_POLICY',60),
      ('US_FED_TARGET_UPPER','US_POLICY',70),
      ('US_EFFR','US_POLICY',80),
      ('US_SOFR','US_POLICY',90),
      ('US_TREASURY_2Y','US_TREASURY',100),
      ('US_TREASURY_10Y','US_TREASURY',110),
      ('US_TREASURY_30Y','US_TREASURY',120),
      ('US_TREASURY_10Y_MINUS_2Y','US_TREASURY',130)
  ), active AS (
    SELECT version.dataset_version
    FROM cre_system.dataset_versions version
    WHERE version.dataset_version = COALESCE(
        p_dataset_version,
        (SELECT dataset_version FROM cre_system.active_manifest WHERE slot = 'dashboard')
      )
      AND version.status_code IN ('ACTIVE', 'RETIRED')
  ), bounds AS (
    SELECT min(f.observation_month) AS available_from,
           max(f.observation_month) AS available_through,
           least(
             max(f.observation_month),
             (date_trunc('month', now() AT TIME ZONE 'Asia/Seoul') - interval '1 month')::date
           ) AS complete_through
    FROM cre_timeseries.macro_monthly f
    JOIN registry r USING (series_code)
    JOIN active USING (dataset_version)
  ), series_rows AS (
    SELECT r.display_order, r.series_code, r.group_code, s.series_name_ko, s.valid_from,
           s.source_name, f.unit_code, f.source_vintage_at, f.observation_month,
           f.numeric_value, f.observation_count, b.complete_through
    FROM active a
    JOIN cre_timeseries.macro_monthly f USING (dataset_version)
    JOIN registry r USING (series_code)
    JOIN cre_timeseries.macro_series s
      ON s.dataset_version = f.dataset_version AND s.series_code = f.series_code
    CROSS JOIN bounds b
  ), headers AS (
    SELECT display_order, series_code, group_code, series_name_ko, valid_from,
           source_name, unit_code, max(source_vintage_at) AS source_vintage_at
    FROM series_rows
    GROUP BY display_order, series_code, group_code, series_name_ko, valid_from,
             source_name, unit_code
  )
  SELECT jsonb_build_object(
    'datasetVersion', (SELECT dataset_version FROM active),
    'generatedAt', clock_timestamp(),
    'availableFrom', to_char(bounds.available_from, 'YYYY-MM'),
    'availableThrough', to_char(bounds.available_through, 'YYYY-MM'),
    'completeThrough', to_char(bounds.complete_through, 'YYYY-MM'),
    'series', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'code', header.series_code,
        'name', header.series_name_ko,
        'group', header.group_code,
        'source', header.source_name,
        'unit', header.unit_code,
        'validFrom', header.valid_from,
        'sourceVintageAt', header.source_vintage_at,
        'points', COALESCE((
          SELECT jsonb_agg(jsonb_build_object(
            'month', to_char(point.observation_month, 'YYYY-MM'),
            'value', point.numeric_value,
            'observationCount', point.observation_count,
            'partial', point.observation_month > point.complete_through
          ) ORDER BY point.observation_month, point.source_vintage_at,
                     point.numeric_value, point.observation_count)
          FROM series_rows point WHERE point.series_code = header.series_code
        ), '[]'::jsonb)
      ) ORDER BY header.display_order, header.series_code)
      FROM headers header
    ), '[]'::jsonb)
  )
  FROM bounds;
$$;

CREATE OR REPLACE FUNCTION public.dashboard_permit_timeseries(
  p_group_by text,
  p_from date DEFAULT NULL,
  p_to date DEFAULT NULL,
  p_event_type text DEFAULT NULL,
  p_asset_type text DEFAULT NULL,
  p_district text DEFAULT NULL,
  p_construction_action text DEFAULT NULL,
  p_dataset_version text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system, cre_timeseries
AS $$
DECLARE
  v_version text;
  v_available_from date;
  v_available_through date;
  v_selected_from date;
  v_selected_through date;
  v_payload jsonb;
BEGIN
  IF p_group_by NOT IN ('EVENT_TYPE','ASSET_TYPE','DISTRICT','CONSTRUCTION_ACTION') THEN
    RAISE EXCEPTION 'invalid permit group';
  END IF;
  SELECT version.dataset_version INTO v_version
  FROM cre_system.dataset_versions version
  WHERE version.dataset_version = COALESCE(
      p_dataset_version,
      (SELECT dataset_version FROM cre_system.active_manifest WHERE slot = 'dashboard')
    )
    AND version.status_code IN ('ACTIVE', 'RETIRED');
  IF v_version IS NULL THEN RAISE EXCEPTION 'dashboard dataset unavailable'; END IF;

  SELECT min(event_month), max(event_month)
  INTO v_available_from, v_available_through
  FROM cre_timeseries.permit_monthly
  WHERE dataset_version = v_version
    AND event_month BETWEEN date '1900-01-01'
                        AND date_trunc('month', now() AT TIME ZONE 'Asia/Seoul')::date;
  v_selected_from := COALESCE(
    date_trunc('month', p_from)::date,
    (v_available_through - interval '59 months')::date
  );
  v_selected_through := COALESCE(date_trunc('month', p_to)::date, v_available_through);
  IF v_selected_from > v_selected_through THEN RAISE EXCEPTION 'invalid permit range'; END IF;

  WITH filtered AS MATERIALIZED (
    SELECT monthly.*
    FROM cre_timeseries.permit_monthly monthly
    WHERE monthly.dataset_version = v_version
      AND monthly.event_month BETWEEN v_selected_from AND v_selected_through
      AND (p_event_type IS NULL OR monthly.event_type = p_event_type)
      AND (p_asset_type IS NULL OR monthly.asset_type = p_asset_type)
      AND (p_district IS NULL OR monthly.district_name = p_district)
      AND (p_construction_action IS NULL
           OR monthly.construction_action = p_construction_action)
  ), grouped AS MATERIALIZED (
    SELECT CASE p_group_by
             WHEN 'EVENT_TYPE' THEN event_type
             WHEN 'ASSET_TYPE' THEN asset_type
             WHEN 'DISTRICT' THEN district_name
             WHEN 'CONSTRUCTION_ACTION' THEN construction_action
           END AS group_key,
           event_month,
           sum(permit_count) AS permit_count,
           sum(total_floor_area_m2) AS total_floor_area_m2,
           sum(missing_area_count) AS missing_area_count,
           sum(invalid_area_count) AS invalid_area_count
    FROM filtered
    GROUP BY group_key, event_month
  ), series_keys AS (
    SELECT DISTINCT group_key FROM grouped WHERE group_key IS NOT NULL
  ), freshness AS (
    SELECT source_as_of_date, generated_at
    FROM cre_system.dataset_lineage
    WHERE dataset_version = v_version AND dataset_code = 'SEOUL_BUILDING_PERMITS'
  )
  SELECT jsonb_build_object(
    'datasetVersion', v_version,
    'generatedAt', (SELECT generated_at FROM freshness),
    'sourceAsOfDate', (SELECT source_as_of_date FROM freshness),
    'availableFrom', to_char(v_available_from, 'YYYY-MM'),
    'availableThrough', to_char(v_available_through, 'YYYY-MM'),
    'selectedFrom', to_char(v_selected_from, 'YYYY-MM'),
    'selectedThrough', to_char(v_selected_through, 'YYYY-MM'),
    'groupBy', p_group_by,
    'filters', jsonb_build_object(
      'eventType', p_event_type,
      'assetType', p_asset_type,
      'district', p_district,
      'constructionAction', p_construction_action
    ),
    'source', jsonb_build_object(
      'code', 'src_seoul_building_permit', 'label', '서울 열린데이터광장'
    ),
    'scope', jsonb_build_object(
      'status', 'IN_SCOPE',
      'completedSnapshotsOnly', true,
      'dateRule', 'ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT'
    ),
    'series', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'key', series.group_key,
        'label', CASE series.group_key
          WHEN 'PERMIT' THEN '건축허가'
          WHEN 'ACTUAL_START' THEN '착공'
          WHEN 'USE_APPROVAL' THEN '사용승인'
          WHEN 'OFFICE' THEN '오피스'
          WHEN 'LOGISTICS' THEN '물류센터'
          WHEN 'DATA_CENTER' THEN '데이터센터'
          WHEN 'HOTEL' THEN '호텔'
          WHEN 'RETAIL' THEN '리테일'
          WHEN 'MIXED_USE' THEN '복합용도'
          WHEN 'OTHER_COMMERCIAL' THEN '기타 상업시설'
          WHEN 'NONCOMMERCIAL' THEN '비상업시설'
          WHEN 'RESIDENTIAL' THEN '주거시설'
          WHEN 'UNKNOWN' THEN '미분류'
          WHEN 'NEW_SUPPLY' THEN '신규 공급'
          WHEN 'AREA_EXPANSION' THEN '증축'
          WHEN 'REDEVELOPMENT' THEN '재개발'
          WHEN 'USE_CONVERSION' THEN '용도 전환'
          WHEN 'OTHER' THEN '기타 공사'
          ELSE series.group_key
        END,
        'points', COALESCE((
          SELECT jsonb_agg(jsonb_build_object(
            'month', to_char(point.event_month, 'YYYY-MM'),
            'permitCount', point.permit_count,
            'totalFloorAreaM2', point.total_floor_area_m2,
            'missingAreaCount', point.missing_area_count,
            'invalidAreaCount', point.invalid_area_count
          ) ORDER BY point.event_month)
          FROM grouped point WHERE point.group_key = series.group_key
        ), '[]'::jsonb)
      ) ORDER BY series.group_key)
      FROM series_keys series
    ), '[]'::jsonb),
    'quality', jsonb_build_object(
      'aggregateRowCount', (SELECT count(*) FROM filtered),
      'permitCount', COALESCE((SELECT sum(permit_count) FROM filtered), 0),
      'totalFloorAreaM2', COALESCE((SELECT sum(total_floor_area_m2) FROM filtered), 0),
      'missingAreaCount', COALESCE((SELECT sum(missing_area_count) FROM filtered), 0),
      'invalidAreaCount', COALESCE((SELECT sum(invalid_area_count) FROM filtered), 0)
    )
  ) INTO v_payload;
  RETURN v_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.dashboard_market_pulse(
  p_dataset_version text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system, cre_timeseries
AS $$
  SELECT pulse.payload || jsonb_build_object('datasetVersion', pulse.dataset_version)
  FROM cre_system.dataset_versions version
  JOIN cre_timeseries.market_pulse pulse USING (dataset_version)
  WHERE pulse.dataset_version = COALESCE(
      p_dataset_version,
      (SELECT dataset_version FROM cre_system.active_manifest WHERE slot = 'dashboard')
    )
    AND version.status_code IN ('ACTIVE', 'RETIRED');
$$;

CREATE OR REPLACE FUNCTION public.dashboard_contextual_evidence_search(
  q text,
  filters jsonb DEFAULT '{}'::jsonb,
  top_k integer DEFAULT 8,
  p_dataset_version text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, extensions, cre_system, cre_news
SET enable_seqscan = off
AS $$
DECLARE
  v_version text;
  v_q text := btrim(COALESCE(q, ''));
  v_filters jsonb := COALESCE(filters, '{}'::jsonb);
  v_top_k integer := LEAST(GREATEST(COALESCE(top_k, 8), 1), 8);
  v_like_pattern text;
  v_from date;
  v_to date;
  v_payload jsonb;
BEGIN
  IF length(v_q) > 200 OR jsonb_typeof(v_filters) <> 'object' THEN
    RAISE EXCEPTION 'invalid evidence search request';
  END IF;
  IF COALESCE(v_filters->>'from', '') <> '' THEN
    v_from := (v_filters->>'from')::date;
  END IF;
  IF COALESCE(v_filters->>'to', '') <> '' THEN
    v_to := (v_filters->>'to')::date;
  END IF;
  IF v_from IS NOT NULL AND v_to IS NOT NULL AND v_from > v_to THEN
    RAISE EXCEPTION 'invalid evidence search range';
  END IF;
  v_like_pattern := '%' || replace(replace(replace(v_q, '\', '\\'), '%', '\%'), '_', '\_') || '%';
  SELECT version.dataset_version INTO v_version
  FROM cre_system.dataset_versions version
  WHERE version.dataset_version = COALESCE(
      p_dataset_version,
      (SELECT dataset_version FROM cre_system.active_manifest WHERE slot = 'dashboard')
    )
    AND version.status_code IN ('ACTIVE', 'RETIRED');
  IF v_version IS NULL THEN RAISE EXCEPTION 'dashboard dataset unavailable'; END IF;

  WITH candidate_ids AS MATERIALIZED (
    SELECT search_document.document_id
    FROM cre_news.article_search_documents search_document
    WHERE v_q <> ''
      AND char_length(v_q) <= 2
      AND search_document.dataset_version = v_version
      AND search_document.terms @> ARRAY[lower(v_q)]
    UNION ALL
    SELECT trigram_article.document_id
    FROM cre_news.articles trigram_article
    WHERE char_length(v_q) > 2
      AND trigram_article.dataset_version = v_version
      AND trigram_article.search_text ILIKE v_like_pattern ESCAPE '\'
    UNION ALL
    SELECT unfiltered_article.document_id
    FROM cre_news.articles unfiltered_article
    WHERE v_q = ''
      AND unfiltered_article.dataset_version = v_version
  ), matching AS MATERIALIZED (
    SELECT article.*,
           CASE WHEN v_q = '' THEN 0::double precision
                WHEN char_length(v_q) <= 2 THEN 1::double precision
                ELSE similarity(article.search_text, lower(v_q)) END AS score
    FROM candidate_ids candidate_id
    JOIN cre_news.articles article
      ON article.dataset_version = v_version
     AND article.document_id = candidate_id.document_id
    WHERE article.dataset_version = v_version
      AND (v_from IS NULL OR article.article_date >= v_from)
      AND (v_to IS NULL OR article.article_date <= v_to)
      AND (COALESCE(v_filters->>'publisher', '') = ''
           OR article.publisher_name = v_filters->>'publisher')
      AND (COALESCE(v_filters->>'topic', '') = '' OR EXISTS (
        SELECT 1 FROM cre_news.article_topics topic
        WHERE topic.dataset_version = article.dataset_version
          AND topic.document_id = article.document_id
          AND topic.term_code = v_filters->>'topic'
      ))
  ), candidates AS MATERIALIZED (
    SELECT * FROM matching
    ORDER BY score DESC, published_at DESC, document_id
    LIMIT v_top_k
  )
  SELECT jsonb_build_object(
    'datasetVersion', v_version,
    'query', v_q,
    'generatedAt', clock_timestamp(),
    'filters', v_filters,
    'total', (SELECT count(*) FROM matching),
    'returned', count(*),
    'truncated', (SELECT count(*) FROM matching) > count(*),
    'items', COALESCE(jsonb_agg(jsonb_build_object(
      'documentId', candidate.document_id,
      'title', candidate.title,
      'publisher', candidate.publisher_name,
      'publishedAt', candidate.published_at,
      'href', candidate.canonical_url,
      'evidenceText', candidate.evidence_text,
      'score', round(candidate.score::numeric, 6)
    ) ORDER BY candidate.score DESC, candidate.published_at DESC, candidate.document_id),
    '[]'::jsonb)
  ) INTO v_payload
  FROM candidates candidate;
  RETURN v_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.dashboard_authorize_subject(p_subject_id text)
RETURNS TABLE(authorized boolean, subject_id text, authz_version bigint, dataset_version text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system
AS $$
  SELECT COALESCE(subject.subject_id IS NOT NULL, false),
         subject.subject_id,
         COALESCE(subject.authz_version, 0),
         active.dataset_version
  FROM (SELECT 1) singleton
  LEFT JOIN cre_system.authorized_subjects subject
    ON subject.subject_id = p_subject_id
   AND subject.approved
   AND subject.revoked_at IS NULL
   AND (subject.access_expires_at IS NULL OR subject.access_expires_at > clock_timestamp())
  LEFT JOIN cre_system.active_manifest active ON active.slot = 'dashboard';
$$;

CREATE OR REPLACE FUNCTION public.dashboard_find_authorized_subject(p_email text)
RETURNS TABLE(authorized boolean, subject_id text, authz_version bigint, dataset_version text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system
AS $$
  SELECT COALESCE(subject.subject_id IS NOT NULL, false),
         subject.subject_id,
         COALESCE(subject.authz_version, 0),
         active.dataset_version
  FROM (SELECT 1) singleton
  LEFT JOIN cre_system.authorized_subjects subject
    ON subject.email_normalized = lower(btrim(COALESCE(p_email, '')))
   AND subject.approved
   AND subject.revoked_at IS NULL
   AND (subject.access_expires_at IS NULL OR subject.access_expires_at > clock_timestamp())
  LEFT JOIN cre_system.active_manifest active ON active.slot = 'dashboard';
$$;

CREATE OR REPLACE FUNCTION public.dashboard_consume_login_attempts(p_keys text[])
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system
AS $$
DECLARE
  v_now timestamptz := clock_timestamp();
  v_result jsonb;
BEGIN
  IF p_keys IS NULL OR cardinality(p_keys) NOT BETWEEN 1 AND 2
     OR EXISTS (SELECT 1 FROM unnest(p_keys) key WHERE key IS NULL OR btrim(key) = '' OR length(key) > 256)
     OR (SELECT count(DISTINCT key) FROM unnest(p_keys) key) <> cardinality(p_keys) THEN
    RAISE EXCEPTION 'login rate limiting requires one or two unique nonempty keys';
  END IF;

  DELETE FROM cre_system.login_rate_limits WHERE updated_at < v_now - interval '7 days';

  WITH requested(rate_limit_key) AS (
    SELECT DISTINCT key FROM unnest(p_keys) key
  ), consumed AS (
    INSERT INTO cre_system.login_rate_limits(
      rate_limit_key, window_started_at, attempt_count, blocked_until, updated_at
    )
    SELECT rate_limit_key, v_now, 1, NULL, v_now FROM requested
    ON CONFLICT (rate_limit_key) DO UPDATE SET
      window_started_at = CASE
        WHEN cre_system.login_rate_limits.window_started_at < v_now - interval '15 minutes'
          THEN v_now ELSE cre_system.login_rate_limits.window_started_at END,
      attempt_count = CASE
        WHEN cre_system.login_rate_limits.window_started_at < v_now - interval '15 minutes'
          THEN 1 ELSE cre_system.login_rate_limits.attempt_count + 1 END,
      blocked_until = CASE
        WHEN cre_system.login_rate_limits.blocked_until > v_now
          THEN cre_system.login_rate_limits.blocked_until
        WHEN cre_system.login_rate_limits.window_started_at < v_now - interval '15 minutes'
          THEN NULL
        WHEN cre_system.login_rate_limits.attempt_count + 1 >= 10
          THEN v_now + interval '15 minutes'
        ELSE NULL END,
      updated_at = v_now
    RETURNING rate_limit_key, attempt_count, blocked_until
  )
  SELECT jsonb_build_object(
        'blocked', COALESCE(bool_or(COALESCE(blocked_until > v_now, false)), false),
    'keys', jsonb_agg(jsonb_build_object(
      'key', rate_limit_key,
      'attemptCount', attempt_count,
      'blocked', COALESCE(blocked_until > v_now, false),
      'blockedUntil', blocked_until
    ) ORDER BY rate_limit_key)
  ) INTO v_result FROM consumed;
  RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.dashboard_clear_login_attempts(p_keys text[])
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, cre_system
AS $$
DECLARE
  v_deleted integer;
BEGIN
  IF p_keys IS NULL OR cardinality(p_keys) NOT BETWEEN 1 AND 2
     OR EXISTS (SELECT 1 FROM unnest(p_keys) key WHERE key IS NULL OR btrim(key) = '' OR length(key) > 256) THEN
    RAISE EXCEPTION 'login rate limiting requires one or two nonempty keys';
  END IF;
  DELETE FROM cre_system.login_rate_limits WHERE rate_limit_key = ANY(p_keys);
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN jsonb_build_object('cleared', v_deleted);
END;
$$;

REVOKE ALL ON FUNCTION public.dashboard_serving_manifest() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_daily_articles(date, integer, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_article_detail(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_macro_timeseries(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_permit_timeseries(text, date, date, text, text, text, text, text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_market_pulse(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_contextual_evidence_search(text, jsonb, integer, text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_authorize_subject(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_find_authorized_subject(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_consume_login_attempts(text[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dashboard_clear_login_attempts(text[]) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.dashboard_serving_manifest() TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_daily_articles(date, integer, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_article_detail(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_macro_timeseries(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_permit_timeseries(text, date, date, text, text, text, text, text)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_market_pulse(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_contextual_evidence_search(text, jsonb, integer, text)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_authorize_subject(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_find_authorized_subject(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_consume_login_attempts(text[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_clear_login_attempts(text[]) TO service_role;

INSERT INTO cre_system.schema_meta(schema_key, schema_value)
VALUES ('compact_dashboard_schema_version', '1.1.0')
ON CONFLICT (schema_key) DO UPDATE
SET schema_value = excluded.schema_value, updated_at = clock_timestamp();

NOTIFY pgrst, 'reload schema';
COMMIT;
