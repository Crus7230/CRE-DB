import { normalizeQuantitativeMarketPulse } from "@/lib/quantitative-market-pulse-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

export type MarketPulseTrendPoint = {
  period: string;
  transactionCount: number;
  amountKrw: string;
  areaM2: string;
  sourceRowCount: number;
  uniquePayloadCount: number;
};

type Metric = {
  value: number;
  previousValue: number | null;
  yearAgoValue: number | null;
  momPct: number | null;
  yoyPct: number | null;
  ytdValue: number | null;
  priorYtdValue: number | null;
  ytdYoyPct: number | null;
};

type QueryPayload = {
  generatedAt: string;
  asOfPeriod: string;
  trend: MarketPulseTrendPoint[];
  analysisTrend: MarketPulseTrendPoint[];
  latestGroups: Array<{ rank: number; dealDate: string; district: string; locality: string; buildingUse: string; amountKrw: string; areaM2: string; sharePct: number }>;
  districts: Array<{ district: string; transactionCount: number; amountKrw: string; areaM2: string; sharePct: number }>;
  coverage: { expectedDistrictCount: number; observedMonthCount: number; completeMonthCount: number; returnedMonthCount: number; excludedMonthCount: number; coverageComplete: boolean };
};

const QUERY = `WITH RECURSIVE expected_districts(district_code) AS (
  VALUES ('11110'),('11140'),('11170'),('11200'),('11215'),('11230'),('11260'),
         ('11290'),('11305'),('11320'),('11350'),('11380'),('11410'),('11440'),
         ('11470'),('11500'),('11530'),('11545'),('11560'),('11590'),('11620'),
         ('11650'),('11680'),('11710'),('11740')
), raw_records AS MATERIALIZED (
  SELECT transaction_key,api_payload_sha256,
         district_code AS sgg_code,district_name AS district,locality,
         building_use,building_area_text AS building_area,
         deal_amount_text AS deal_amount,deal_year,
         deal_month_number AS deal_month,deal_day
  FROM serving_molit_current_transactions
), coverage_by_month AS MATERIALIZED (
  SELECT p.deal_month,
         count(DISTINCT CASE WHEN e.district_code IS NOT NULL THEN p.district_code END) AS present_district_count,
         count(DISTINCT CASE
           WHEN e.district_code IS NOT NULL AND p.coverage_status IN (
             'COMPLETE_FULL_SNAPSHOT','COMPLETE_EMPTY','COMPLETE_BASELINE_WITH_CHANGES'
           ) THEN p.district_code END) AS available_district_count
  FROM serving_molit_completed_partitions p
  LEFT JOIN expected_districts e ON e.district_code=p.district_code
  WHERE p.deal_month GLOB '20[0-9][0-9]-[0-1][0-9]'
  GROUP BY p.deal_month
), source_coverage AS MATERIALIZED (
  SELECT p.deal_month||'-01' AS month_start,
         sum(coalesce(p.discovered_count,0)) AS source_record_count
  FROM serving_molit_completed_partitions p
  JOIN coverage_by_month c ON c.deal_month=p.deal_month
  JOIN expected_districts e ON e.district_code=p.district_code
  WHERE c.present_district_count=(SELECT count(*) FROM expected_districts)
    AND c.available_district_count=(SELECT count(*) FROM expected_districts)
    AND p.coverage_status IN (
      'COMPLETE_FULL_SNAPSHOT','COMPLETE_EMPTY','COMPLETE_BASELINE_WITH_CHANGES'
    )
  GROUP BY p.deal_month
), coverage_summary AS (
  SELECT CAST(json_extract(metadata_json,'$.expectedDistrictCount') AS INTEGER) AS expected_district_count,
         CAST(json_extract(metadata_json,'$.completeMonthCount') AS INTEGER)
           + CAST(json_extract(metadata_json,'$.excludedMonthCount') AS INTEGER) AS observed_month_count,
         CAST(json_extract(metadata_json,'$.completeMonthCount') AS INTEGER) AS complete_month_count,
         CAST(json_extract(metadata_json,'$.excludedMonthCount') AS INTEGER) AS excluded_month_count
  FROM serving_dataset_freshness
  WHERE dataset_code='MOLIT_TRANSACTIONS' AND source_status_code='READY'
), raw_eligible AS MATERIALIZED (
  SELECT *
  FROM raw_records
  WHERE sgg_code LIKE '11%'
    AND nullif(trim(building_use),'') IS NOT NULL
    AND instr(building_use,'아파트')=0
    AND instr(building_use,'공동주택')=0
    AND instr(building_use,'단독주택')=0
    AND instr(building_use,'다가구')=0
    AND instr(building_use,'다세대')=0
    AND instr(building_use,'연립')=0
    AND instr(building_use,'주택')=0
    AND instr(building_use,'주거')=0
    AND building_area<>''
    AND building_area NOT GLOB '*[^0-9.]*'
    AND building_area NOT LIKE '%.%.%'
    AND building_area NOT LIKE '.%'
    AND building_area NOT LIKE '%.'
    AND CAST(building_area AS REAL)>3300
    AND deal_amount<>''
    AND deal_amount NOT GLOB '*[^0-9,]*'
    AND NOT EXISTS (
      SELECT 1
      FROM json_each('['||replace(json_quote(deal_amount),',','","')||']') amount_part
      WHERE amount_part.value=''
         OR amount_part.value GLOB '*[^0-9]*'
         OR CASE
              WHEN instr(deal_amount,',')=0 THEN 0
              WHEN CAST(amount_part.key AS INTEGER)=0 THEN 0
              ELSE length(amount_part.value)<>3
            END
    )
    AND deal_year GLOB '20[0-9][0-9]'
    AND length(deal_month) BETWEEN 1 AND 2
    AND deal_month NOT GLOB '*[^0-9]*'
    AND CAST(deal_month AS INTEGER) BETWEEN 1 AND 12
    AND length(deal_day) BETWEEN 1 AND 2
    AND deal_day NOT GLOB '*[^0-9]*'
    AND CAST(deal_day AS INTEGER) BETWEEN 1 AND 31
    AND date(printf(
      '%04d-%02d-%02d',
      CAST(deal_year AS INTEGER),CAST(deal_month AS INTEGER),CAST(deal_day AS INTEGER)
    ),'+0 days')=printf(
      '%04d-%02d-%02d',
      CAST(deal_year AS INTEGER),CAST(deal_month AS INTEGER),CAST(deal_day AS INTEGER)
    )
), eligible AS MATERIALIZED (
  SELECT DISTINCT api_payload_sha256,deal_year,deal_month,deal_day,
         district,locality,building_use,building_area,deal_amount
  FROM raw_eligible
), canonical_transactions AS (
  SELECT printf(
           '%04d-%02d-01',
           CAST(deal_year AS INTEGER),CAST(deal_month AS INTEGER)
         ) AS month_start,
         printf(
           '%04d-%02d-%02d',
           CAST(deal_year AS INTEGER),CAST(deal_month AS INTEGER),CAST(deal_day AS INTEGER)
         ) AS deal_date,
         district,locality,building_use,
         CAST(replace(deal_amount,',','') AS INTEGER)*10000 AS amount_krw,
         CAST(building_area AS REAL) AS area_m2
  FROM eligible
), monthly_quality AS (
  SELECT printf('%04d-%02d-01',CAST(deal_year AS INTEGER),CAST(deal_month AS INTEGER)) AS month_start,
         count(*) AS source_row_count,
         count(DISTINCT api_payload_sha256) AS unique_payload_count
  FROM raw_eligible
  GROUP BY month_start
), monthly_facts AS (
  SELECT month_start,count(*) AS transaction_count,sum(amount_krw) AS amount_krw,sum(area_m2) AS area_m2
  FROM canonical_transactions
  GROUP BY month_start
), data_bounds AS (
  SELECT max(month_start) AS latest_data_month FROM source_coverage
), clock AS (
  SELECT date('now','+9 hours','start of month') AS current_month
), reference_month AS (
  SELECT (
           SELECT max(coverage.month_start)
           FROM source_coverage coverage
           WHERE coverage.month_start<clock.current_month
         ) AS month_start,
         clock.current_month,data_bounds.latest_data_month
  FROM data_bounds CROSS JOIN clock
), calendar(month_start,end_month) AS (
  SELECT CASE
           WHEN date(r.month_start,'-18 months')<date(r.month_start,'start of year','-1 year')
             THEN date(r.month_start,'-18 months')
           ELSE date(r.month_start,'start of year','-1 year')
         END,
         r.month_start
  FROM reference_month r
  WHERE r.month_start IS NOT NULL
  UNION ALL
  SELECT date(month_start,'+1 month'),end_month
  FROM calendar
  WHERE month_start<end_month
), monthly AS (
  SELECT c.month_start,
         coalesce(f.transaction_count,0) AS transaction_count,
         coalesce(f.amount_krw,0) AS amount_krw,
         coalesce(f.area_m2,0) AS area_m2,
         coalesce(q.source_row_count,0) AS source_row_count,
         coalesce(q.unique_payload_count,0) AS unique_payload_count
  FROM calendar c
  JOIN source_coverage coverage USING(month_start)
  LEFT JOIN monthly_facts f USING(month_start)
  LEFT JOIN monthly_quality q USING(month_start)
), ranked_transactions AS (
  SELECT t.*,
         row_number() OVER(ORDER BY t.amount_krw DESC,t.deal_date,t.district,t.locality) AS amount_rank,
         100.0*t.amount_krw/nullif(sum(t.amount_krw) OVER(),0) AS share_pct
  FROM canonical_transactions t
  JOIN reference_month r ON t.month_start=r.month_start
), district_totals AS (
  SELECT district,count(*) AS transaction_count,sum(amount_krw) AS amount_krw,sum(area_m2) AS area_m2,
         100.0*sum(amount_krw)/nullif(sum(sum(amount_krw)) OVER(),0) AS share_pct
  FROM canonical_transactions t
  JOIN reference_month r ON t.month_start=r.month_start
  GROUP BY district
)
SELECT json_object(
  'generatedAt',strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  'asOfPeriod',(SELECT strftime('%Y-%m',month_start) FROM reference_month),
  'analysisTrend',json(coalesce((
    SELECT json_group_array(json_object(
      'period',strftime('%Y-%m',month_start),'transactionCount',transaction_count,
      'amountKrw',CAST(amount_krw AS TEXT),'areaM2',CAST(area_m2 AS TEXT),
      'sourceRowCount',source_row_count,'uniquePayloadCount',unique_payload_count
    ))
    FROM (SELECT * FROM monthly ORDER BY month_start)
  ),'[]')),
  'trend',json(coalesce((
    SELECT json_group_array(json_object(
      'period',strftime('%Y-%m',month_start),'transactionCount',transaction_count,
      'amountKrw',CAST(amount_krw AS TEXT),'areaM2',CAST(area_m2 AS TEXT),
      'sourceRowCount',source_row_count,'uniquePayloadCount',unique_payload_count
    ))
    FROM (
      SELECT monthly.*
      FROM monthly CROSS JOIN reference_month r
      WHERE monthly.month_start>=date(r.month_start,'-18 months')
      ORDER BY monthly.month_start
    )
  ),'[]')),
  'latestGroups',json(coalesce((
    SELECT json_group_array(json_object(
      'rank',amount_rank,'dealDate',deal_date,'district',district,'locality',locality,
      'buildingUse',building_use,'amountKrw',CAST(amount_krw AS TEXT),'areaM2',CAST(area_m2 AS TEXT),
      'sharePct',round(share_pct,2)
    ))
    FROM (SELECT * FROM ranked_transactions WHERE amount_rank<=5 ORDER BY amount_rank)
  ),'[]')),
  'districts',json(coalesce((
    SELECT json_group_array(json_object(
      'district',district,'transactionCount',transaction_count,'amountKrw',CAST(amount_krw AS TEXT),
      'areaM2',CAST(area_m2 AS TEXT),'sharePct',round(share_pct,2)
    ))
    FROM (SELECT * FROM district_totals ORDER BY amount_krw DESC,district)
  ),'[]')),
  'coverage',json_object(
    'expectedDistrictCount',(SELECT expected_district_count FROM coverage_summary),
    'observedMonthCount',(SELECT observed_month_count FROM coverage_summary),
    'completeMonthCount',(SELECT complete_month_count FROM coverage_summary),
    'returnedMonthCount',(SELECT count(*) FROM monthly),
    'excludedMonthCount',(SELECT excluded_month_count FROM coverage_summary),
    'coverageComplete',json(CASE
      WHEN (SELECT excluded_month_count FROM coverage_summary)=0 THEN 'true' ELSE 'false' END)
  )
) AS payload`;

