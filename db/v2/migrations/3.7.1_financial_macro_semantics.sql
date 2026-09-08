-- PostgreSQL financial macro feature 1.0.1: policy target-range semantic boundary.
BEGIN;
DO $$ DECLARE v TEXT; BEGIN
 SELECT schema_value INTO v FROM market_intelligence.schema_meta WHERE schema_key='financial_macro_schema_version';
 IF v IS DISTINCT FROM '1.0.0' THEN RAISE EXCEPTION 'financial macro feature 1.0.0 required, found %',v; END IF;
END $$;

UPDATE market_intelligence.macro_series
SET valid_from='2008-12-16',
    definition_text='뉴욕연은 EFFR 응답의 연방기금 목표범위 하단(목표범위 제도 이후)',
    metadata_json='{"aggregation":"CALENDAR_MONTH_AVERAGE","domain":"FINANCIAL_MARKETS","nativeId":"NYFED/EFFR/targetRateFrom","semanticBoundary":"2008-12-16 target-range regime"}'
WHERE series_code='US_FED_TARGET_LOWER';

CREATE OR REPLACE VIEW market_intelligence.v_financial_macro_monthly AS
SELECT s.series_code,s.series_name_ko,s.source_id,s.region_id,
       substr(o.period_start,1,7) AS observation_month,
       CASE WHEN s.frequency_code='MONTHLY' THEN max(o.numeric_value)
            ELSE avg(o.numeric_value) END AS numeric_value,
       count(o.numeric_value) AS observation_count,
       CASE WHEN s.frequency_code='MONTHLY' THEN 'PROVIDER_MONTHLY'
            ELSE 'CALENDAR_MONTH_AVERAGE' END AS aggregation_code,
       s.unit_code,max(o.vintage_at) AS source_vintage_at
FROM market_intelligence.v_latest_macro_observations o
JOIN market_intelligence.macro_series s ON s.macro_series_id=o.macro_series_id
WHERE s.is_active=1
  AND (s.metadata_json::jsonb ->> 'domain')='FINANCIAL_MARKETS'
  AND (s.valid_from IS NULL OR o.period_start>=s.valid_from)
  AND (s.valid_to IS NULL OR o.period_end<=s.valid_to)
  AND o.observation_status NOT IN ('MISSING','SUPPRESSED','WITHDRAWN')
  AND o.numeric_value IS NOT NULL
GROUP BY s.series_code,s.series_name_ko,s.source_id,s.region_id,substr(o.period_start,1,7),s.frequency_code,s.unit_code;

UPDATE market_intelligence.schema_meta
SET schema_value='1.0.1',updated_at=to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
WHERE schema_key='financial_macro_schema_version';
COMMIT;
