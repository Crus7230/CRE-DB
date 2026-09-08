export type ComparisonMetric = {
  value: number;
  previousValue: number | null;
  yearAgoValue: number | null;
  momPct: number | null;
  yoyPct: number | null;
  ytdValue: number | null;
  priorYtdValue: number | null;
  ytdYoyPct: number | null;
};

export type PointMetric = {
  value: number | null;
  previousValue: number | null;
  yearAgoValue: number | null;
  momPct: number | null;
  yoyPct: number | null;
};

export type QuantitativeMarketPulse = {
  generatedAt: string;
  asOfPeriod: string;
  call: { headline: string; detail: string; caution: string };
  metrics: { amount: ComparisonMetric; count: ComparisonMetric; area: ComparisonMetric; averageTicket: PointMetric; unitAmount: PointMetric };
  trend: Array<{ period: string; transactionCount: number; amountKrw: string; areaM2: string; sourceRowCount: number; uniquePayloadCount: number }>;
  concentration: {
    topGroups: Array<{ rank: number; dealDate: string; district: string; locality: string; buildingUse: string; amountKrw: string; areaM2: string; sharePct: number }>;
    districts: Array<{ district: string; transactionCount: number; amountKrw: string; areaM2: string; sharePct: number }>;
  };
  quality: { sourceRowCount: number; transactionCount: number; uniquePayloadCount: number; exactDuplicateRows: number };
  scope: { geography: string; source: string; population: string; areaRule: string; exclusions: string[]; amountBasis: string };
};

const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, label: string) => { if (typeof value !== "string" || value.trim() === "") throw new Error(`Invalid ${label}`); return value; };
const finite = (value: unknown, label: string) => { if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`Invalid ${label}`); return value; };
const nonnegative = (value: unknown, label: string) => { const result = finite(value, label); if (result < 0) throw new Error(`Invalid ${label}`); return result; };
const integer = (value: unknown, label: string, minimum = 0) => { const result = nonnegative(value, label); if (!Number.isInteger(result) || result < minimum) throw new Error(`Invalid ${label}`); return result; };
const nullableFinite = (value: unknown, label: string) => value === null ? null : finite(value, label);
const nullableNonnegative = (value: unknown, label: string) => value === null ? null : nonnegative(value, label);
const period = (value: unknown, label: string) => { const result = text(value, label); if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(result)) throw new Error(`Invalid ${label}`); return result; };
const decimalText = (value: unknown, label: string) => { const result = text(value, label); if (!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(result) || !Number.isFinite(Number(result))) throw new Error(`Invalid ${label}`); return result; };
const share = (value: unknown, label: string) => { const result = finite(value, label); if (result < 0 || result > 100) throw new Error(`Invalid ${label}`); return result; };
const timestamp = (value: unknown, label: string) => {
  const result = text(value, label);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(result) || Number.isNaN(Date.parse(result))) throw new Error(`Invalid ${label}`);
  return result;
};
const date = (value: unknown, label: string) => {
  const result = text(value, label);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result) || new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result) throw new Error(`Invalid ${label}`);
  return result;
};
const close = (actual: number, expected: number, tolerance = Math.max(0.1, Math.abs(expected) * 1e-9)) => Math.abs(actual - expected) <= tolerance;
const sqlRoundedShareTolerance = 0.005000001;
const matchesSqlRoundedShare = (actual: number, amount: number, total: number) => total > 0 && Math.abs(actual - amount / total * 100) <= sqlRoundedShareTolerance;
const expectedPct = (value: number, comparison: number | null) => comparison === null || comparison === 0 ? null : (value / comparison - 1) * 100;
const assertPct = (actual: number | null, value: number, comparison: number | null, label: string) => {
  const expected = expectedPct(value, comparison);
  if ((expected === null) !== (actual === null) || (expected !== null && actual !== null && !close(actual, expected, 0.11))) throw new Error(`Invalid ${label} comparison`);
};

function comparison(value: unknown, label: string, countMetric = false): ComparisonMetric {
  if (!record(value)) throw new Error(`Invalid ${label}`);
  const result = {
    value: countMetric ? integer(value.value, `${label}.value`) : nonnegative(value.value, `${label}.value`),
    previousValue: value.previousValue === null ? null : countMetric ? integer(value.previousValue, `${label}.previousValue`) : nonnegative(value.previousValue, `${label}.previousValue`),
    yearAgoValue: value.yearAgoValue === null ? null : countMetric ? integer(value.yearAgoValue, `${label}.yearAgoValue`) : nonnegative(value.yearAgoValue, `${label}.yearAgoValue`),
    momPct: nullableFinite(value.momPct, `${label}.momPct`),
    yoyPct: nullableFinite(value.yoyPct, `${label}.yoyPct`),
    ytdValue: value.ytdValue === null ? null : countMetric ? integer(value.ytdValue, `${label}.ytdValue`) : nonnegative(value.ytdValue, `${label}.ytdValue`),
    priorYtdValue: value.priorYtdValue === null ? null : countMetric ? integer(value.priorYtdValue, `${label}.priorYtdValue`) : nonnegative(value.priorYtdValue, `${label}.priorYtdValue`),
    ytdYoyPct: nullableFinite(value.ytdYoyPct, `${label}.ytdYoyPct`),
  };
  assertPct(result.momPct, result.value, result.previousValue, `${label}.momPct`);
  assertPct(result.yoyPct, result.value, result.yearAgoValue, `${label}.yoyPct`);
  if (result.ytdValue === null) {
    if (result.ytdYoyPct !== null) throw new Error(`Invalid ${label}.ytdYoyPct comparison`);
  } else {
    assertPct(result.ytdYoyPct, result.ytdValue, result.priorYtdValue, `${label}.ytdYoyPct`);
  }
  return result;
}