export const quantitativeMarketPulseSql = QUERY;

const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const requiredText = (value: unknown, label: string) => {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`Invalid ${label}`);
  return value;
};
const integer = (value: unknown, label: string, minimum = 0) => {
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) throw new Error(`Invalid ${label}`);
  return value;
};
const bounded = (value: unknown, label: string) => {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 100) throw new Error(`Invalid ${label}`);
  return value;
};
const boolean = (value: unknown, label: string) => {
  if (typeof value !== "boolean") throw new Error(`Invalid ${label}`);
  return value;
};
const decimalText = (value: unknown, label: string) => {
  const result = requiredText(value, label);
  if (!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(result) || !Number.isFinite(Number(result))) throw new Error(`Invalid ${label}`);
  return result;
};
const monthPeriod = (value: unknown, label: string) => {
  const result = requiredText(value, label);
  if (!/^\d{4}-(?:0[1-9]|1[0-2])$/.test(result)) throw new Error(`Invalid ${label}`);
  return result;
};
const isoTimestamp = (value: unknown, label: string) => {
  const result = requiredText(value, label);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(result) || Number.isNaN(Date.parse(result))) throw new Error(`Invalid ${label}`);
  return new Date(result).toISOString();
};
const isoDate = (value: unknown, label: string) => {
  const result = requiredText(value, label);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result) || new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result) throw new Error(`Invalid ${label}`);
  return result;
};

