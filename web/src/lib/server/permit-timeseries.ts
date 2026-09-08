import {
  normalizePermitTimeseries,
  type PermitTimeseriesRequest,
  type PermitTimeseriesResponse,
} from "@/lib/permit-timeseries-contract";

export type PermitTimeseriesSqlExecutor = (
  text: string,
  values: readonly (string | number | null)[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

const SEOUL_SOURCE = "src_seoul_building_permit";

export const permitTimeseriesSql = `
WITH available AS MATERIALIZED (
  SELECT (
    SELECT event_month FROM serving_v2_building_permit_monthly
    WHERE source_id='src_seoul_building_permit' AND scope_status='IN_SCOPE'
      AND event_month BETWEEN '1900-01' AND strftime('%Y-%m','now','+9 hours')
    ORDER BY event_month LIMIT 1
  ) AS available_from,(
    SELECT event_month FROM serving_v2_building_permit_monthly
    WHERE source_id='src_seoul_building_permit' AND scope_status='IN_SCOPE'
      AND event_month BETWEEN '1900-01' AND strftime('%Y-%m','now','+9 hours')
    ORDER BY event_month DESC LIMIT 1
  ) AS available_through
), selected AS MATERIALIZED (
  SELECT coalesce(?2,strftime('%Y-%m',date(available_through||'-01','-59 months'))) AS selected_from,
         coalesce(?3,available_through) AS selected_through
  FROM available
), filtered AS MATERIALIZED (
  SELECT monthly.*
  FROM serving_v2_building_permit_monthly monthly
  CROSS JOIN selected
  WHERE monthly.source_id='src_seoul_building_permit'
    AND monthly.scope_status='IN_SCOPE'
    AND monthly.event_month BETWEEN selected.selected_from AND selected.selected_through
    AND monthly.event_month BETWEEN '1900-01' AND strftime('%Y-%m','now','+9 hours')
    AND (?4 IS NULL OR monthly.event_type=?4)
    AND (?5 IS NULL OR monthly.asset_type=?5)
    AND (?6 IS NULL OR monthly.district_name=?6)
    AND (?7 IS NULL OR monthly.construction_action=?7)
), grouped AS MATERIALIZED (
  SELECT CASE ?1
           WHEN 'EVENT_TYPE' THEN event_type
           WHEN 'ASSET_TYPE' THEN asset_type
           WHEN 'DISTRICT' THEN district_name
           WHEN 'CONSTRUCTION_ACTION' THEN construction_action
         END AS group_key,
         event_month,
         sum(permit_count) AS permit_count,
         sum(total_floor_area_m2) AS total_floor_area_m2,
         sum(missing_area_count) AS missing_area_count,
         sum(invalid_area_count) AS invalid_area_count
  FROM filtered
  GROUP BY group_key,event_month
), series_keys AS MATERIALIZED (
  SELECT DISTINCT group_key FROM grouped WHERE group_key IS NOT NULL
), freshness AS MATERIALIZED (
  SELECT source_as_of_date,generated_at
  FROM serving_dataset_freshness
  WHERE dataset_code='SEOUL_BUILDING_PERMITS'
)
SELECT json_object(
  'generatedAt',(SELECT generated_at FROM freshness),
  'sourceAsOfDate',(SELECT source_as_of_date FROM freshness),
  'availableFrom',(SELECT available_from FROM available),
  'availableThrough',(SELECT available_through FROM available),
  'selectedFrom',(SELECT selected_from FROM selected),
  'selectedThrough',(SELECT selected_through FROM selected),
  'groupBy',?1,
  'filters',json_object(
    'eventType',?4,'assetType',?5,'district',?6,'constructionAction',?7
  ),
  'source',json_object('code','src_seoul_building_permit','label','서울 열린데이터광장'),
  'scope',json_object(
    'status','IN_SCOPE',
    'completedSnapshotsOnly',json('true'),
    'dateRule','ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT'
  ),
  'series',json(COALESCE((SELECT json_group_array(json_object(
    'key',series.group_key,
    'label',CASE series.group_key
      WHEN 'PERMIT' THEN '건축허가'
      WHEN 'ACTUAL_START' THEN '착공'
      WHEN 'USE_APPROVAL' THEN '사용승인'
      WHEN 'OFFICE' THEN '오피스'
      WHEN 'LOGISTICS' THEN '물류센터'
      WHEN 'DATA_CENTER' THEN '데이터센터'
      WHEN 'HOTEL' THEN '호텔'
      WHEN 'RETAIL' THEN '리테일'
      WHEN 'MIXED_USE' THEN '복합용도'
      WHEN 'OTHER_COMMERCIAL' THEN '기타 상업시설'
      WHEN 'NONCOMMERCIAL' THEN '비상업시설'
      WHEN 'RESIDENTIAL' THEN '주거시설'
      WHEN 'UNKNOWN' THEN '미분류'
      WHEN 'NEW_SUPPLY' THEN '신규 공급'
      WHEN 'AREA_EXPANSION' THEN '증축'
      WHEN 'REDEVELOPMENT' THEN '재개발'
      WHEN 'USE_CONVERSION' THEN '용도 전환'
      WHEN 'OTHER' THEN '기타 공사'
      ELSE series.group_key
    END,
    'points',json(COALESCE((
      SELECT json_group_array(json_object(
        'month',point.event_month,
        'permitCount',point.permit_count,
        'totalFloorAreaM2',point.total_floor_area_m2,
        'missingAreaCount',point.missing_area_count,
        'invalidAreaCount',point.invalid_area_count
      ))
      FROM (
        SELECT * FROM grouped point
        WHERE point.group_key=series.group_key
        ORDER BY point.event_month
      ) point
    ),'[]'))
  )) FROM (
    SELECT * FROM series_keys ORDER BY group_key
  ) series),'[]')),
  'quality',json_object(
    'aggregateRowCount',(SELECT count(*) FROM filtered),
    'permitCount',coalesce((SELECT sum(permit_count) FROM filtered),0),
    'totalFloorAreaM2',coalesce((SELECT sum(total_floor_area_m2) FROM filtered),0),
    'missingAreaCount',coalesce((SELECT sum(missing_area_count) FROM filtered),0),
    'invalidAreaCount',coalesce((SELECT sum(invalid_area_count) FROM filtered),0)
  )
) AS payload`;

export async function getPermitTimeseries(
  execute: PermitTimeseriesSqlExecutor,
  request: PermitTimeseriesRequest,
): Promise<PermitTimeseriesResponse> {
  const result = await execute(permitTimeseriesSql, [
    request.groupBy,
    request.from,
    request.to,
    request.eventType,
    request.assetType,
    request.district,
    request.constructionAction,
  ]);
  const payload = normalizePermitTimeseries(result.rows[0]?.payload);
  if (payload.source.code !== SEOUL_SOURCE) throw new Error("Invalid permit source");
  return payload;
}
