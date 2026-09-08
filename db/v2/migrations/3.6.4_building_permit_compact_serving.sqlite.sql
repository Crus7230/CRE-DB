-- SQLite feature 1.0.4: compact monthly serving table for Supabase publication parity.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _bp104_guard(value TEXT NOT NULL CHECK(value='1.0.3'));
INSERT INTO _bp104_guard(value) SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version';
CREATE TABLE building_permit_monthly_serving (
    source_id TEXT NOT NULL REFERENCES collection_sources(source_id),
    source_snapshot_id TEXT NOT NULL REFERENCES building_permit_snapshots(snapshot_id),
    event_month TEXT NOT NULL CHECK(event_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    event_type TEXT NOT NULL CHECK(event_type IN ('PERMIT','ACTUAL_START','USE_APPROVAL')),
    district_name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    scope_status TEXT NOT NULL,
    construction_action TEXT NOT NULL,
    permit_count INTEGER NOT NULL CHECK(permit_count>=0),
    total_floor_area_m2 REAL NOT NULL CHECK(total_floor_area_m2>=0),
    missing_area_count INTEGER NOT NULL CHECK(missing_area_count>=0),
    invalid_area_count INTEGER NOT NULL CHECK(invalid_area_count>=0),
    generated_at TEXT NOT NULL,
    PRIMARY KEY(source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action)
);
CREATE INDEX ix_building_permit_monthly_serving_snapshot
ON building_permit_monthly_serving(source_snapshot_id,event_month,event_type);
UPDATE schema_meta SET schema_value='1.0.4',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE schema_key='building_permit_schema_version';
DROP TABLE _bp104_guard;
COMMIT;
