-- PostgreSQL building-permit feature 1.0.1: prevent cross-source double counting.
BEGIN;
DO $$ DECLARE feature_version TEXT; BEGIN
  SELECT schema_value INTO feature_version FROM market_intelligence.schema_meta WHERE schema_key='building_permit_schema_version';
  IF feature_version IS DISTINCT FROM '1.0.0' THEN
    RAISE EXCEPTION 'Expected building permit feature 1.0.0, found %',COALESCE(feature_version,'missing');
  END IF;
END $$;
DROP VIEW market_intelligence.v_cre_building_permit_monthly;
CREATE VIEW market_intelligence.v_cre_building_permit_monthly AS
SELECT source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action,
       COUNT(*) AS permit_count,COALESCE(SUM(total_floor_area_m2),0) AS total_floor_area_m2,
       SUM(CASE WHEN total_floor_area_m2 IS NULL THEN 1 ELSE 0 END) AS missing_area_count
FROM market_intelligence.v_cre_building_permit_events
GROUP BY source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action;
UPDATE market_intelligence.schema_meta SET schema_value='1.0.1',
       updated_at=to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
WHERE schema_key='building_permit_schema_version';
COMMIT;