function parsePoint(value: unknown, label: string): MarketPulseTrendPoint {
  if (!record(value)) throw new Error(`Invalid ${label}`);
  const point = {
    period: monthPeriod(value.period, `${label}.period`),
    transactionCount: integer(value.transactionCount, `${label}.transactionCount`),
    amountKrw: decimalText(value.amountKrw, `${label}.amountKrw`),
    areaM2: decimalText(value.areaM2, `${label}.areaM2`),
    sourceRowCount: integer(value.sourceRowCount, `${label}.sourceRowCount`),
    uniquePayloadCount: integer(value.uniquePayloadCount, `${label}.uniquePayloadCount`),
  };
  if (point.transactionCount !== point.uniquePayloadCount || point.sourceRowCount < point.uniquePayloadCount) throw new Error(`Invalid ${label} count invariant`);
  const amountValue = Number(point.amountKrw);
  const areaValue = Number(point.areaM2);
  if (point.transactionCount === 0 ? amountValue !== 0 || areaValue !== 0 : amountValue <= 0 || areaValue <= 0) throw new Error(`Invalid ${label} fact invariant`);
  return point;
}

function parsePoints(value: unknown, label: string) {
  if (!Array.isArray(value) || value.length === 0) throw new Error(`Invalid ${label}`);
  const points = value.map((item, index) => parsePoint(item, `${label}.${index}`));
  for (let index = 1; index < points.length; index += 1) {
    if (points[index].period <= points[index - 1].period) throw new Error(`Invalid ${label} period sequence`);
  }
  return points;
}

