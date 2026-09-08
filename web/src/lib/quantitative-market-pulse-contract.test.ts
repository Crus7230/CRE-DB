import { describe, expect, it } from "vitest";
import { normalizeQuantitativeMarketPulse } from "@/lib/quantitative-market-pulse-contract";

const metric = (value: number, previousValue: number | null, yearAgoValue: number | null, momPct: number | null, yoyPct: number | null, ytdValue: number | null, priorYtdValue: number | null, ytdYoyPct: number | null) => ({ value, previousValue, yearAgoValue, momPct, yoyPct, ytdValue, priorYtdValue, ytdYoyPct });

const trend = Array.from({ length: 19 }, (_, index) => {
  const month = new Date(Date.UTC(2025, index, 1));
  return {
    period: `${month.getUTCFullYear()}-${String(month.getUTCMonth() + 1).padStart(2, "0")}`,
    transactionCount: index === 18 ? 3 : 0,
    amountKrw: index === 18 ? "600" : "0",
    areaM2: index === 18 ? "60" : "0",
    sourceRowCount: index === 18 ? 4 : 0,
    uniquePayloadCount: index === 18 ? 3 : 0,
  };
});

const valid = {
  generatedAt: "2026-08-31T02:00:00.000Z",
  asOfPeriod: "2026-07",
  call: { headline: "거래금액 증가 · 거래건수 감소", detail: "금액 +20.0%", caution: "동일자산 가격지수가 아님" },
  metrics: {
    amount: metric(600, 0, 400, null, 50, 900, 500, 80),
    count: metric(3, 0, 4, null, -25, 6, 6, 0),
    area: metric(60, 0, 40, null, 50, 90, 50, 80),
    averageTicket: { value: 200, previousValue: null, yearAgoValue: 100, momPct: null, yoyPct: 100 },
    unitAmount: { value: 10, previousValue: null, yearAgoValue: 10, momPct: null, yoyPct: 0 },
  },
  trend,
  concentration: {
    topGroups: [
      { rank: 1, dealDate: "2026-07-16", district: "강남구", locality: "역삼동", buildingUse: "업무", amountKrw: "300", areaM2: "30", sharePct: 50 },
      { rank: 2, dealDate: "2026-07-17", district: "강남구", locality: "삼성동", buildingUse: "판매", amountKrw: "200", areaM2: "20", sharePct: 33.33 },
      { rank: 3, dealDate: "2026-07-18", district: "서초구", locality: "서초동", buildingUse: "업무", amountKrw: "100", areaM2: "10", sharePct: 16.67 },
    ],
    districts: [
      { district: "강남구", transactionCount: 2, amountKrw: "400", areaM2: "40", sharePct: 66.67 },
      { district: "서초구", transactionCount: 1, amountKrw: "200", areaM2: "20", sharePct: 33.33 },
    ],
  },
  quality: { sourceRowCount: 4, transactionCount: 3, uniquePayloadCount: 3, exactDuplicateRows: 1 },
  scope: { geography: "서울특별시", source: "국토교통부 실거래 공개시스템", population: "비주거용 부동산 실거래", areaRule: "개별 API 행 건물면적 > 3,300㎡", exclusions: ["취소 신고"], amountBasis: "보수적 canonical payload 행 기준" },
};

const replace = (path: string, value: unknown) => {
  const copy = structuredClone(valid) as Record<string, unknown>;
  const keys = path.split(".");
  let target = copy;
  for (const key of keys.slice(0, -1)) target = target[key] as Record<string, unknown>;
  target[keys.at(-1)!] = value;
  return copy;
};

