import {
  LARGE_TRANSACTION_MIN_AREA_M2,
  LARGE_TRANSACTION_MIN_AREA_PYEONG,
  LARGE_TRANSACTION_PAGE_SIZE,
  MAX_LARGE_TRANSACTION_PAGE,
  LargeTransactionRequestError,
  normalizeLargeTransactions,
  type LargeTransactionRow,
  type LargeTransactionsRequest,
  type LargeTransactionsResponse,
} from "@/lib/large-transactions-contract";
import { normalizeQuantitativeMarketPulse } from "@/lib/quantitative-market-pulse-contract";

export type LargeTransactionsSqlExecutor = (
  text: string,
  values: readonly (string | number | null)[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

export class LargeTransactionMonthUnavailableError extends Error {
  readonly code = "LARGE_TRANSACTION_MONTH_UNAVAILABLE";

  constructor() {
    super("The requested month is not a completed 25-district Seoul snapshot");
    this.name = "LargeTransactionMonthUnavailableError";
  }
}

export class LargeTransactionDetailUnavailableError extends Error {
  readonly code = "LARGE_TRANSACTION_DETAIL_UNAVAILABLE";

  constructor() {
    super("The compact snapshot does not contain individual transaction detail");
    this.name = "LargeTransactionDetailUnavailableError";
  }
}

type QueryPayload = {
  generatedAt: unknown;
  expectedDistrictCount: number;
  presentDistrictCount: number;
  completedDistrictCount: number;
  baseTransactionCount: number;
  totalCount: number;
  rows: unknown[];
};

type CompactLargeTransactionPage = {
  page: number;
  rows: LargeTransactionRow[];
};

type CompactLargeTransactionMonth = {
  month: string;
  baseTransactionCount: number;
  totalCount: number;
  coverage: {
    status: "COMPLETE";
    expectedDistrictCount: 25;
    completedDistrictCount: 25;
  };
  pages: CompactLargeTransactionPage[];
};

export type CompactLargeTransactionsSnapshot = {
  datasetVersion: string;
  generatedAt: string;
  minAreaPyeong: typeof LARGE_TRANSACTION_MIN_AREA_PYEONG;
  minAreaM2: number;
  areaBasis: "TRANSACTED_BUILDING_AREA";
  pageSize: typeof LARGE_TRANSACTION_PAGE_SIZE;
  months: CompactLargeTransactionMonth[];
};

const MAX_COMPACT_MONTHS = 19;
const MAX_COMPACT_ROWS = 10_000;
const MAX_COMPACT_UTF8_BYTES = 1024 * 1024;

export const largeTransactionsSql = `
WITH RECURSIVE expected_districts(district_code) AS (
  VALUES ('11110'),('11140'),('11170'),('11200'),('11215'),('11230'),('11260'),
         ('11290'),('11305'),('11320'),('11350'),('11380'),('11410'),('11440'),
         ('11470'),('11500'),('11530'),('11545'),('11560'),('11590'),('11620'),
         ('11650'),('11680'),('11710'),('11740')
), selected_coverage AS MATERIALIZED (
  SELECT (SELECT count(*) FROM expected_districts) AS expected_district_count,
         count(DISTINCT CASE WHEN e.district_code IS NOT NULL THEN p.district_code END)
           AS present_district_count,
         count(DISTINCT CASE
           WHEN e.district_code IS NOT NULL AND p.coverage_status IN (
             'COMPLETE_FULL_SNAPSHOT','COMPLETE_EMPTY','COMPLETE_BASELINE_WITH_CHANGES'
           ) THEN p.district_code END) AS completed_district_count
  FROM serving_molit_completed_partitions p
  LEFT JOIN expected_districts e ON e.district_code=p.district_code
  WHERE p.deal_month=?1
), raw_records AS MATERIALIZED (
  SELECT api_payload_sha256,
         district_code AS sgg_code,district_name AS district,locality,
         building_use,building_area_text AS building_area,
         deal_amount_text AS deal_amount,deal_year,
         deal_month_number AS deal_month,deal_day,
         nullif(trim(CAST(json_extract(api_payload_json,'$.buildingType') AS TEXT)),'')
           AS building_type,
         nullif(trim(CAST(json_extract(api_payload_json,'$.jibun') AS TEXT)),'') AS jibun
  FROM serving_molit_current_transactions
  WHERE deal_year=substr(?1,1,4)
    AND deal_month_number IN (
      substr(?1,6,2),CAST(CAST(substr(?1,6,2) AS INTEGER) AS TEXT)
    )
), raw_eligible AS MATERIALIZED (
  SELECT *
  FROM raw_records
  WHERE (SELECT present_district_count=expected_district_count
           AND completed_district_count=expected_district_count FROM selected_coverage)
    AND sgg_code LIKE '11%'
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
    AND CAST(deal_month AS TEXT) NOT GLOB '*[^0-9]*'
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
         district,locality,building_use,building_area,deal_amount,building_type,jibun
  FROM raw_eligible
), canonical_transactions AS MATERIALIZED (
  SELECT api_payload_sha256 AS id,
         printf(
           '%04d-%02d-%02d',
           CAST(deal_year AS INTEGER),CAST(deal_month AS INTEGER),CAST(deal_day AS INTEGER)
         ) AS deal_date,
         trim(
           coalesce(district,'')||' '||coalesce(locality,'')||
           CASE WHEN jibun IS NULL THEN '' ELSE ' '||jibun END
         ) AS address,
         building_use,building_type,
         CAST(building_area AS REAL) AS area_m2,
         CAST(replace(deal_amount,',','') AS INTEGER)*10000 AS amount_krw
  FROM eligible
), large_transactions AS MATERIALIZED (
  SELECT *
  FROM canonical_transactions
  WHERE area_m2*121>=2000000
), freshness AS MATERIALIZED (
  SELECT generated_at
  FROM serving_dataset_freshness
  WHERE dataset_code='MOLIT_TRANSACTIONS' AND source_status_code='READY'
)
SELECT json_object(
  'generatedAt',(SELECT generated_at FROM freshness),
  'expectedDistrictCount',(SELECT expected_district_count FROM selected_coverage),
  'presentDistrictCount',(SELECT present_district_count FROM selected_coverage),
  'completedDistrictCount',(SELECT completed_district_count FROM selected_coverage),
  'baseTransactionCount',(SELECT count(*) FROM canonical_transactions),
  'totalCount',(SELECT count(*) FROM large_transactions),
  'rows',json(COALESCE((
    SELECT json_group_array(json_object(
      'id',page_rows.id,
      'dealDate',page_rows.deal_date,
      'address',page_rows.address,
      'buildingUse',page_rows.building_use,
      'buildingType',page_rows.building_type,
      'areaM2',page_rows.area_m2,
      'areaPyeong',round(page_rows.area_m2*121/400,2),
      'amountKrw',CAST(page_rows.amount_krw AS TEXT)
    ))
    FROM (
      SELECT * FROM large_transactions
      ORDER BY area_m2 DESC,amount_krw DESC,deal_date DESC,id
      LIMIT ?2 OFFSET ?3
    ) page_rows
  ),'[]'))
) AS payload`;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function count(value: unknown, label: string) {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`Invalid ${label}`);
  }
  return value;
}

