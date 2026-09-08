-- PostgreSQL feature 1.0.3: quarantine implausible floor-area values from area totals.
BEGIN;
DO $$ DECLARE feature_version TEXT; BEGIN
  SELECT schema_value INTO feature_version FROM market_intelligence.schema_meta
  WHERE schema_key='building_permit_schema_version';
  IF feature_version IS DISTINCT FROM '1.0.2' THEN
    RAISE EXCEPTION 'expected building permit feature 1.0.2, found %',feature_version;
  END IF;
END $$;
DROP VIEW market_intelligence.v_cre_building_permit_monthly;
CREATE VIEW market_intelligence.v_cre_building_permit_monthly AS
SELECT source_id,substr(event_date,1,7) AS event_month,event_type,
       COALESCE(district_name,'UNKNOWN') AS district_name,asset_type,scope_status,construction_action,
       COUNT(*)::bigint AS permit_count,
       SUM(CASE WHEN total_floor_area_m2 BETWEEN 0 AND 2000000 THEN total_floor_area_m2 ELSE 0 END) AS total_floor_area_m2,
       SUM(CASE WHEN total_floor_area_m2 IS NULL THEN 1 ELSE 0 END)::bigint AS missing_area_count,
       SUM(CASE WHEN total_floor_area_m2<0 OR total_floor_area_m2>2000000 THEN 1 ELSE 0 END)::bigint AS invalid_area_count
FROM market_intelligence.v_cre_building_permit_events
GROUP BY source_id,substr(event_date,1,7),event_type,COALESCE(district_name,'UNKNOWN'),
         asset_type,scope_status,construction_action;
CREATE VIEW market_intelligence.v_building_permit_area_quality AS
WITH classified AS (
 SELECT source_id,total_floor_area_m2,
   CASE WHEN total_floor_area_m2 IS NULL THEN 'MISSING'
        WHEN total_floor_area_m2<0 THEN 'NEGATIVE'
        WHEN total_floor_area_m2>2000000 THEN 'ABOVE_2M'
        ELSE 'VALID' END AS quality_status
 FROM market_intelligence.v_current_cre_building_permit_records
)
SELECT source_id,quality_status,COUNT(*)::bigint AS record_count,
       MIN(total_floor_area_m2) AS min_area_m2,MAX(total_floor_area_m2) AS max_area_m2,
       SUM(COALESCE(total_floor_area_m2,0)) AS raw_area_m2
FROM classified GROUP BY source_id,quality_status;
UPDATE market_intelligence.schema_meta SET schema_value='1.0.3',updated_at=NOW()
WHERE schema_key='building_permit_schema_version';
COMMIT;
