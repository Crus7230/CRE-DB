import { describe, expect, it, vi } from "vitest";
import { createClient } from "@libsql/client";
import {
  buildMarketHeadline,
  getQuantitativeMarketPulse,
  quantitativeMarketPulseSql,
} from "@/lib/server/quantitative-market-pulse";

type Point = { period: string; transactionCount: number; amountKrw: string; areaM2: string; sourceRowCount: number; uniquePayloadCount: number };

const months = (startYear: number, startMonth: number, count: number): Point[] => Array.from({ length: count }, (_, index) => {
  const date = new Date(Date.UTC(startYear, startMonth - 1 + index, 1));
  return {
    period: `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`,
    transactionCount: 0,
    amountKrw: "0",
    areaM2: "0",
    sourceRowCount: 0,
    uniquePayloadCount: 0,
  };
});

const analysisTrend = months(2025, 1, 19).map((point) => {
  const values: Record<string, Partial<Point>> = {
    "2025-01": { transactionCount: 2, amountKrw: "100", areaM2: "10", sourceRowCount: 2, uniquePayloadCount: 2 },
    "2025-07": { transactionCount: 4, amountKrw: "400", areaM2: "40", sourceRowCount: 4, uniquePayloadCount: 4 },
    "2026-01": { transactionCount: 3, amountKrw: "300", areaM2: "30", sourceRowCount: 3, uniquePayloadCount: 3 },
    "2026-06": { transactionCount: 0, amountKrw: "0", areaM2: "0", sourceRowCount: 0, uniquePayloadCount: 0 },
    "2026-07": { transactionCount: 2, amountKrw: "600", areaM2: "60", sourceRowCount: 3, uniquePayloadCount: 2 },
  };
  return { ...point, ...values[point.period] };
});

const payload = {
  generatedAt: "2026-08-31T02:00:00.000Z",
  asOfPeriod: "2026-07",
  analysisTrend,
  trend: analysisTrend,
  latestGroups: [
    { rank: 1, dealDate: "2026-07-16", district: "강남구", locality: "역삼동", buildingUse: "업무", amountKrw: "400", areaM2: "40", sharePct: 66.67 },
    { rank: 2, dealDate: "2026-07-17", district: "강남구", locality: "삼성동", buildingUse: "판매", amountKrw: "200", areaM2: "20", sharePct: 33.33 },
  ],
  districts: [{ district: "강남구", transactionCount: 2, amountKrw: "600", areaM2: "60", sharePct: 100 }],
  coverage: { expectedDistrictCount: 25, observedMonthCount: 19, completeMonthCount: 19, returnedMonthCount: 19, excludedMonthCount: 0, coverageComplete: true },
};

const seoulDistrictCodes = [
  "11110", "11140", "11170", "11200", "11215", "11230", "11260",
  "11290", "11305", "11320", "11350", "11380", "11410", "11440",
  "11470", "11500", "11530", "11545", "11560", "11590", "11620",
  "11650", "11680", "11710", "11740",
];

const concentrationRoundingPayload = (() => {
  const latestPoint = {
    period: "2026-07",
    transactionCount: 4,
    amountKrw: "562310430000",
    areaM2: "37254",
    sourceRowCount: 4,
    uniquePayloadCount: 4,
  };
  const roundedTrend = analysisTrend.map((point) => point.period === latestPoint.period ? latestPoint : point);
  return {
    ...payload,
    analysisTrend: roundedTrend,
    trend: roundedTrend,
    latestGroups: [
      { rank: 1, dealDate: "2026-07-21", district: "마포구", locality: "서교동", buildingUse: "업무", amountKrw: "252000000000", areaM2: "13274.61", sharePct: 44.82 },
      { rank: 2, dealDate: "2026-07-26", district: "광진구", locality: "화양동", buildingUse: "업무", amountKrw: "120000000000", areaM2: "12097.46", sharePct: 21.34 },
      { rank: 3, dealDate: "2026-07-03", district: "강남구", locality: "청담동", buildingUse: "제1종근린생활", amountKrw: "110310430000", areaM2: "6998.6", sharePct: 19.62 },
      { rank: 4, dealDate: "2026-07-04", district: "강남구", locality: "신사동", buildingUse: "제1종근린생활", amountKrw: "80000000000", areaM2: "4883.33", sharePct: 14.23 },
    ],
    districts: [
      { district: "마포구", transactionCount: 1, amountKrw: "252000000000", areaM2: "13274.61", sharePct: 44.82 },
      { district: "강남구", transactionCount: 2, amountKrw: "190310430000", areaM2: "11881.93", sharePct: 33.84 },
      { district: "광진구", transactionCount: 1, amountKrw: "120000000000", areaM2: "12097.46", sharePct: 21.34 },
    ],
  };
})();

