import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/server/market-data-cache", () => ({ getCachedMacroTimeseries: vi.fn() }));

import { loadMacroTimeseriesResponse } from "@/app/api/market/timeseries/route";
import { DATA_SERVER_UNAVAILABLE_MESSAGE } from "@/lib/server/api-response";

const codes = ["BOK_BASE_RATE_MONTHLY", "KR_CD_91D", "KR_GOVT_BOND_3Y", "KR_GOVT_BOND_10Y", "KR_CORP_BOND_AA_MINUS_3Y", "US_FED_TARGET_LOWER", "US_FED_TARGET_UPPER", "US_EFFR", "US_SOFR", "US_TREASURY_2Y", "US_TREASURY_10Y", "US_TREASURY_30Y", "US_TREASURY_10Y_MINUS_2Y"];
const payload = {
  generatedAt: "2026-09-02T06:00:00Z", availableFrom: "2026-08", availableThrough: "2026-08", completeThrough: "2026-08",
  series: codes.map((code, index) => ({ code, name: code, group: index < 5 ? "KOREA" : index < 9 ? "US_POLICY" : "US_TREASURY", source: "공식기관", unit: "PERCENT", validFrom: "2000-01-01", sourceVintageAt: "2026-09-02T05:00:00Z", points: [{ month: "2026-08", value: index, observationCount: 20, partial: false }] })),
};

describe("GET /api/market/timeseries", () => {
  it("returns a canonical synchronized payload with private caching", async () => {
    const response = await loadMacroTimeseriesResponse(async () => payload);
    expect(response.status).toBe(200);
    expect((await response.json()).series).toHaveLength(13);
    expect(response.headers.get("cache-control")).toContain("max-age=3600");
    expect(response.headers.get("server-timing")).toMatch(/^data;dur=/u);
  });

  it("fails closed on malformed or incomplete loader output", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await loadMacroTimeseriesResponse(async () => ({ ...payload, series: payload.series.slice(0, -1) }));
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: DATA_SERVER_UNAVAILABLE_MESSAGE,
      code: "MACRO_TIMESERIES_UNAVAILABLE",
    });
    consoleError.mockRestore();
  });

  it("fails closed without exposing database errors", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await loadMacroTimeseriesResponse(async () => { throw new Error("secret dsn"); });
    expect(response.status).toBe(503);
    const body = await response.json();
    expect(body).toEqual({
      error: DATA_SERVER_UNAVAILABLE_MESSAGE,
      code: "MACRO_TIMESERIES_UNAVAILABLE",
    });
    expect(JSON.stringify(body)).not.toContain("secret");
    consoleError.mockRestore();
  });
});
