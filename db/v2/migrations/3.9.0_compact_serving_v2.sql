-- PostgreSQL/Supabase additive feature: compact dashboard-only serving v2.
-- Full raw snapshots, revisions, memberships, and classification history stay in local SQLite.
BEGIN;

DO $$
BEGIN
  IF (SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version') <> '3.5.0' THEN
    RAISE EXCEPTION 'compact serving v2 requires global schema_version 3.5.0';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS market_intelligence.serving_releases (
  release_id text PRIMARY KEY,
  dataset_code text NOT NULL,
  status_code text NOT NULL CHECK (status_code IN ('LOADING','READY','ACTIVE','RETIRED','FAILED')),
  source_as_of_date date NOT NULL,
  hot_window_start date,
  row_count_monthly bigint NOT NULL DEFAULT 0 CHECK (row_count_monthly >= 0),
  row_count_detail bigint NOT NULL DEFAULT 0 CHECK (row_count_detail >= 0),
  source_manifest_sha256 text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ready_at timestamptz,
  activated_at timestamptz,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(dataset_code,release_id)
);

CREATE TABLE IF NOT EXISTS market_intelligence.serving_active_release (
  dataset_code text PRIMARY KEY,
  release_id text NOT NULL REFERENCES market_intelligence.serving_releases(release_id),
  switched_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS market_intelligence.serving_v2_building_permit_monthly (
  release_id text NOT NULL REFERENCES market_intelligence.serving_releases(release_id) ON DELETE CASCADE,
  source_id text NOT NULL,
  event_month date NOT NULL,
  event_type text NOT NULL,
  district_name text NOT NULL,
  asset_type text NOT NULL,
  scope_status text NOT NULL,
  construction_action text NOT NULL,
  permit_count integer NOT NULL CHECK (permit_count >= 0),
  total_floor_area_m2 numeric NOT NULL CHECK (total_floor_area_m2 >= 0),
  missing_area_count integer NOT NULL CHECK (missing_area_count >= 0),
  invalid_area_count integer NOT NULL CHECK (invalid_area_count >= 0),
  PRIMARY KEY(release_id,source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action)
);

CREATE INDEX IF NOT EXISTS ix_serving_v2_permit_monthly_filter
  ON market_intelligence.serving_v2_building_permit_monthly
  (release_id,event_month,scope_status,asset_type,district_name);

CREATE TABLE IF NOT EXISTS market_intelligence.serving_v2_building_permit_hot_detail (
  release_id text NOT NULL REFERENCES market_intelligence.serving_releases(release_id) ON DELETE CASCADE,
  source_id text NOT NULL,
  source_record_key text NOT NULL,
  source_created_date date,
  sigungu_code text,
  bjdong_code text,
  district_name text,
  legal_dong_name text,
  parcel_address text,
  parcel_type_code text,
  main_lot_number text,
  sub_lot_number text,
  building_name text,
  construction_type text,
  main_use_code text,
  main_use_name text,
  site_area_m2 numeric,
  building_area_m2 numeric,
  total_floor_area_m2 numeric,
  household_count integer,
  unit_count integer,
  family_count integer,
  permit_date date,
  planned_start_date date,
  delayed_start_date date,
  actual_start_date date,
  use_approval_date date,
  scope_status text NOT NULL,
  asset_type text NOT NULL,
  construction_action text NOT NULL,
  confidence_score numeric NOT NULL,
  quality_flags smallint NOT NULL DEFAULT 0,
  last_seen_at timestamptz NOT NULL,
  PRIMARY KEY(release_id,source_id,source_record_key)
);

CREATE INDEX IF NOT EXISTS ix_serving_v2_permit_hot_filter
  ON market_intelligence.serving_v2_building_permit_hot_detail
  (release_id,scope_status,asset_type,district_name);
CREATE INDEX IF NOT EXISTS ix_serving_v2_permit_hot_dates
  ON market_intelligence.serving_v2_building_permit_hot_detail
  (release_id,permit_date,actual_start_date,use_approval_date);

CREATE OR REPLACE VIEW market_intelligence.v_serving_v2_building_permit_monthly AS
SELECT fact.*
FROM market_intelligence.serving_v2_building_permit_monthly fact
JOIN market_intelligence.serving_active_release active
  ON active.dataset_code='BUILDING_PERMIT'
 AND active.release_id=fact.release_id;

CREATE OR REPLACE VIEW market_intelligence.v_serving_v2_building_permit_hot_detail AS
SELECT fact.*
FROM market_intelligence.serving_v2_building_permit_hot_detail fact
JOIN market_intelligence.serving_active_release active
  ON active.dataset_code='BUILDING_PERMIT'
 AND active.release_id=fact.release_id;

INSERT INTO market_intelligence.schema_meta(schema_key,schema_value)
VALUES('serving_v2_schema_version','1.0.0')
ON CONFLICT(schema_key) DO UPDATE SET schema_value=excluded.schema_value;

COMMIT;