describe("getQuantitativeMarketPulse SQL contract", () => {
  it("validates decimal building areas before SQLite casts", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    await getQuantitativeMarketPulse(execute);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("building_area NOT GLOB '*[^0-9.]*'");
    expect(sql).toContain("building_area NOT LIKE '%.%.%'");
    expect(sql).toContain("building_area NOT LIKE '.%'");
    expect(sql).toContain("building_area NOT LIKE '%.'");
    expect(sql).toContain("CAST(building_area AS REAL)>3300");
  });

  it("deduplicates canonical JSON payloads without regrouping partial fields", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    await getQuantitativeMarketPulse(execute);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("api_payload_sha256");
    expect(sql).toContain("SELECT DISTINCT api_payload_sha256");
    expect(sql).toContain("canonical_transactions AS");
    expect(sql).not.toContain("transaction_group AS");
    expect(sql).not.toContain("document_versions");
    expect(sql).not.toContain("source_documents");
    expect(sql).not.toContain("collection_runs");
    expect(sql).not.toContain("run_documents");
  });

  it("guards source casts so malformed numeric and calendar fields fail closed", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    await getQuantitativeMarketPulse(execute);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("deal_year GLOB '20[0-9][0-9]'");
    expect(sql).toContain("deal_month NOT GLOB '*[^0-9]*'");
    expect(sql).toContain("CAST(deal_month AS INTEGER) BETWEEN 1 AND 12");
    expect(sql).toContain("deal_day NOT GLOB '*[^0-9]*'");
    expect(sql).toContain("CAST(deal_day AS INTEGER) BETWEEN 1 AND 31");
    expect(sql).toContain("AND date(printf(");
    expect(sql).toContain("),'+0 days')=printf(");
    expect(sql).toContain("FROM json_each('['||replace(json_quote(deal_amount),',','\",\"')||']')");
    expect(sql).toContain("WHEN CAST(amount_part.key AS INTEGER)=0 THEN 0");
    expect(sql).toContain("ELSE length(amount_part.value)<>3");
  });

  it("excludes unknown building use and serves only complete 25-district months behind the reporting cutoff", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    await getQuantitativeMarketPulse(execute);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("nullif(trim(building_use),'') IS NOT NULL");
    expect(sql).toContain("instr(building_use,'주거')=0");
    expect(sql).toContain("calendar(month_start,end_month) AS");
    expect(sql).toContain("SELECT date(month_start,'+1 month'),end_month");
    expect(sql).toContain("source_coverage AS MATERIALIZED");
    expect(sql).toContain("expected_districts(district_code)");
    expect(sql).toContain("('11680')");
    expect(sql).toContain("c.present_district_count=(SELECT count(*) FROM expected_districts)");
    expect(sql).toContain("c.available_district_count=(SELECT count(*) FROM expected_districts)");
    expect(sql).toContain("'COMPLETE_BASELINE_WITH_CHANGES'");
    expect(sql).toContain("JOIN source_coverage coverage USING(month_start)");
    expect(sql).toContain("current_month");
    expect(sql).toContain("date('now','+9 hours','start of month')");
    expect(sql).toContain("coverage.month_start<clock.current_month");
    expect(sql).toContain("date(r.month_start,'-18 months')");
  });

  it("treats 15:30 UTC month-end as the next KST month and excludes that current month", async () => {
    const client = createClient({ url: "file::memory:" });
    try {
      const partitions = ["2026-08", "2026-09"].flatMap((month) =>
        seoulDistrictCodes.map((district) =>
          `INSERT INTO serving_molit_completed_partitions VALUES(
            '${month}','${district}','COMPLETE_FULL_SNAPSHOT',
            ${district === "11680" ? 1 : 0}
          )`,
        )
      );
      await client.batch([
        `CREATE TABLE serving_molit_current_transactions(
          transaction_key TEXT,api_payload_sha256 TEXT,district_code TEXT,
          district_name TEXT,locality TEXT,building_use TEXT,
          building_area_text TEXT,deal_amount_text TEXT,deal_year TEXT,
          deal_month_number TEXT,deal_day TEXT
        )`,
        `CREATE TABLE serving_molit_completed_partitions(
          deal_month TEXT,district_code TEXT,coverage_status TEXT,
          discovered_count INTEGER
        )`,
        `CREATE TABLE serving_dataset_freshness(
          dataset_code TEXT,source_status_code TEXT,metadata_json TEXT
        )`,
        `INSERT INTO serving_dataset_freshness VALUES(
          'MOLIT_TRANSACTIONS','READY',
          '{"expectedDistrictCount":25,"completeMonthCount":2,"excludedMonthCount":0}'
        )`,
        ...partitions,
        `INSERT INTO serving_molit_current_transactions VALUES
          ('aug','aug-hash','11680','강남구','역삼동','업무시설','3301','100,000','2026','8','15'),
          ('sep','sep-hash','11680','강남구','삼성동','업무시설','3301','999,000','2026','9','1')`,
      ], "write");
      const boundarySql = quantitativeMarketPulseSql.replaceAll(
        "'now'", "'2026-08-31T15:30:00Z'",
      );
      const result = await getQuantitativeMarketPulse(async () => {
        const query = await client.execute(boundarySql);
        return {
          rows: query.rows.map((row) => ({
            payload: JSON.parse(String(row.payload)) as unknown,
          })),
        };
      });
      expect(result.asOfPeriod).toBe("2026-08");
      expect(result.trend.at(-1)?.period).toBe("2026-08");
      expect(result.concentration.topGroups[0]?.dealDate).toBe("2026-08-15");
    } finally {
      client.close();
    }
  });

  it("contains only SQLite and Turso-compatible SQL primitives", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    await getQuantitativeMarketPulse(execute);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("json_group_array(json_object(");
    expect(sql).toContain("strftime('%Y-%m-%dT%H:%M:%fZ','now')");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|DISTINCT ON|clock_timestamp|AT TIME ZONE|date_trunc|to_char\s*\(|generate_series|\bLATERAL\b|interval\s|make_date|concat_ws|btrim|->>|!~|\s~\s/i);
  });

  it("preserves independently rounded two-decimal top shares", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    await getQuantitativeMarketPulse(execute);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("'sharePct',round(share_pct,2)");
    expect(sql).toContain("FROM (SELECT * FROM ranked_transactions WHERE amount_rank<=5 ORDER BY amount_rank)");
    expect(sql).not.toContain("displayed_share_total");
  });
});

