import { describe, expect, it } from "vitest";
import { normalizeMacroTimeseries } from "@/lib/macro-timeseries-contract";

const fixture = {
  generatedAt: "2026-09-02T06:00:00.000Z",
  availableFrom: "2000-01",
  availableThrough: "2026-09",
  completeThrough: "2026-08",
  series: [
    { code: "BOK_BASE_RATE_MONTHLY", name: "한국은행 기준금리", group: "KOREA", source: "한국은행 ECOS", unit: "PERCENT", validFrom: "2000-01-01", sourceVintageAt: "2026-09-02T05:50:29.000Z", points: [
      { month: "2026-07", value: 3.25, observationCount: 1, partial: false },
      { month: "2026-08", value: 3, observationCount: 1, partial: false },
    ] },
  ],
};

describe("normalizeMacroTimeseries", () => {
  it("accepts ordered monthly official observations", () => {
    const result = normalizeMacroTimeseries(fixture);
    expect(result.series[0].points.at(-1)?.value).toBe(3);
    expect(result.completeThrough).toBe("2026-08");
  });

  it("rejects duplicate series and invalid partial-month flags", () => {
    expect(() => normalizeMacroTimeseries({ ...fixture, series: [...fixture.series, fixture.series[0]] })).toThrow();
    const bad = structuredClone(fixture);
    bad.series[0].points[0].partial = true;
    expect(() => normalizeMacroTimeseries(bad)).toThrow();
  });
});