function parseQueryPayload(value: unknown): QueryPayload {
  if (!record(value) || !Array.isArray(value.rows)) {
    throw new Error("Invalid large transactions database payload");
  }
  return {
    generatedAt: value.generatedAt,
    expectedDistrictCount: count(value.expectedDistrictCount, "expectedDistrictCount"),
    presentDistrictCount: count(value.presentDistrictCount, "presentDistrictCount"),
    completedDistrictCount: count(value.completedDistrictCount, "completedDistrictCount"),
    baseTransactionCount: count(value.baseTransactionCount, "baseTransactionCount"),
    totalCount: count(value.totalCount, "totalCount"),
    rows: value.rows,
  };
}

export function currentKstMonth(now = new Date()) {
  return new Date(now.getTime() + 9 * 60 * 60 * 1_000).toISOString().slice(0, 7);
}

function requiredText(value: unknown, label: string, maximumLength = 256) {
  if (
    typeof value !== "string"
    || value.trim() === ""
    || value.length > maximumLength
    || /[\u0000-\u001f\u007f]/u.test(value)
  ) throw new Error(`Invalid ${label}`);
  return value;
}

function responseMetadata() {
  return {
    minAreaPyeong: LARGE_TRANSACTION_MIN_AREA_PYEONG,
    minAreaM2: LARGE_TRANSACTION_MIN_AREA_M2,
    areaBasis: "TRANSACTED_BUILDING_AREA" as const,
    pageSize: LARGE_TRANSACTION_PAGE_SIZE,
    source: {
      code: "MOLIT_REAL_TRANSACTION" as const,
      label: "국토교통부 실거래 공개시스템" as const,
      geography: "서울특별시" as const,
      completedPartitionsOnly: true as const,
      exactPayloadDeduplicated: true as const,
      currentServingOnly: true as const,
    },
  };
}

function buildResponse(input: {
  datasetVersion: string;
  generatedAt: unknown;
  month: string;
  baseTransactionCount: number;
  totalCount: number;
  page: number;
  rows: unknown[];
  coverage: unknown;
}) {
  return normalizeLargeTransactions({
    datasetVersion: input.datasetVersion,
    generatedAt: input.generatedAt,
    month: input.month,
    ...responseMetadata(),
    totalCount: input.totalCount,
    baseTransactionCount: input.baseTransactionCount,
    page: input.page,
    totalPages: Math.ceil(input.totalCount / LARGE_TRANSACTION_PAGE_SIZE),
    rows: input.rows,
    coverage: input.coverage,
  });
}

