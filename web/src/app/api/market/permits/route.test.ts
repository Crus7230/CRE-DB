import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { loadPermitTimeseriesResponse } from "@/app/api/market/permits/route";
import { DATA_SERVER_UNAVAILABLE_MESSAGE } from "@/lib/server/api-response";

const request = (query = "") => new Request(`http://localhost/api/market/permits${query}`);

describe("GET /api/market/permits", () => {
  it("returns a private cached response and passes the parsed filters", async () => {
    const loader = vi.fn(async () => ({ ok: true } as never));
    const response = await loadPermitTimeseriesResponse(
      request("?groupBy=DISTRICT&eventType=PERMIT&from=2025-01&to=2026-08"),
      loader,
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("max-age=21600");
    expect(response.headers.get("server-timing")).toMatch(/^data;dur=/u);
    expect(loader).toHaveBeenCalledWith(expect.objectContaining({
      groupBy: "DISTRICT", eventType: "PERMIT", from: "2025-01", to: "2026-08",
    }));
  });

  it("returns 400 before querying for a malformed dimension", async () => {
    const loader = vi.fn();
    const response = await loadPermitTimeseriesResponse(request("?groupBy=SOURCE"), loader);
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      error: "허가 통계 조회 조건이 올바르지 않습니다.",
      code: "INVALID_PERMIT_QUERY",
    });
    expect(loader).not.toHaveBeenCalled();
  });

  it("returns a sanitized infrastructure 503 without leaking provider details", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await loadPermitTimeseriesResponse(request(), async () => {
      throw Object.assign(new Error("secret token and SQL"), { code: "BLOCKED" });
    });
    const body = await response.json();
    expect(response.status).toBe(503);
    expect(body).toEqual({
      error: DATA_SERVER_UNAVAILABLE_MESSAGE,
      code: "PERMIT_TIMESERIES_UNAVAILABLE",
    });
    expect(JSON.stringify(body)).not.toMatch(/secret|Turso|SQL/u);
    consoleError.mockRestore();
  });
});
