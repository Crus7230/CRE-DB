-- PostgreSQL additive feature migration: source-faithful CRE building permit dataset.
-- The global schema_version remains 3.5.0 because independent analytics code pins it.
BEGIN;
DO $$ DECLARE current_version TEXT; feature_version TEXT; BEGIN
  SELECT schema_value INTO current_version FROM market_intelligence.schema_meta WHERE schema_key='schema_version';
  SELECT schema_value INTO feature_version FROM market_intelligence.schema_meta WHERE schema_key='building_permit_schema_version';
  IF current_version IS DISTINCT FROM '3.5.0' THEN
    RAISE EXCEPTION 'Expected global schema 3.5.0, found %',COALESCE(current_version,'missing');
  END IF;
  IF feature_version IS NOT NULL THEN
    RAISE EXCEPTION 'Building permit feature already installed at %',feature_version;
  END IF;
END $$;

CREATE TABLE market_intelligence.building_permit_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES market_intelligence.collection_sources(source_id) ON DELETE RESTRICT,
    snapshot_kind TEXT NOT NULL CHECK(snapshot_kind IN ('FULL','INCREMENTAL','PILOT')),
    status_code TEXT NOT NULL CHECK(status_code IN ('RUNNING','PARTIAL','COMPLETED','FAILED')),
    started_at TEXT NOT NULL,completed_at TEXT,source_as_of_date TEXT,
    source_total_count BIGINT CHECK(source_total_count IS NULL OR source_total_count>=0),
    fetched_count BIGINT NOT NULL DEFAULT 0 CHECK(fetched_count>=0),
    stored_count BIGINT NOT NULL DEFAULT 0 CHECK(stored_count>=0),
    candidate_count BIGINT NOT NULL DEFAULT 0 CHECK(candidate_count>=0),
    excluded_count BIGINT NOT NULL DEFAULT 0 CHECK(excluded_count>=0),
    request_count BIGINT NOT NULL DEFAULT 0 CHECK(request_count>=0),
    page_size BIGINT CHECK(page_size IS NULL OR page_size>0),
    last_completed_page BIGINT NOT NULL DEFAULT 0 CHECK(last_completed_page>=0),
    cursor_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(cursor_json::jsonb)='object'),
    classification_counts_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(classification_counts_json::jsonb)='object'),
    error_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(error_json::jsonb)='object'),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata_json::jsonb)='object')
);
CREATE INDEX ix_building_permit_snapshots_source_time ON market_intelligence.building_permit_snapshots(source_id,started_at DESC);

CREATE TABLE market_intelligence.building_permit_record_versions (
    record_version_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES market_intelligence.collection_sources(source_id) ON DELETE RESTRICT,
    source_record_key TEXT NOT NULL CHECK(length(trim(source_record_key))>0),
    revision_no BIGINT NOT NULL DEFAULT 1 CHECK(revision_no>0),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    raw_json TEXT NOT NULL CHECK(jsonb_typeof(raw_json::jsonb)='object'),
    source_created_date TEXT,sigungu_code TEXT,bjdong_code TEXT,district_name TEXT,legal_dong_name TEXT,
    parcel_address TEXT,road_address TEXT,parcel_type_code TEXT,main_lot_number TEXT,sub_lot_number TEXT,
    building_name TEXT,construction_type TEXT,main_use_code TEXT,main_use_name TEXT,
    site_area_m2 DOUBLE PRECISION CHECK(site_area_m2 IS NULL OR site_area_m2>=0),
    building_area_m2 DOUBLE PRECISION CHECK(building_area_m2 IS NULL OR building_area_m2>=0),
    total_floor_area_m2 DOUBLE PRECISION CHECK(total_floor_area_m2 IS NULL OR total_floor_area_m2>=0),
    household_count BIGINT CHECK(household_count IS NULL OR household_count>=0),
    unit_count BIGINT CHECK(unit_count IS NULL OR unit_count>=0),
    family_count BIGINT CHECK(family_count IS NULL OR family_count>=0),
    permit_date TEXT,planned_start_date TEXT,delayed_start_date TEXT,actual_start_date TEXT,use_approval_date TEXT,
    first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,created_at TEXT NOT NULL,
    UNIQUE(source_id,source_record_key,payload_sha256),
    UNIQUE(source_id,source_record_key,revision_no)
);
CREATE INDEX ix_building_permit_record_identity ON market_intelligence.building_permit_record_versions(source_id,source_record_key,revision_no DESC);
CREATE INDEX ix_building_permit_record_dates ON market_intelligence.building_permit_record_versions(permit_date,actual_start_date,use_approval_date);
CREATE INDEX ix_building_permit_record_location ON market_intelligence.building_permit_record_versions(district_name,legal_dong_name);