describe("normalizeQuantitativeMarketPulse", () => {
  it("accepts a complete decision-grade payload including a zero-transaction month", () => {
    expect(normalizeQuantitativeMarketPulse(valid)).toEqual(valid);
  });

  it("allows the bounded overshoot from independently rounding top shares to two decimals", () => {
    const independentlyRounded = structuredClone(valid);
    independentlyRounded.concentration.topGroups = independentlyRounded.concentration.topGroups.map((item, index) => ({
      ...item,
      amountKrw: ["400", "100", "100"][index],
      sharePct: [66.67, 16.67, 16.67][index],
    }));
    expect(independentlyRounded.concentration.topGroups.reduce((sum, item) => sum + item.sharePct, 0)).toBeCloseTo(100.01, 8);
    expect(() => normalizeQuantitativeMarketPulse(independentlyRounded)).not.toThrow();
  });

  it("accepts unavailable YTD values only without a derived comparison", () => {
    const incomplete = structuredClone(valid);
    incomplete.metrics.amount = metric(600, 0, 400, null, 50, null, null, null);
    expect(normalizeQuantitativeMarketPulse(incomplete).metrics.amount.ytdValue).toBeNull();
    incomplete.metrics.amount.ytdYoyPct = 80;
    expect(() => normalizeQuantitativeMarketPulse(incomplete)).toThrow(/ytdYoyPct/i);
  });

  it.each([
    ["generatedAt", "2026-08-31"],
    ["asOfPeriod", "July"],
    ["trend.0.amountKrw", "not-a-number"],
    ["trend.0.amountKrw", "1"],
    ["trend.0.areaM2", "1e3"],
    ["trend.0.transactionCount", 1.5],
    ["trend.0.sourceRowCount", -1],
    ["concentration.topGroups.0.dealDate", "2026-02-30"],
    ["concentration.topGroups.0.rank", 0],
    ["concentration.topGroups.0.sharePct", 100.1],
    ["concentration.districts.0.sharePct", -0.1],
  ])("rejects invalid runtime field %s", (path, value) => {
    expect(() => normalizeQuantitativeMarketPulse(replace(path, value))).toThrow(/Invalid/);
  });

  it("allows 1 to 19 strictly ordered observed months, including coverage gaps", () => {
    expect(() => normalizeQuantitativeMarketPulse({ ...valid, trend: valid.trend.slice(1) })).not.toThrow();
    expect(() => normalizeQuantitativeMarketPulse({ ...valid, trend: [] })).toThrow(/arrays/i);
    expect(() => normalizeQuantitativeMarketPulse({ ...valid, trend: [valid.trend[1], valid.trend[0], ...valid.trend.slice(2)] })).toThrow(/period/i);
    expect(() => normalizeQuantitativeMarketPulse({ ...valid, trend: [valid.trend[0], valid.trend[0], ...valid.trend.slice(2)] })).toThrow(/period/i);
    const twentyValidMonths = Array.from({ length: 20 }, (_, index) => {
      const month = new Date(Date.UTC(2025, index, 1));
      return { ...valid.trend[0], period: `${month.getUTCFullYear()}-${String(month.getUTCMonth() + 1).padStart(2, "0")}` };
    });
    expect(() => normalizeQuantitativeMarketPulse({ ...valid, trend: twentyValidMonths })).toThrow(/arrays/i);
  });

  it("enforces canonical count and quality invariants", () => {
    expect(() => normalizeQuantitativeMarketPulse(replace("trend.1.uniquePayloadCount", 1))).toThrow(/count|quality/i);
    expect(() => normalizeQuantitativeMarketPulse(replace("quality.exactDuplicateRows", 2))).toThrow(/count|quality/i);
    expect(() => normalizeQuantitativeMarketPulse(replace("quality.transactionCount", 1))).toThrow(/count|quality/i);
    expect(() => normalizeQuantitativeMarketPulse(replace("metrics.count.value", 1))).toThrow(/count|quality/i);
  });

  it("requires concentration to match whether the reference month has transactions", () => {
    expect(() => normalizeQuantitativeMarketPulse({ ...valid, concentration: { topGroups: [], districts: [] } })).toThrow(/concentration/i);
    expect(() => normalizeQuantitativeMarketPulse({
      ...valid,
      concentration: { ...valid.concentration, topGroups: valid.concentration.topGroups.slice(0, 2) },
    })).toThrow(/concentration/i);
    const zero = structuredClone(valid);
    zero.trend[18] = { period: "2026-07", transactionCount: 0, amountKrw: "0", areaM2: "0", sourceRowCount: 0, uniquePayloadCount: 0 };
    zero.metrics.amount = metric(0, 10, 5, -100, -100, 0, 5, -100);
    zero.metrics.count = metric(0, 1, 1, -100, -100, 0, 1, -100);
    zero.metrics.area = metric(0, 10, 5, -100, -100, 0, 5, -100);
    zero.metrics.averageTicket = { value: null, previousValue: 10, yearAgoValue: 5, momPct: null, yoyPct: null } as never;
    zero.metrics.unitAmount = { value: null, previousValue: 1, yearAgoValue: 1, momPct: null, yoyPct: null } as never;
    zero.quality = { sourceRowCount: 0, transactionCount: 0, uniquePayloadCount: 0, exactDuplicateRows: 0 };
    expect(() => normalizeQuantitativeMarketPulse(zero)).toThrow(/concentration/i);
    expect(normalizeQuantitativeMarketPulse({ ...zero, concentration: { topGroups: [], districts: [] } }).concentration.districts).toEqual([]);
  });

  it.each([
    ["top-group shares total more than 100%", () => {
      const malformed = structuredClone(valid);
      malformed.concentration.topGroups.forEach((item) => { item.sharePct = 100; });
      return malformed;
    }],
    ["top groups are not sorted by amount descending", () => {
      const malformed = structuredClone(valid);
      malformed.concentration.topGroups = [...malformed.concentration.topGroups].reverse().map((item, index) => ({ ...item, rank: index + 1 }));
      return malformed;
    }],
    ["an individual top-group share does not match its amount", () => {
      const malformed = structuredClone(valid);
      malformed.concentration.topGroups[0].sharePct = 40;
      malformed.concentration.topGroups[1].sharePct = 43.33;
      return malformed;
    }],
    ["top-group amount and share totals exceed the reference month", () => {
      const malformed = structuredClone(valid);
      malformed.concentration.topGroups = malformed.concentration.topGroups.map((item, index) => ({
        ...item,
        amountKrw: ["400", "300", "200"][index],
        sharePct: [66.67, 50, 33.33][index],
      }));
      return malformed;
    }],
    ["district shares are swapped relative to their amounts", () => {
      const malformed = structuredClone(valid);
      [malformed.concentration.districts[0].sharePct, malformed.concentration.districts[1].sharePct] = [
        malformed.concentration.districts[1].sharePct,
        malformed.concentration.districts[0].sharePct,
      ];
      return malformed;
    }],
  ])("rejects malformed concentration when %s", (_label, makeMalformed) => {
    expect(() => normalizeQuantitativeMarketPulse(makeMalformed())).toThrow(/concentration|topGroups|districts/i);
  });
});
