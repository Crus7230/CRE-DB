import { normalizeMacroTimeseries } from "@/lib/macro-timeseries-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

const EXPECTED_SERIES_CODES = new Set([
  "BOK_BASE_RATE_MONTHLY", "KR_CD_91D", "KR_GOVT_BOND_3Y", "KR_GOVT_BOND_10Y", "KR_CORP_BOND_AA_MINUS_3Y",
  "US_FED_TARGET_LOWER", "US_FED_TARGET_UPPER", "US_EFFR", "US_SOFR",
  "US_TREASURY_2Y", "US_TREASURY_10Y", "US_TREASURY_30Y", "US_TREASURY_10Y_MINUS_2Y",
]);

const QUERY = `WITH registry(series_code,group_code,display_order) AS (
  VALUES
    ('BOK_BASE_RATE_MONTHLY','KOREA',10),
    ('KR_CD_91D','KOREA',20),
    ('KR_GOVT_BOND_3Y','KOREA',30),
    ('KR_GOVT_BOND_10Y','KOREA',40),
    ('KR_CORP_BOND_AA_MINUS_3Y','KOREA',50),
    ('US_FED_TARGET_LOWER','US_POLICY',60),
    ('US_FED_TARGET_UPPER','US_POLICY',70),
    ('US_EFFR','US_POLICY',80),
    ('US_SOFR','US_POLICY',90),
    ('US_TREASURY_2Y','US_TREASURY',100),
    ('US_TREASURY_10Y','US_TREASURY',110),
    ('US_TREASURY_30Y','US_TREASURY',120),
    ('US_TREASURY_10Y_MINUS_2Y','US_TREASURY',130)
), bounds AS (
  SELECT min(observation_month) AS available_from,max(observation_month) AS available_through,
         min(max(observation_month),strftime('%Y-%m',date('now','+9 hours','start of month','-1 month'))) AS complete_through
  FROM financial_macro_monthly_serving f
  JOIN registry r USING(series_code)
), series_rows AS (
  SELECT r.display_order,r.series_code,r.group_code,s.series_name_ko,s.valid_from,
         cs.source_name,f.unit_code,f.source_vintage_at,f.observation_month,
         f.numeric_value,f.observation_count,b.complete_through
  FROM registry r
  JOIN financial_macro_monthly_serving f USING(series_code)
  JOIN macro_series s USING(series_code)
  JOIN collection_sources cs ON cs.source_id=f.source_id
  CROSS JOIN bounds b
), series_headers AS (
  SELECT display_order,series_code,group_code,series_name_ko,valid_from,source_name,unit_code,
         max(source_vintage_at) AS source_vintage_at
  FROM series_rows
  GROUP BY series_code,group_code,display_order,series_name_ko,valid_from,source_name,unit_code
), series_payload AS (
  SELECT h.display_order,h.series_code,json_object(
    'code',h.series_code,
    'name',h.series_name_ko,
    'group',h.group_code,
    'source',h.source_name,
    'unit',h.unit_code,
    'validFrom',h.valid_from,
    'sourceVintageAt',h.source_vintage_at,
    'points',json(COALESCE((
      SELECT json_group_array(json_object(
        'month',point.observation_month,
        'value',CAST(point.numeric_value AS REAL),
        'observationCount',point.observation_count,
        'partial',json(CASE WHEN point.observation_month>point.complete_through THEN 'true' ELSE 'false' END)
      ))
      FROM (
        SELECT * FROM series_rows point
        WHERE point.series_code=h.series_code
          AND point.group_code=h.group_code
          AND point.display_order=h.display_order
          AND point.series_name_ko=h.series_name_ko
          AND point.valid_from IS h.valid_from
          AND point.source_name=h.source_name
          AND point.unit_code=h.unit_code
        ORDER BY point.observation_month,point.source_vintage_at,point.numeric_value,point.observation_count
      ) point
    ),'[]'))
  ) AS series
  FROM series_headers h
)
SELECT json_object(
  'generatedAt',strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  'availableFrom',b.available_from,
  'availableThrough',b.available_through,
  'completeThrough',b.complete_through,
  'series',json(COALESCE((
    SELECT json_group_array(json(ordered_series.series))
    FROM (
      SELECT * FROM series_payload ordered_series
      ORDER BY ordered_series.display_order,ordered_series.series_code
    ) ordered_series
  ),'[]'))
) AS payload
FROM bounds b`;

export function normalizeCanonicalMacroTimeseries(value: unknown) {
  const normalized = normalizeMacroTimeseries(value);
  const codes = new Set(normalized.series.map((series) => series.code));
  if (codes.size !== EXPECTED_SERIES_CODES.size || [...EXPECTED_SERIES_CODES].some((code) => !codes.has(code))) {
    throw new Error("Incomplete macro series registry");
  }
  return normalized;
}

export async function getMacroTimeseries(execute: SqlExecutor) {
  const result = await execute(QUERY, []);
  return normalizeCanonicalMacroTimeseries(result.rows[0]?.payload);
}