describe("getQuantitativeMarketPulse calculations", () => {
  it("uses the zero-filled prior calendar month and complete prior-year YTD window", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    const result = await getQuantitativeMarketPulse(execute);
    expect(result.asOfPeriod).toBe("2026-07");
    expect(result.metrics.amount.previousValue).toBe(0);
    expect(result.metrics.amount.momPct).toBeNull();
    expect(result.metrics.amount.yearAgoValue).toBe(400);
    expect(result.metrics.amount.yoyPct).toBe(50);
    expect(result.metrics.amount.ytdValue).toBe(900);
    expect(result.metrics.amount.priorYtdValue).toBe(500);
    expect(result.metrics.amount.ytdYoyPct).toBe(80);
    expect(result.trend).toHaveLength(19);
    expect(result.quality).toEqual({ sourceRowCount: 3, transactionCount: 2, uniquePayloadCount: 2, exactDuplicateRows: 1 });
  });

  it("does not compare a coverage gap as the prior month", async () => {
    const gapped = payload.analysisTrend.filter((point) => point.period !== "2026-06");
    const withoutJune = { ...payload, analysisTrend: gapped, trend: gapped, coverage: { ...payload.coverage, returnedMonthCount: gapped.length } };
    const result = await getQuantitativeMarketPulse(vi.fn().mockResolvedValue({ rows: [{ payload: withoutJune }] }));
    expect(result.metrics.amount.previousValue).toBeNull();
    expect(result.metrics.amount.momPct).toBeNull();
  });

  it("leaves comparisons unavailable when only one complete month is verified", async () => {
    const latest = {
      period: "2026-08", transactionCount: 1, amountKrw: "100", areaM2: "10",
      sourceRowCount: 1, uniquePayloadCount: 1,
    };
    const oneMonth = {
      ...payload,
      asOfPeriod: "2026-08",
      analysisTrend: [latest],
      trend: [latest],
      latestGroups: [{ rank: 1, dealDate: "2026-08-15", district: "강남구", locality: "역삼동", buildingUse: "업무", amountKrw: "100", areaM2: "10", sharePct: 100 }],
      districts: [{ district: "강남구", transactionCount: 1, amountKrw: "100", areaM2: "10", sharePct: 100 }],
      coverage: { expectedDistrictCount: 25, observedMonthCount: 20, completeMonthCount: 1, returnedMonthCount: 1, excludedMonthCount: 19, coverageComplete: false },
    };
    const result = await getQuantitativeMarketPulse(vi.fn().mockResolvedValue({ rows: [{ payload: oneMonth }] }));
    expect(result.metrics.amount.previousValue).toBeNull();
    expect(result.metrics.amount.yearAgoValue).toBeNull();
    expect(result.metrics.amount.momPct).toBeNull();
    expect(result.metrics.amount.yoyPct).toBeNull();
    expect(result.metrics.amount.ytdValue).toBeNull();
    expect(result.metrics.amount.priorYtdValue).toBeNull();
    expect(result.metrics.amount.ytdYoyPct).toBeNull();
    expect(result.call.detail).toContain("검증 완료 1개월만 표시");
    expect(result.call.caution).toContain("25개 자치구 기준선");
  });

  it("fails closed before deriving metrics from malformed database payloads", async () => {
    const malformed = { ...payload, trend: payload.trend.map((point, index) => index === 0 ? { ...point, amountKrw: "not-a-number" } : point) };
    await expect(getQuantitativeMarketPulse(vi.fn().mockResolvedValue({ rows: [{ payload: malformed }] }))).rejects.toThrow(/Invalid/);
  });

  it("accepts mathematically valid two-decimal shares that independently total 100.01", async () => {
    const result = await getQuantitativeMarketPulse(vi.fn().mockResolvedValue({ rows: [{ payload: concentrationRoundingPayload }] }));
    expect(result.concentration.topGroups).toHaveLength(4);
    expect(result.concentration.topGroups.reduce((sum, item) => sum + item.sharePct, 0)).toBeCloseTo(100.01, 8);
  });
});

describe("buildMarketHeadline", () => {
  it.each([
    [1, 1, "전월 대비 증가"], [1, 0, "신고 거래금액 증가 · 고유 신고행 보합"], [1, -1, "신고 거래금액 증가 · 고유 신고행 감소"],
    [0, 1, "신고 거래금액 보합 · 고유 신고행 증가"], [0, 0, "전월 대비 보합"], [0, -1, "신고 거래금액 보합 · 고유 신고행 감소"],
    [-1, 1, "신고 거래금액 감소 · 고유 신고행 증가"], [-1, 0, "신고 거래금액 감소 · 고유 신고행 보합"], [-1, -1, "전월 대비 감소"],
  ])("describes amount %s and count %s without collapsing mixed directions", (amount, count, phrase) => {
    expect(buildMarketHeadline(amount, count)).toContain(phrase);
  });

  it("treats changes that round to 0.0% as flat", () => {
    expect(buildMarketHeadline(0.04, -0.04)).toContain("전월 대비 보합");
  });

  it("states when either comparison is unavailable", () => {
    expect(buildMarketHeadline(null, -1)).toContain("전월 비교 불가");
    expect(buildMarketHeadline(1, null)).toContain("전월 비교 불가");
  });
});
