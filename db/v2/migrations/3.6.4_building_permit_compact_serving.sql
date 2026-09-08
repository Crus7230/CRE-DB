-- PostgreSQL feature 1.0.4: compact monthly serving table.
BEGIN;
DO $$ DECLARE feature_version TEXT; BEGIN
  SELECT schema_value INTO feature_version FROM market_intelligence.schema_meta
  WHERE schema_key='building_permit_schema_version';
  IF feature_version IS DISTINCT FROM '1.0.3' THEN
    RAISE EXCEPTION 'expected building permit feature 1.0.3, found %',feature_version;
  END IF;
END $$;
CREATE TABLE market_intelligence.building_permit_monthly_serving (
    source_id TEXT NOT NULL REFERENCES market_intelligence.collection_sources(source_id),
    source_snapshot_id TEXT NOT NULL REFERENCES market_intelligence.building_permit_snapshots(snapshot_id),
    event_month TEXT NOT NULL CHECK(event_month ~ '^[0-9]{4}-[0-9]{2}$'),
    event_type TEXT NOT NULL CHECK(event_type IN ('PERMIT','ACTUAL_START','USE_APPROVAL')),
    district_name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    scope_status TEXT NOT NULL,
    construction_action TEXT NOT NULL,
    permit_count BIGINT NOT NULL CHECK(permit_count>=0),
    total_floor_area_m2 NUMERIC NOT NULL CHECK(total_floor_area_m2>=0),
    missing_area_count BIGINT NOT NULL CHECK(missing_area_count>=0),
    invalid_area_count BIGINT NOT NULL CHECK(invalid_area_count>=0),
    generated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action)
);
CREATE INDEX ix_building_permit_monthly_serving_snapshot
ON market_intelligence.building_permit_monthly_serving(source_snapshot_id,event_month,event_type);
UPDATE market_intelligence.schema_meta SET schema_value='1.0.4',updated_at=NOW()
WHERE schema_key='building_permit_schema_version';
COMMIT;
