-- PostgreSQL feature 1.0.2: quarantine impossible actual event dates from market series.
BEGIN;
DO $$ DECLARE feature_version TEXT; BEGIN
  SELECT schema_value INTO feature_version FROM market_intelligence.schema_meta
  WHERE schema_key='building_permit_schema_version';
  IF feature_version IS DISTINCT FROM '1.0.1' THEN
    RAISE EXCEPTION 'expected building permit feature 1.0.1, found %',feature_version;
  END IF;
END $$;
DROP VIEW market_intelligence.v_cre_building_permit_monthly;
DROP VIEW market_intelligence.v_cre_building_permit_events;
CREATE VIEW market_intelligence.v_cre_building_permit_events AS
SELECT source_id,source_record_key,record_version_id,'PERMIT'::text AS event_type,permit_date AS event_date,
       district_name,asset_type,scope_status,construction_action,total_floor_area_m2
FROM market_intelligence.v_current_cre_building_permit_records
WHERE permit_date BETWEEN '1900-01-01' AND to_char(CURRENT_DATE,'YYYY-MM-DD')
UNION ALL
SELECT source_id,source_record_key,record_version_id,'ACTUAL_START'::text,actual_start_date,
       district_name,asset_type,scope_status,construction_action,total_floor_area_m2
FROM market_intelligence.v_current_cre_building_permit_records
WHERE actual_start_date BETWEEN '1900-01-01' AND to_char(CURRENT_DATE,'YYYY-MM-DD')
UNION ALL
SELECT source_id,source_record_key,record_version_id,'USE_APPROVAL'::text,use_approval_date,
       district_name,asset_type,scope_status,construction_action,total_floor_area_m2
FROM market_intelligence.v_current_cre_building_permit_records
WHERE use_approval_date BETWEEN '1900-01-01' AND to_char(CURRENT_DATE,'YYYY-MM-DD');
CREATE VIEW market_intelligence.v_cre_building_permit_monthly AS
SELECT source_id,substr(event_date,1,7) AS event_month,event_type,
       COALESCE(district_name,'UNKNOWN') AS district_name,asset_type,scope_status,construction_action,
       COUNT(*)::bigint AS permit_count,SUM(COALESCE(total_floor_area_m2,0)) AS total_floor_area_m2,
       SUM(CASE WHEN total_floor_area_m2 IS NULL THEN 1 ELSE 0 END)::bigint AS missing_area_count
FROM market_intelligence.v_cre_building_permit_events
GROUP BY source_id,substr(event_date,1,7),event_type,COALESCE(district_name,'UNKNOWN'),
         asset_type,scope_status,construction_action;
CREATE VIEW market_intelligence.v_building_permit_event_date_quality AS
WITH dates AS (
 SELECT source_id,'PERMIT'::text AS event_type,permit_date AS event_date FROM market_intelligence.v_current_cre_building_permit_records
 UNION ALL SELECT source_id,'ACTUAL_START'::text,actual_start_date FROM market_intelligence.v_current_cre_building_permit_records
 UNION ALL SELECT source_id,'USE_APPROVAL'::text,use_approval_date FROM market_intelligence.v_current_cre_building_permit_records
), classified AS (
 SELECT source_id,event_type,event_date,
   CASE WHEN event_date IS NULL THEN 'MISSING'
        WHEN event_date<'1900-01-01' THEN 'BEFORE_1900'
        WHEN event_date>to_char(CURRENT_DATE,'YYYY-MM-DD') THEN 'FUTURE'
        ELSE 'VALID' END AS quality_status
 FROM dates
)
SELECT source_id,event_type,quality_status,COUNT(*)::bigint AS record_count,
       MIN(event_date) AS min_event_date,MAX(event_date) AS max_event_date
FROM classified GROUP BY source_id,event_type,quality_status;
UPDATE market_intelligence.schema_meta SET schema_value='1.0.2',updated_at=NOW()
WHERE schema_key='building_permit_schema_version';
COMMIT;