function parseQueryPayload(value: unknown): QueryPayload {
  if (!record(value)) throw new Error("Invalid market pulse database payload");
  const generatedAt = isoTimestamp(value.generatedAt, "generatedAt");
  const asOfPeriod = monthPeriod(value.asOfPeriod, "asOfPeriod");
  const trend = parsePoints(value.trend, "trend");
  const analysisTrend = parsePoints(value.analysisTrend, "analysisTrend");
  if (trend.length > 19 || trend.at(-1)?.period !== asOfPeriod || analysisTrend.at(-1)?.period !== asOfPeriod) throw new Error("Invalid trend period");
  const analysisSuffix = analysisTrend.slice(-trend.length);
  if (JSON.stringify(analysisSuffix) !== JSON.stringify(trend)) throw new Error("Invalid trend analysis suffix");
  if (!Array.isArray(value.latestGroups) || !Array.isArray(value.districts) || !record(value.coverage)) throw new Error("Invalid concentration or coverage data");
  const latestGroups = value.latestGroups.map((item, index) => {
    if (!record(item)) throw new Error(`Invalid latestGroups.${index}`);
    return {
      rank: integer(item.rank, `latestGroups.${index}.rank`, 1),
      dealDate: isoDate(item.dealDate, `latestGroups.${index}.dealDate`),
      district: requiredText(item.district, `latestGroups.${index}.district`),
      locality: requiredText(item.locality, `latestGroups.${index}.locality`),
      buildingUse: requiredText(item.buildingUse, `latestGroups.${index}.buildingUse`),
      amountKrw: decimalText(item.amountKrw, `latestGroups.${index}.amountKrw`),
      areaM2: decimalText(item.areaM2, `latestGroups.${index}.areaM2`),
      sharePct: bounded(item.sharePct, `latestGroups.${index}.sharePct`),
    };
  });
  const districts = value.districts.map((item, index) => {
    if (!record(item)) throw new Error(`Invalid districts.${index}`);
    return {
      district: requiredText(item.district, `districts.${index}.district`),
      transactionCount: integer(item.transactionCount, `districts.${index}.transactionCount`),
      amountKrw: decimalText(item.amountKrw, `districts.${index}.amountKrw`),
      areaM2: decimalText(item.areaM2, `districts.${index}.areaM2`),
      sharePct: bounded(item.sharePct, `districts.${index}.sharePct`),
    };
  });
  const latest = trend.at(-1)!;
  if ((latest.transactionCount === 0) !== (latestGroups.length === 0 && districts.length === 0)) throw new Error("Invalid concentration count invariant");
  if (districts.reduce((sum, item) => sum + item.transactionCount, 0) !== latest.transactionCount) throw new Error("Invalid district count invariant");
  const coverage = {
    expectedDistrictCount: integer(value.coverage.expectedDistrictCount, "coverage.expectedDistrictCount", 1),
    observedMonthCount: integer(value.coverage.observedMonthCount, "coverage.observedMonthCount", 1),
    completeMonthCount: integer(value.coverage.completeMonthCount, "coverage.completeMonthCount", 1),
    returnedMonthCount: integer(value.coverage.returnedMonthCount, "coverage.returnedMonthCount", 1),
    excludedMonthCount: integer(value.coverage.excludedMonthCount, "coverage.excludedMonthCount"),
    coverageComplete: boolean(value.coverage.coverageComplete, "coverage.coverageComplete"),
  };
  if (
    coverage.expectedDistrictCount !== 25
    || coverage.completeMonthCount > coverage.observedMonthCount
    || coverage.returnedMonthCount > coverage.completeMonthCount
    || coverage.returnedMonthCount !== analysisTrend.length
    || coverage.coverageComplete !== (coverage.excludedMonthCount === 0)
  ) throw new Error("Invalid coverage invariant");
  return { generatedAt, asOfPeriod, trend, analysisTrend, latestGroups, districts, coverage };
}