CREATE TABLE market_intelligence.building_permit_snapshot_records (
    snapshot_id TEXT NOT NULL REFERENCES market_intelligence.building_permit_snapshots(snapshot_id) ON DELETE CASCADE,
    record_version_id TEXT NOT NULL REFERENCES market_intelligence.building_permit_record_versions(record_version_id) ON DELETE RESTRICT,
    source_row_no BIGINT NOT NULL CHECK(source_row_no>0),
    PRIMARY KEY(snapshot_id,record_version_id),UNIQUE(snapshot_id,source_row_no)
);
CREATE INDEX ix_building_permit_snapshot_records_version ON market_intelligence.building_permit_snapshot_records(record_version_id,snapshot_id);

CREATE TABLE market_intelligence.building_permit_snapshot_pages (
    snapshot_id TEXT NOT NULL REFERENCES market_intelligence.building_permit_snapshots(snapshot_id) ON DELETE CASCADE,
    page_no BIGINT NOT NULL CHECK(page_no>0),start_row_no BIGINT NOT NULL CHECK(start_row_no>=0),
    fetched_count BIGINT NOT NULL CHECK(fetched_count>=0),stored_count BIGINT NOT NULL CHECK(stored_count>=0),
    excluded_count BIGINT NOT NULL CHECK(excluded_count>=0),
    classification_counts_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(classification_counts_json::jsonb)='object'),
    completed_at TEXT NOT NULL,PRIMARY KEY(snapshot_id,page_no)
);

CREATE TABLE market_intelligence.building_permit_classifications (
    classification_id TEXT PRIMARY KEY,
    record_version_id TEXT NOT NULL REFERENCES market_intelligence.building_permit_record_versions(record_version_id) ON DELETE CASCADE,
    rule_version TEXT NOT NULL,
    scope_status TEXT NOT NULL CHECK(scope_status IN ('IN_SCOPE','REVIEW_MIXED','REVIEW_DATA_CENTER','REVIEW_OTHER','REVIEW_UNKNOWN','EXCLUDED_RESIDENTIAL','EXCLUDED_NONCOMMERCIAL')),
    asset_type TEXT NOT NULL CHECK(asset_type IN ('OFFICE','LOGISTICS','DATA_CENTER','HOTEL','RETAIL','MIXED_USE','OTHER_COMMERCIAL','NONCOMMERCIAL','RESIDENTIAL','UNKNOWN')),
    construction_action TEXT NOT NULL CHECK(construction_action IN ('NEW_SUPPLY','AREA_EXPANSION','REDEVELOPMENT','USE_CONVERSION','OTHER')),
    confidence_score DOUBLE PRECISION NOT NULL CHECK(confidence_score>=0 AND confidence_score<=1),
    is_current BIGINT NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    reason_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(reason_json::jsonb)='object'),
    classified_at TEXT NOT NULL,UNIQUE(record_version_id,rule_version)
);
CREATE UNIQUE INDEX ux_building_permit_classification_current ON market_intelligence.building_permit_classifications(record_version_id) WHERE is_current=1;
CREATE INDEX ix_building_permit_classification_scope ON market_intelligence.building_permit_classifications(scope_status,asset_type,construction_action);

