-- SQLite feature 1.0.2: quarantine impossible actual event dates from market series.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _bp102_guard(value TEXT NOT NULL CHECK(value='1.0.1'));
INSERT INTO _bp102_guard(value) SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version';
DROP VIEW v_cre_building_permit_monthly;
DROP VIEW v_cre_building_permit_events;
CREATE VIEW v_cre_building_permit_events AS
SELECT source_id,source_record_key,record_version_id,'PERMIT' AS event_type,permit_date AS event_date,
       district_name,asset_type,scope_status,construction_action,total_floor_area_m2
FROM v_current_cre_building_permit_records
WHERE permit_date BETWEEN '1900-01-01' AND date('now')
UNION ALL
SELECT source_id,source_record_key,record_version_id,'ACTUAL_START',actual_start_date,
       district_name,asset_type,scope_status,construction_action,total_floor_area_m2
FROM v_current_cre_building_permit_records
WHERE actual_start_date BETWEEN '1900-01-01' AND date('now')
UNION ALL
SELECT source_id,source_record_key,record_version_id,'USE_APPROVAL',use_approval_date,
       district_name,asset_type,scope_status,construction_action,total_floor_area_m2
FROM v_current_cre_building_permit_records
WHERE use_approval_date BETWEEN '1900-01-01' AND date('now');
CREATE VIEW v_cre_building_permit_monthly AS
SELECT source_id,substr(event_date,1,7) AS event_month,event_type,
       COALESCE(district_name,'UNKNOWN') AS district_name,asset_type,scope_status,construction_action,
       COUNT(*) AS permit_count,SUM(COALESCE(total_floor_area_m2,0)) AS total_floor_area_m2,
       SUM(CASE WHEN total_floor_area_m2 IS NULL THEN 1 ELSE 0 END) AS missing_area_count
FROM v_cre_building_permit_events
GROUP BY source_id,substr(event_date,1,7),event_type,COALESCE(district_name,'UNKNOWN'),
         asset_type,scope_status,construction_action;
CREATE VIEW v_building_permit_event_date_quality AS
WITH dates AS (
 SELECT source_id,'PERMIT' AS event_type,permit_date AS event_date FROM v_current_cre_building_permit_records
 UNION ALL SELECT source_id,'ACTUAL_START',actual_start_date FROM v_current_cre_building_permit_records
 UNION ALL SELECT source_id,'USE_APPROVAL',use_approval_date FROM v_current_cre_building_permit_records
), classified AS (
 SELECT source_id,event_type,event_date,
   CASE WHEN event_date IS NULL THEN 'MISSING'
        WHEN event_date<'1900-01-01' THEN 'BEFORE_1900'
        WHEN event_date>date('now') THEN 'FUTURE'
        ELSE 'VALID' END AS quality_status
 FROM dates
)
SELECT source_id,event_type,quality_status,COUNT(*) AS record_count,
       MIN(event_date) AS min_event_date,MAX(event_date) AS max_event_date
FROM classified GROUP BY source_id,event_type,quality_status;
UPDATE schema_meta SET schema_value='1.0.2',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE schema_key='building_permit_schema_version';
DROP TABLE _bp102_guard;
COMMIT;