function compareRows(left: LargeTransactionRow, right: LargeTransactionRow) {
  if (left.areaM2 !== right.areaM2) return right.areaM2 - left.areaM2;
  const leftAmount = BigInt(left.amountKrw);
  const rightAmount = BigInt(right.amountKrw);
  if (leftAmount !== rightAmount) return leftAmount > rightAmount ? -1 : 1;
  if (left.dealDate !== right.dealDate) return left.dealDate > right.dealDate ? -1 : 1;
  return left.id.localeCompare(right.id);
}

export function normalizeCompactLargeTransactionsPulse(
  value: unknown,
  expectedDatasetVersion: string,
): CompactLargeTransactionsSnapshot {
  if (!record(value)) throw new Error("Invalid compact market pulse payload");
  const compact = value.largeTransactions;
  if (compact === undefined || compact === null) {
    throw new LargeTransactionDetailUnavailableError();
  }
  if (!record(compact) || !Array.isArray(compact.months)) {
    throw new Error("Invalid compact large transactions payload");
  }
  if (new TextEncoder().encode(JSON.stringify(compact)).byteLength > MAX_COMPACT_UTF8_BYTES) {
    throw new Error("Compact large transactions payload size exceeded");
  }
  if (compact.months.length > MAX_COMPACT_MONTHS) {
    throw new Error("Compact large transactions month bound exceeded");
  }
  let rawRowCount = 0;
  for (const rawMonth of compact.months) {
    if (!record(rawMonth) || !Array.isArray(rawMonth.pages) || rawMonth.pages.length > MAX_LARGE_TRANSACTION_PAGE) {
      throw new Error("Invalid compact large transactions pages");
    }
    for (const rawPage of rawMonth.pages) {
      if (!record(rawPage) || !Array.isArray(rawPage.rows) || rawPage.rows.length > LARGE_TRANSACTION_PAGE_SIZE) {
        throw new Error("Invalid compact large transactions page rows");
      }
      rawRowCount += rawPage.rows.length;
      if (rawRowCount > MAX_COMPACT_ROWS) {
        throw new Error("Compact large transactions row bound exceeded");
      }
    }
  }

  const datasetVersion = requiredText(value.datasetVersion, "datasetVersion", 128);
  if (datasetVersion !== expectedDatasetVersion) {
    throw new Error("Compact large transactions dataset version mismatch");
  }
  if (
    compact.contractVersion !== 1
    || compact.minAreaPyeong !== LARGE_TRANSACTION_MIN_AREA_PYEONG
    || typeof compact.minAreaM2 !== "number"
    || Math.abs(compact.minAreaM2 - LARGE_TRANSACTION_MIN_AREA_M2) > 1e-9
    || compact.areaBasis !== "TRANSACTED_BUILDING_AREA"
    || compact.pageSize !== LARGE_TRANSACTION_PAGE_SIZE
  ) throw new Error("Invalid compact large transactions contract metadata");

  const pulse = normalizeQuantitativeMarketPulse(value);
  if (compact.months.length !== pulse.trend.length) {
    throw new LargeTransactionDetailUnavailableError();
  }
  const months = compact.months.map((rawMonth, monthIndex): CompactLargeTransactionMonth => {
    if (!record(rawMonth) || !Array.isArray(rawMonth.pages) || !record(rawMonth.coverage)) {
      throw new Error(`Invalid compact month ${monthIndex}`);
    }
    const month = requiredText(rawMonth.month, `months.${monthIndex}.month`, 7);
    const trendPoint = pulse.trend[monthIndex];
    const baseTransactionCount = count(rawMonth.baseTransactionCount, `months.${monthIndex}.baseTransactionCount`);
    const totalCount = count(rawMonth.totalCount, `months.${monthIndex}.totalCount`);
    if (
      month !== trendPoint.period
      || baseTransactionCount !== trendPoint.transactionCount
      || totalCount > baseTransactionCount
    ) throw new Error(`Invalid compact month ${monthIndex} count lineage`);
    const totalPages = Math.ceil(totalCount / LARGE_TRANSACTION_PAGE_SIZE);
    if (totalPages > MAX_LARGE_TRANSACTION_PAGE || rawMonth.pages.length !== totalPages) {
      throw new Error(`Invalid compact month ${monthIndex} pagination`);
    }
    const coverage = {
      status: rawMonth.coverage.status,
      expectedDistrictCount: rawMonth.coverage.expectedDistrictCount,
      completedDistrictCount: rawMonth.coverage.completedDistrictCount,
    };
    const pages = rawMonth.pages.map((rawPage, pageIndex): CompactLargeTransactionPage => {
      if (!record(rawPage) || !Array.isArray(rawPage.rows) || rawPage.page !== pageIndex + 1) {
        throw new Error(`Invalid compact month ${monthIndex} page ${pageIndex}`);
      }
      const normalized = buildResponse({
        datasetVersion,
        generatedAt: pulse.generatedAt,
        month,
        baseTransactionCount,
        totalCount,
        page: pageIndex + 1,
        rows: rawPage.rows,
        coverage,
      });
      return { page: normalized.page, rows: normalized.rows };
    });
    if (totalCount === 0) {
      buildResponse({
        datasetVersion,
        generatedAt: pulse.generatedAt,
        month,
        baseTransactionCount,
        totalCount,
        page: 1,
        rows: [],
        coverage,
      });
    }
    const allRows = pages.flatMap((page) => page.rows);
    if (!/^(?:0|[1-9]\d*)$/u.test(trendPoint.amountKrw)) {
      throw new Error(`Invalid compact month ${monthIndex} amount lineage`);
    }
    const selectedAmount = allRows.reduce((sum, row) => sum + BigInt(row.amountKrw), BigInt(0));
    const selectedArea = allRows.reduce((sum, row) => sum + row.areaM2, 0);
    if (
      allRows.length !== totalCount
      || new Set(allRows.map((row) => row.id)).size !== allRows.length
      || allRows.some((row, index) => index > 0 && compareRows(allRows[index - 1], row) > 0)
      || selectedAmount > BigInt(trendPoint.amountKrw)
      || selectedArea > Number(trendPoint.areaM2) + 1e-6
    ) throw new Error(`Invalid compact month ${monthIndex} rows`);
    return {
      month,
      baseTransactionCount,
      totalCount,
      coverage: {
        status: "COMPLETE",
        expectedDistrictCount: 25,
        completedDistrictCount: 25,
      },
      pages,
    };
  });
  return {
    datasetVersion,
    generatedAt: pulse.generatedAt,
    minAreaPyeong: LARGE_TRANSACTION_MIN_AREA_PYEONG,
    minAreaM2: LARGE_TRANSACTION_MIN_AREA_M2,
    areaBasis: "TRANSACTED_BUILDING_AREA",
    pageSize: LARGE_TRANSACTION_PAGE_SIZE,
    months,
  };
}