function point(value: unknown, label: string): PointMetric {
  if (!record(value)) throw new Error(`Invalid ${label}`);
  const result = {
    value: nullableNonnegative(value.value, `${label}.value`),
    previousValue: nullableNonnegative(value.previousValue, `${label}.previousValue`),
    yearAgoValue: nullableNonnegative(value.yearAgoValue, `${label}.yearAgoValue`),
    momPct: nullableFinite(value.momPct, `${label}.momPct`),
    yoyPct: nullableFinite(value.yoyPct, `${label}.yoyPct`),
  };
  if (result.value === null) {
    if (result.momPct !== null || result.yoyPct !== null) throw new Error(`Invalid ${label} comparison`);
  } else {
    assertPct(result.momPct, result.value, result.previousValue, `${label}.momPct`);
    assertPct(result.yoyPct, result.value, result.yearAgoValue, `${label}.yoyPct`);
  }
  return result;
}

export function normalizeQuantitativeMarketPulse(value: unknown): QuantitativeMarketPulse {
  if (!record(value) || !record(value.call) || !record(value.metrics) || !record(value.concentration) || !record(value.quality) || !record(value.scope)) throw new Error("Invalid market pulse");
  const call = value.call; const metrics = value.metrics; const concentration = value.concentration; const quality = value.quality; const scope = value.scope;
  const trendInput = value.trend; const topGroupsInput = concentration.topGroups; const districtsInput = concentration.districts; const exclusions = scope.exclusions;
  if (!Array.isArray(trendInput) || trendInput.length === 0 || trendInput.length > 19 || !Array.isArray(topGroupsInput) || !Array.isArray(districtsInput) || !Array.isArray(exclusions)) throw new Error("Invalid market pulse arrays");

  const trend = trendInput.map((item, index) => {
    if (!record(item)) throw new Error(`Invalid trend ${index}`);
    const result = {
      period: period(item.period, `trend.${index}.period`),
      transactionCount: integer(item.transactionCount, `trend.${index}.transactionCount`),
      amountKrw: decimalText(item.amountKrw, `trend.${index}.amountKrw`),
      areaM2: decimalText(item.areaM2, `trend.${index}.areaM2`),
      sourceRowCount: integer(item.sourceRowCount, `trend.${index}.sourceRowCount`),
      uniquePayloadCount: integer(item.uniquePayloadCount, `trend.${index}.uniquePayloadCount`),
    };
    if (result.transactionCount !== result.uniquePayloadCount || result.sourceRowCount < result.uniquePayloadCount) throw new Error(`Invalid trend.${index} count invariant`);
    const amountValue = Number(result.amountKrw);
    const areaValue = Number(result.areaM2);
    if (result.transactionCount === 0 ? amountValue !== 0 || areaValue !== 0 : amountValue <= 0 || areaValue <= 0) throw new Error(`Invalid trend.${index} fact invariant`);
    if (index > 0 && result.period <= period((trendInput[index - 1] as Record<string, unknown>).period, `trend.${index - 1}.period`)) throw new Error("Invalid trend period sequence");
    return result;
  });

  const topGroups = topGroupsInput.map((item, index) => {
    if (!record(item)) throw new Error(`Invalid topGroup ${index}`);
    const result = { rank: integer(item.rank, `topGroups.${index}.rank`, 1), dealDate: date(item.dealDate, `topGroups.${index}.dealDate`), district: text(item.district, `topGroups.${index}.district`), locality: text(item.locality, `topGroups.${index}.locality`), buildingUse: text(item.buildingUse, `topGroups.${index}.buildingUse`), amountKrw: decimalText(item.amountKrw, `topGroups.${index}.amountKrw`), areaM2: decimalText(item.areaM2, `topGroups.${index}.areaM2`), sharePct: share(item.sharePct, `topGroups.${index}.sharePct`) };
    if (result.rank !== index + 1) throw new Error("Invalid topGroups rank order");
    return result;
  });
  const districts = districtsInput.map((item, index) => {
    if (!record(item)) throw new Error(`Invalid district ${index}`);
    const result = { district: text(item.district, `districts.${index}.district`), transactionCount: integer(item.transactionCount, `districts.${index}.transactionCount`), amountKrw: decimalText(item.amountKrw, `districts.${index}.amountKrw`), areaM2: decimalText(item.areaM2, `districts.${index}.areaM2`), sharePct: share(item.sharePct, `districts.${index}.sharePct`) };
    if (index > 0 && Number(result.amountKrw) > Number((districtsInput[index - 1] as Record<string, unknown>).amountKrw)) throw new Error("Invalid districts sort order");
    return result;
  });

  const normalized = {
    generatedAt: timestamp(value.generatedAt, "generatedAt"), asOfPeriod: period(value.asOfPeriod, "asOfPeriod"),
    call: { headline: text(call.headline, "headline"), detail: text(call.detail, "detail"), caution: text(call.caution, "caution") },
    metrics: { amount: comparison(metrics.amount, "amount"), count: comparison(metrics.count, "count", true), area: comparison(metrics.area, "area"), averageTicket: point(metrics.averageTicket, "averageTicket"), unitAmount: point(metrics.unitAmount, "unitAmount") },
    trend,
    concentration: { topGroups, districts },
    quality: { sourceRowCount: integer(quality.sourceRowCount, "quality.sourceRowCount"), transactionCount: integer(quality.transactionCount, "quality.transactionCount"), uniquePayloadCount: integer(quality.uniquePayloadCount, "quality.uniquePayloadCount"), exactDuplicateRows: integer(quality.exactDuplicateRows, "quality.exactDuplicateRows") },
    scope: { geography: text(scope.geography, "geography"), source: text(scope.source, "source"), population: text(scope.population, "population"), areaRule: text(scope.areaRule, "areaRule"), exclusions: exclusions.map((item, index) => text(item, `exclusions.${index}`)), amountBasis: text(scope.amountBasis, "amountBasis") },
  } satisfies QuantitativeMarketPulse;

  const latest = trend.at(-1)!;
  if (normalized.asOfPeriod !== latest.period) throw new Error("Invalid asOfPeriod/trend invariant");
  if (normalized.metrics.count.value !== latest.transactionCount || !close(normalized.metrics.amount.value, Number(latest.amountKrw)) || !close(normalized.metrics.area.value, Number(latest.areaM2))) throw new Error("Invalid metric count invariant");
  if (normalized.quality.sourceRowCount !== latest.sourceRowCount || normalized.quality.transactionCount !== latest.transactionCount || normalized.quality.uniquePayloadCount !== latest.uniquePayloadCount || normalized.quality.transactionCount !== normalized.quality.uniquePayloadCount || normalized.quality.exactDuplicateRows !== normalized.quality.sourceRowCount - normalized.quality.uniquePayloadCount) throw new Error("Invalid quality count invariant");
  const hasTransactions = latest.transactionCount > 0;
  const expectedTopGroupCount = Math.min(5, latest.transactionCount);
  if (topGroups.length !== expectedTopGroupCount || (hasTransactions ? districts.length === 0 : districts.length !== 0)) throw new Error("Invalid concentration count invariant");
  if (districts.reduce((sum, item) => sum + item.transactionCount, 0) !== latest.transactionCount) throw new Error("Invalid concentration transaction count");
  const latestAmount = Number(latest.amountKrw);
  const districtAmountTotal = districts.reduce((sum, item) => sum + Number(item.amountKrw), 0);
  const districtAreaTotal = districts.reduce((sum, item) => sum + Number(item.areaM2), 0);
  if (!close(districtAmountTotal, latestAmount) || !close(districtAreaTotal, Number(latest.areaM2))) throw new Error("Invalid concentration totals");
  if (hasTransactions) {
    const topAmountTotal = topGroups.reduce((sum, item) => sum + Number(item.amountKrw), 0);
    const topShareTotal = topGroups.reduce((sum, item) => sum + item.sharePct, 0);
    if (topGroups.some((item, index) =>
      (index > 0 && Number(item.amountKrw) > Number(topGroups[index - 1].amountKrw))
      || !matchesSqlRoundedShare(item.sharePct, Number(item.amountKrw), latestAmount))) throw new Error("Invalid topGroups concentration");
    const maxIndependentlyRoundedShareTotal = 100 + sqlRoundedShareTolerance * topGroups.length;
    if (topAmountTotal > latestAmount || topShareTotal > maxIndependentlyRoundedShareTotal) throw new Error("Invalid topGroups concentration totals");
    if (!close(districts.reduce((sum, item) => sum + item.sharePct, 0), 100, 0.2)) throw new Error("Invalid concentration shares");
    if (districts.some((item) => !matchesSqlRoundedShare(item.sharePct, Number(item.amountKrw), latestAmount))) throw new Error("Invalid districts concentration shares");
    if (topGroups.some((item) => !item.dealDate.startsWith(normalized.asOfPeriod))) throw new Error("Invalid concentration date period");
  }
  return normalized;
}
