import { describe, expect, it, vi } from "vitest";
import { getMacroTimeseries } from "@/lib/server/macro-timeseries";

const codes = [
  "BOK_BASE_RATE_MONTHLY", "KR_CD_91D", "KR_GOVT_BOND_3Y", "KR_GOVT_BOND_10Y", "KR_CORP_BOND_AA_MINUS_3Y",
  "US_FED_TARGET_LOWER", "US_FED_TARGET_UPPER", "US_EFFR", "US_SOFR",
  "US_TREASURY_2Y", "US_TREASURY_10Y", "US_TREASURY_30Y", "US_TREASURY_10Y_MINUS_2Y",
];
const payload = {
  generatedAt: "2026-09-02T06:00:00.000Z", availableFrom: "2026-08", availableThrough: "2026-08", completeThrough: "2026-08",
  series: codes.map((code, index) => ({
    code, name: code, group: index < 5 ? "KOREA" : index < 9 ? "US_POLICY" : "US_TREASURY", source: "공식기관", unit: "PERCENT", validFrom: "2000-01-01", sourceVintageAt: "2026-09-02T05:00:00Z",
    points: [{ month: "2026-08", value: index / 10, observationCount: 20, partial: false }],
  })),
};
const executor = (value: unknown) => vi.fn(async (...args: [string, readonly (string | number | boolean | null)[]]) => { void args; return { rows: [{ payload: value }] }; });

describe("getMacroTimeseries", () => {
  it("reads the compact monthly serving table and validates all 13 canonical series", async () => {
    const execute = executor(payload);
    const result = await getMacroTimeseries(execute);
    expect(result.series).toHaveLength(13);
    expect(execute).toHaveBeenCalledOnce();
    expect(execute.mock.calls[0][0]).toContain("financial_macro_monthly_serving");
    expect(execute.mock.calls[0][0]).toContain("date('now','+9 hours','start of month','-1 month')");
    expect(execute.mock.calls[0][0]).toContain("json(CASE WHEN point.observation_month>point.complete_through THEN 'true'");
    expect(execute.mock.calls[0][0]).toContain("FROM series_rows point");
    expect(execute.mock.calls[0][0]).toContain("ORDER BY point.observation_month");
    expect(execute.mock.calls[0][0]).toContain("FROM series_payload ordered_series");
    expect(execute.mock.calls[0][0]).not.toContain(") ORDER BY f.observation_month");
    expect(execute.mock.calls[0][0]).not.toContain("json(sp.series) ORDER BY");
    expect(execute.mock.calls[0][0]).not.toMatch(/market_intelligence\.|::|jsonb_|date_trunc|clock_timestamp|\binterval\b|AT TIME ZONE/i);
  });

  it("fails closed when any canonical series is missing", async () => {
    await expect(getMacroTimeseries(executor({ ...payload, series: payload.series.slice(0, -1) }))).rejects.toThrow("Incomplete macro series registry");
  });
});