export function getLargeTransactionsFromCompactSnapshot(
  snapshot: CompactLargeTransactionsSnapshot,
  request: LargeTransactionsRequest,
  now = new Date(),
) {
  if (request.month >= currentKstMonth(now)) {
    throw new LargeTransactionMonthUnavailableError();
  }
  const month = snapshot.months.find((item) => item.month === request.month);
  if (!month) throw new LargeTransactionMonthUnavailableError();
  const totalPages = Math.ceil(month.totalCount / LARGE_TRANSACTION_PAGE_SIZE);
  if (request.page > Math.max(1, totalPages)) {
    throw new LargeTransactionRequestError("Page exceeds the available result set");
  }
  return buildResponse({
    datasetVersion: snapshot.datasetVersion,
    generatedAt: snapshot.generatedAt,
    month: month.month,
    baseTransactionCount: month.baseTransactionCount,
    totalCount: month.totalCount,
    page: request.page,
    rows: month.totalCount === 0 ? [] : month.pages[request.page - 1].rows,
    coverage: month.coverage,
  });
}

export async function getLargeTransactions(
  execute: LargeTransactionsSqlExecutor,
  request: LargeTransactionsRequest,
  datasetVersion: string,
  now = new Date(),
): Promise<LargeTransactionsResponse> {
  if (request.month >= currentKstMonth(now)) {
    throw new LargeTransactionMonthUnavailableError();
  }
  const result = await execute(largeTransactionsSql, [
    request.month,
    LARGE_TRANSACTION_PAGE_SIZE,
    (request.page - 1) * LARGE_TRANSACTION_PAGE_SIZE,
  ]);
  const payload = parseQueryPayload(result.rows[0]?.payload);
  if (
    payload.expectedDistrictCount !== 25
    || payload.presentDistrictCount !== 25
    || payload.completedDistrictCount !== 25
  ) throw new LargeTransactionMonthUnavailableError();
  const totalPages = Math.ceil(payload.totalCount / LARGE_TRANSACTION_PAGE_SIZE);
  if (request.page > Math.max(1, totalPages)) {
    throw new LargeTransactionRequestError("Page exceeds the available result set");
  }
  return buildResponse({
    datasetVersion,
    generatedAt: payload.generatedAt,
    month: request.month,
    totalCount: payload.totalCount,
    baseTransactionCount: payload.baseTransactionCount,
    page: request.page,
    rows: payload.rows,
    coverage: { status: "COMPLETE", expectedDistrictCount: 25, completedDistrictCount: 25 },
  });
}
