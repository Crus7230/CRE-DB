-- Financial macro feature 1.0.1: policy target-range semantic boundary.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _fm101_guard(value TEXT NOT NULL CHECK(value='1.0.0'));
INSERT INTO _fm101_guard(value) SELECT schema_value FROM schema_meta WHERE schema_key='financial_macro_schema_version';
DROP TABLE _fm101_guard;

UPDATE macro_series
SET valid_from='2008-12-16',
    definition_text='뉴욕연은 EFFR 응답의 연방기금 목표범위 하단(목표범위 제도 이후)',
    metadata_json='{"aggregation":"CALENDAR_MONTH_AVERAGE","domain":"FINANCIAL_MARKETS","nativeId":"NYFED/EFFR/targetRateFrom","semanticBoundary":"2008-12-16 target-range regime"}'
WHERE series_code='US_FED_TARGET_LOWER';

DROP VIEW v_financial_macro_monthly;
CREATE VIEW v_financial_macro_monthly AS
SELECT s.series_code,s.series_name_ko,s.source_id,s.region_id,
       substr(o.period_start,1,7) AS observation_month,
       CASE WHEN s.frequency_code='MONTHLY' THEN max(o.numeric_value)
            ELSE avg(o.numeric_value) END AS numeric_value,
       count(o.numeric_value) AS observation_count,
       CASE WHEN s.frequency_code='MONTHLY' THEN 'PROVIDER_MONTHLY'
            ELSE 'CALENDAR_MONTH_AVERAGE' END AS aggregation_code,
       s.unit_code,max(o.vintage_at) AS source_vintage_at
FROM v_latest_macro_observations o
JOIN macro_series s ON s.macro_series_id=o.macro_series_id
WHERE s.is_active=1
  AND json_extract(s.metadata_json,'$.domain')='FINANCIAL_MARKETS'
  AND (s.valid_from IS NULL OR o.period_start>=s.valid_from)
  AND (s.valid_to IS NULL OR o.period_end<=s.valid_to)
  AND o.observation_status NOT IN ('MISSING','SUPPRESSED','WITHDRAWN')
  AND o.numeric_value IS NOT NULL
GROUP BY s.series_code,s.series_name_ko,s.source_id,s.region_id,substr(o.period_start,1,7),s.frequency_code,s.unit_code;

UPDATE schema_meta SET schema_value='1.0.1',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE schema_key='financial_macro_schema_version';
COMMIT;