CREATE TABLE market_intelligence.building_permit_exclusion_summary (
    snapshot_id TEXT NOT NULL REFERENCES market_intelligence.building_permit_snapshots(snapshot_id) ON DELETE CASCADE,
    district_name TEXT NOT NULL DEFAULT '',main_use_name TEXT NOT NULL DEFAULT '',
    scope_status TEXT NOT NULL CHECK(scope_status IN ('EXCLUDED_RESIDENTIAL','EXCLUDED_NONCOMMERCIAL')),
    permit_count BIGINT NOT NULL CHECK(permit_count>=0),
    total_floor_area_m2 DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK(total_floor_area_m2>=0),
    PRIMARY KEY(snapshot_id,district_name,main_use_name,scope_status)
);

CREATE VIEW market_intelligence.v_latest_building_permit_records AS
WITH ranked AS (
  SELECT rv.*,s.snapshot_id,s.completed_at AS snapshot_completed_at,
         ROW_NUMBER() OVER (PARTITION BY rv.source_id,rv.source_record_key ORDER BY s.completed_at DESC,rv.revision_no DESC,rv.record_version_id DESC) AS rn
  FROM market_intelligence.building_permit_record_versions rv
  JOIN market_intelligence.building_permit_snapshot_records sr ON sr.record_version_id=rv.record_version_id
  JOIN market_intelligence.building_permit_snapshots s ON s.snapshot_id=sr.snapshot_id
  WHERE s.status_code='COMPLETED'
) SELECT * FROM ranked WHERE rn=1;

CREATE VIEW market_intelligence.v_current_cre_building_permit_records AS
SELECT r.*,c.rule_version,c.scope_status,c.asset_type,c.construction_action,c.confidence_score,c.reason_json
FROM market_intelligence.v_latest_building_permit_records r
JOIN market_intelligence.building_permit_classifications c ON c.record_version_id=r.record_version_id AND c.is_current=1
WHERE c.scope_status IN ('IN_SCOPE','REVIEW_MIXED','REVIEW_DATA_CENTER','REVIEW_OTHER','REVIEW_UNKNOWN');

CREATE VIEW market_intelligence.v_cre_building_permit_events AS
SELECT source_id,source_record_key,record_version_id,district_name,legal_dong_name,building_name,main_use_name,asset_type,scope_status,construction_action,
       'PERMIT'::TEXT AS event_type,permit_date AS event_date,substring(permit_date from 1 for 7) AS event_month,total_floor_area_m2
FROM market_intelligence.v_current_cre_building_permit_records WHERE permit_date IS NOT NULL
UNION ALL
SELECT source_id,source_record_key,record_version_id,district_name,legal_dong_name,building_name,main_use_name,asset_type,scope_status,construction_action,
       'ACTUAL_START',actual_start_date,substring(actual_start_date from 1 for 7),total_floor_area_m2
FROM market_intelligence.v_current_cre_building_permit_records WHERE actual_start_date IS NOT NULL
UNION ALL
SELECT source_id,source_record_key,record_version_id,district_name,legal_dong_name,building_name,main_use_name,asset_type,scope_status,construction_action,
       'USE_APPROVAL',use_approval_date,substring(use_approval_date from 1 for 7),total_floor_area_m2
FROM market_intelligence.v_current_cre_building_permit_records WHERE use_approval_date IS NOT NULL;

CREATE VIEW market_intelligence.v_cre_building_permit_monthly AS
SELECT event_month,event_type,district_name,asset_type,scope_status,construction_action,
       COUNT(*) AS permit_count,COALESCE(SUM(total_floor_area_m2),0) AS total_floor_area_m2,
       SUM(CASE WHEN total_floor_area_m2 IS NULL THEN 1 ELSE 0 END) AS missing_area_count
FROM market_intelligence.v_cre_building_permit_events
GROUP BY event_month,event_type,district_name,asset_type,scope_status,construction_action;

INSERT INTO market_intelligence.schema_meta(schema_key,schema_value,updated_at)
VALUES('building_permit_schema_version','1.0.0',to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'));
COMMIT;
