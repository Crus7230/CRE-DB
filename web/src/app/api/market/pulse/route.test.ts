import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { loadMarketPulseResponse } from "@/app/api/market/pulse/route";
import { DATA_SERVER_UNAVAILABLE_MESSAGE } from "@/lib/server/api-response";

describe("GET /api/market/pulse", () => {
  it("returns the cached decision-grade market pulse", async () => {
    const response = await loadMarketPulseResponse(async () => ({ asOfPeriod: "2026-07", metrics: {} }));
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ asOfPeriod: "2026-07" });
    expect(response.headers.get("cache-control")).toContain("max-age=21600");
    expect(response.headers.get("server-timing")).toMatch(/^data;dur=/u);
  });

  it("fails closed without exposing database errors", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await loadMarketPulseResponse(async () => {
      throw Object.assign(new Error("secret dsn"), { code: "XX001" });
    });
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: DATA_SERVER_UNAVAILABLE_MESSAGE,
      code: "MARKET_PULSE_UNAVAILABLE",
    });
    expect(consoleError).toHaveBeenCalledWith("quantitative market pulse request failed", { name: "Error", code: "XX001" });
    consoleError.mockRestore();
  });
});
