import { describe, expect, it, vi } from "vitest";
import { runContextualSearchRequest } from "@/lib/server/contextual-search-route";
import type { SqlExecutor } from "@/lib/server/market-search";

describe("GET /api/contextual-search", () => {
  it("returns approved default mode with no connection details", async () => {
    const execute: SqlExecutor = vi.fn().mockResolvedValue({
      rows: [{ payload: { total: 0, facets: {}, results: [] } }],
    });
    const response = await runContextualSearchRequest(
      new Request("http://localhost/api/contextual-search?q=용인"),
      execute,
      () => 12,
      () => new Date("2026-09-03T03:00:00Z"),
    );
    const body = await response.json();
    expect(response.status).toBe(200);
    expect(body.request.mode).toBe("APPROVED");
    expect(body.database).toBe("turso-libsql");
    expect(body.generatedAt).toBe("2026-09-03T03:00:00.000Z");
    expect(JSON.stringify(body)).not.toContain("TURSO_DATABASE_URL");
    expect(JSON.stringify(body)).not.toContain("TURSO_AUTH_TOKEN");
  });
});