const pct = (current: number, comparison: number | null) => comparison === null || comparison === 0 ? null : (current / comparison - 1) * 100;
const asNumber = (value: string | number) => typeof value === "number" ? value : Number(value);
const safeRatio = (numerator: number, denominator: number) => denominator === 0 ? null : numerator / denominator;

const previousMonthPeriod = (period: string) => {
  const [year, month] = period.split("-").map(Number);
  return month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, "0")}`;
};

function metric(points: MarketPulseTrendPoint[], field: "amountKrw" | "transactionCount" | "areaM2"): Metric {
  const latest = points.at(-1)!;
  const previous = points.find((point) => point.period === previousMonthPeriod(latest.period)) ?? null;
  const [year, month] = latest.period.split("-").map(Number);
  const yearAgo = points.find((point) => point.period === `${year - 1}-${String(month).padStart(2, "0")}`) ?? null;
  const value = asNumber(latest[field]);
  const previousValue = previous ? asNumber(previous[field]) : null;
  const yearAgoValue = yearAgo ? asNumber(yearAgo[field]) : null;
  const currentYtd = points.filter((point) => point.period.startsWith(`${year}-`) && Number(point.period.slice(5)) <= month);
  const priorYtd = points.filter((point) => point.period.startsWith(`${year - 1}-`) && Number(point.period.slice(5)) <= month);
  const currentYtdSum = currentYtd.reduce((sum, point) => sum + asNumber(point[field]), 0);
  const priorYtdSum = priorYtd.reduce((sum, point) => sum + asNumber(point[field]), 0);
  const expectedMonths = Array.from({ length: month }, (_, index) => String(index + 1).padStart(2, "0"));
  const currentYtdComplete = expectedMonths.every((candidate) => currentYtd.some((point) => point.period === `${year}-${candidate}`));
  const priorYtdComplete = expectedMonths.every((candidate) => priorYtd.some((point) => point.period === `${year - 1}-${candidate}`));
  const ytdValue = currentYtdComplete ? currentYtdSum : null;
  const priorYtdValue = priorYtdComplete ? priorYtdSum : null;
  return {
    value,
    previousValue,
    yearAgoValue,
    momPct: pct(value, previousValue),
    yoyPct: pct(value, yearAgoValue),
    ytdValue,
    priorYtdValue,
    ytdYoyPct: ytdValue === null ? null : pct(ytdValue, priorYtdValue),
  };
}

const direction = (value: number) => value >= 0.05 ? "증가" : value <= -0.05 ? "감소" : "보합";
export function buildMarketHeadline(amountMomPct: number | null, countMomPct: number | null) {
  if (amountMomPct === null || countMomPct === null) return "전월 비교 불가 — 검증된 기준월 또는 전월 없음";
  const amountDirection = direction(amountMomPct);
  const countDirection = direction(countMomPct);
  return amountDirection === countDirection
    ? `신고 거래금액과 고유 신고행 전월 대비 ${amountDirection}`
    : `신고 거래금액 ${amountDirection} · 고유 신고행 ${countDirection}`;
}

export async function getQuantitativeMarketPulse(execute: SqlExecutor) {
  const result = await execute(quantitativeMarketPulseSql, []);
  const payload = parseQueryPayload(result.rows[0]?.payload);
  const amount = metric(payload.analysisTrend, "amountKrw");
  const count = metric(payload.analysisTrend, "transactionCount");
  const area = metric(payload.analysisTrend, "areaM2");
  const latest = payload.trend.at(-1)!;
  const previous = payload.analysisTrend.find((point) => point.period === previousMonthPeriod(latest.period)) ?? null;
  const [year, month] = latest.period.split("-").map(Number);
  const yearAgo = payload.analysisTrend.find((point) => point.period === `${year - 1}-${String(month).padStart(2, "0")}`) ?? null;
  const averageTicket = safeRatio(amount.value, count.value);
  const previousAverageTicket = previous ? safeRatio(asNumber(previous.amountKrw), previous.transactionCount) : null;
  const yearAgoAverageTicket = yearAgo ? safeRatio(asNumber(yearAgo.amountKrw), yearAgo.transactionCount) : null;
  const unitAmount = safeRatio(amount.value, area.value);
  const previousUnitAmount = previous ? safeRatio(asNumber(previous.amountKrw), asNumber(previous.areaM2)) : null;
  const yearAgoUnitAmount = yearAgo ? safeRatio(asNumber(yearAgo.amountKrw), asNumber(yearAgo.areaM2)) : null;
  const headline = buildMarketHeadline(amount.momPct, count.momPct);
  const averageTicketMomPct = averageTicket === null ? null : pct(averageTicket, previousAverageTicket);
  const averageTicketYoyPct = averageTicket === null ? null : pct(averageTicket, yearAgoAverageTicket);
  const unitAmountMomPct = unitAmount === null ? null : pct(unitAmount, previousUnitAmount);
  const unitAmountYoyPct = unitAmount === null ? null : pct(unitAmount, yearAgoUnitAmount);
  const averageTicketDetail = averageTicketMomPct === null ? "비교 불가" : `${averageTicketMomPct >= 0 ? "+" : ""}${averageTicketMomPct.toFixed(1)}%`;
  const coverageDetail = payload.coverage.coverageComplete
    ? ""
    : ` · 검증 완료 ${payload.coverage.returnedMonthCount}개월만 표시`;
  const coverageCaution = payload.coverage.coverageComplete
    ? ""
    : ` 과거 ${payload.coverage.excludedMonthCount}개월은 25개 자치구 기준선이 완결되지 않아 추이와 비교 계산에서 제외했습니다.`;
  return normalizeQuantitativeMarketPulse({
    generatedAt: payload.generatedAt,
    asOfPeriod: payload.asOfPeriod,
    call: {
      headline,
      detail: `신고 거래금액 ${amount.momPct === null ? "비교 불가" : `${amount.momPct >= 0 ? "+" : ""}${amount.momPct.toFixed(1)}%`} · 고유 신고행 ${count.momPct === null ? "비교 불가" : `${count.momPct >= 0 ? "+" : ""}${count.momPct.toFixed(1)}%`} · 신고행당 평균 ${averageTicketDetail}${coverageDetail}`,
      caution: `면적당 금액은 자산구성 변화의 영향을 받으므로 동일자산 가격지수로 해석하지 않습니다.${coverageCaution}`,
    },
    metrics: {
      amount,
      count,
      area,
      averageTicket: { value: averageTicket, previousValue: previousAverageTicket, yearAgoValue: yearAgoAverageTicket, momPct: averageTicketMomPct, yoyPct: averageTicketYoyPct },
      unitAmount: { value: unitAmount, previousValue: previousUnitAmount, yearAgoValue: yearAgoUnitAmount, momPct: unitAmountMomPct, yoyPct: unitAmountYoyPct },
    },
    trend: payload.trend,
    concentration: { topGroups: payload.latestGroups, districts: payload.districts },
    quality: { sourceRowCount: latest.sourceRowCount, transactionCount: latest.transactionCount, uniquePayloadCount: latest.uniquePayloadCount, exactDuplicateRows: latest.sourceRowCount - latest.uniquePayloadCount },
    scope: {
      geography: "서울특별시",
      source: "국토교통부 실거래 공개시스템",
      population: "용도가 확인된 비주거용 부동산 실거래",
      areaRule: "개별 API 행 건물면적 > 3,300㎡",
      exclusions: ["취소 신고", "주거용", "용도 미상", "동일 API payload 중복"],
      amountBasis: "신고 거래금액 · 원 단위 환산 · 보수적 canonical payload 행 기준",
    },
  });
}
