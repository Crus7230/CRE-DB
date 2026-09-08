-- PostgreSQL feature 1.0.5: normalized current-detail serving mart.
BEGIN;
DO $$ DECLARE feature_version TEXT; BEGIN
 SELECT schema_value INTO feature_version FROM market_intelligence.schema_meta WHERE schema_key='building_permit_schema_version';
 IF feature_version IS DISTINCT FROM '1.0.4' THEN RAISE EXCEPTION 'expected building permit feature 1.0.4, found %',feature_version; END IF;
END $$;
CREATE TABLE market_intelligence.building_permit_current_serving (
    source_id TEXT NOT NULL REFERENCES market_intelligence.collection_sources(source_id),
    source_snapshot_id TEXT NOT NULL REFERENCES market_intelligence.building_permit_snapshots(snapshot_id),
    record_version_id TEXT NOT NULL,source_record_key TEXT NOT NULL,revision_no INTEGER NOT NULL,
    source_created_date TEXT,sigungu_code TEXT,bjdong_code TEXT,district_name TEXT,legal_dong_name TEXT,
    parcel_address TEXT,road_address TEXT,parcel_type_code TEXT,main_lot_number TEXT,sub_lot_number TEXT,
    building_name TEXT,construction_type TEXT,main_use_code TEXT,main_use_name TEXT,
    site_area_m2 NUMERIC,building_area_m2 NUMERIC,total_floor_area_m2 NUMERIC,
    household_count INTEGER,unit_count INTEGER,family_count INTEGER,
    permit_date TEXT,planned_start_date TEXT,delayed_start_date TEXT,actual_start_date TEXT,use_approval_date TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,last_seen_at TIMESTAMPTZ NOT NULL,
    rule_version TEXT NOT NULL,scope_status TEXT NOT NULL,asset_type TEXT NOT NULL,
    construction_action TEXT NOT NULL,confidence_score NUMERIC NOT NULL,
    permit_date_quality TEXT NOT NULL,actual_start_date_quality TEXT NOT NULL,
    use_approval_date_quality TEXT NOT NULL,area_quality_status TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(source_id,source_record_key)
);
CREATE INDEX ix_bp_current_serving_asset ON market_intelligence.building_permit_current_serving(asset_type,scope_status,district_name);
CREATE INDEX ix_bp_current_serving_permit_date ON market_intelligence.building_permit_current_serving(permit_date,source_id);
CREATE INDEX ix_bp_current_serving_address ON market_intelligence.building_permit_current_serving(district_name,legal_dong_name);
UPDATE market_intelligence.schema_meta SET schema_value='1.0.5',updated_at=NOW() WHERE schema_key='building_permit_schema_version';
COMMIT;
