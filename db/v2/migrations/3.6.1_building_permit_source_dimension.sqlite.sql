-- SQLite building-permit feature 1.0.1: prevent cross-source double counting.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _bp101_guard(value TEXT NOT NULL CHECK(value='1.0.0'));
INSERT INTO _bp101_guard(value)
SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version';
DROP VIEW v_cre_building_permit_monthly;
CREATE VIEW v_cre_building_permit_monthly AS
SELECT source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action,
       COUNT(*) AS permit_count,
       SUM(CASE WHEN total_floor_area_m2 IS NOT NULL THEN total_floor_area_m2 ELSE 0 END) AS total_floor_area_m2,
       SUM(CASE WHEN total_floor_area_m2 IS NULL THEN 1 ELSE 0 END) AS missing_area_count
FROM v_cre_building_permit_events
GROUP BY source_id,event_month,event_type,district_name,asset_type,scope_status,construction_action;
UPDATE schema_meta SET schema_value='1.0.1',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE schema_key='building_permit_schema_version';
DROP TABLE _bp101_guard;
COMMIT;
