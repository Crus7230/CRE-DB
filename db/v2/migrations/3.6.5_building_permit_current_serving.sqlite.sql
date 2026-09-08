-- SQLite feature 1.0.5: normalized current-detail serving mart.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _bp105_guard(value TEXT NOT NULL CHECK(value='1.0.4'));
INSERT INTO _bp105_guard(value) SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version';
CREATE TABLE building_permit_current_serving (
    source_id TEXT NOT NULL REFERENCES collection_sources(source_id),
    source_snapshot_id TEXT NOT NULL REFERENCES building_permit_snapshots(snapshot_id),
    record_version_id TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    source_created_date TEXT,
    sigungu_code TEXT,bjdong_code TEXT,district_name TEXT,legal_dong_name TEXT,
    parcel_address TEXT,road_address TEXT,parcel_type_code TEXT,main_lot_number TEXT,sub_lot_number TEXT,
    building_name TEXT,construction_type TEXT,main_use_code TEXT,main_use_name TEXT,
    site_area_m2 REAL,building_area_m2 REAL,total_floor_area_m2 REAL,
    household_count INTEGER,unit_count INTEGER,family_count INTEGER,
    permit_date TEXT,planned_start_date TEXT,delayed_start_date TEXT,actual_start_date TEXT,use_approval_date TEXT,
    first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,
    rule_version TEXT NOT NULL,scope_status TEXT NOT NULL,asset_type TEXT NOT NULL,
    construction_action TEXT NOT NULL,confidence_score REAL NOT NULL,
    permit_date_quality TEXT NOT NULL,actual_start_date_quality TEXT NOT NULL,
    use_approval_date_quality TEXT NOT NULL,area_quality_status TEXT NOT NULL,
    published_at TEXT NOT NULL,
    PRIMARY KEY(source_id,source_record_key)
);
CREATE INDEX ix_bp_current_serving_asset ON building_permit_current_serving(asset_type,scope_status,district_name);
CREATE INDEX ix_bp_current_serving_permit_date ON building_permit_current_serving(permit_date,source_id);
CREATE INDEX ix_bp_current_serving_address ON building_permit_current_serving(district_name,legal_dong_name);
UPDATE schema_meta SET schema_value='1.0.5',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE schema_key='building_permit_schema_version';
DROP TABLE _bp105_guard;
COMMIT;
