-- Financial macro feature 1.0.0: official-rate sources and compact monthly serving.
BEGIN IMMEDIATE;

INSERT INTO regions(region_id,region_type,canonical_name,country_code,metadata_json)
VALUES('reg_us','COUNTRY','미국','US','{"iso2":"US"}')
ON CONFLICT(region_id) DO UPDATE SET canonical_name=excluded.canonical_name,country_code=excluded.country_code;

INSERT INTO collection_sources(source_id,source_code,source_name,source_kind,base_url,authority_tier,collection_policy,policy_checked_at,config_json,is_active)
VALUES
 ('src_ny_fed','NY_FED_MARKETS','뉴욕연방준비은행 Markets API','OFFICIAL_API','https://markets.newyorkfed.org/api',1,'API_ALLOWED','2026-09-02','{"domain":"financial_markets"}',1),
 ('src_us_treasury','US_TREASURY_YIELD_CURVE','미국 재무부 Daily Treasury Par Yield Curve Rates','OFFICIAL_API','https://home.treasury.gov/resource-center/data-chart-center/interest-rates',1,'API_ALLOWED','2026-09-02','{"domain":"financial_markets"}',1)
ON CONFLICT(source_id) DO UPDATE SET source_name=excluded.source_name,base_url=excluded.base_url,policy_checked_at=excluded.policy_checked_at,is_active=1;

CREATE VIEW IF NOT EXISTS v_latest_macro_observations AS
WITH ranked AS (
 SELECT o.*,ROW_NUMBER() OVER(
   PARTITION BY o.macro_series_id,o.period_start,o.period_end
   ORDER BY o.revision_no DESC,o.vintage_at DESC,o.collected_at DESC,o.macro_observation_id DESC
 ) AS rn
 FROM macro_observations o
)
SELECT * FROM ranked WHERE rn=1;

CREATE VIEW IF NOT EXISTS v_financial_macro_monthly AS
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
  AND o.observation_status NOT IN ('MISSING','SUPPRESSED','WITHDRAWN')
  AND o.numeric_value IS NOT NULL
GROUP BY s.series_code,s.series_name_ko,s.source_id,s.region_id,substr(o.period_start,1,7),s.frequency_code,s.unit_code;

CREATE TABLE IF NOT EXISTS financial_macro_monthly_serving(
 series_code TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES collection_sources(source_id),
 region_id TEXT REFERENCES regions(region_id),
 observation_month TEXT NOT NULL CHECK(observation_month GLOB '[12][0-9][0-9][0-9]-[01][0-9]'),
 numeric_value REAL NOT NULL,
 observation_count INTEGER NOT NULL CHECK(observation_count>0),
 aggregation_code TEXT NOT NULL CHECK(aggregation_code IN ('PROVIDER_MONTHLY','CALENDAR_MONTH_AVERAGE','DERIVED_MONTHLY')),
 unit_code TEXT NOT NULL REFERENCES units(unit_code),
 source_vintage_at TEXT NOT NULL,
 published_at TEXT NOT NULL,
 PRIMARY KEY(series_code,observation_month)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_financial_macro_monthly_source_month ON financial_macro_monthly_serving(source_id,observation_month DESC);
CREATE INDEX IF NOT EXISTS ix_financial_macro_monthly_region_month ON financial_macro_monthly_serving(region_id,observation_month DESC);

INSERT INTO schema_meta(schema_key,schema_value,updated_at)
VALUES('financial_macro_schema_version','1.0.0',strftime('%Y-%m-%dT%H:%M:%fZ','now'))
ON CONFLICT(schema_key) DO UPDATE SET schema_value=excluded.schema_value,updated_at=excluded.updated_at;
COMMIT;
