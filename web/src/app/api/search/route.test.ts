import { describe, expect, it, vi } from "vitest";
import { runSearchRequest } from "@/lib/server/search-route";
import type { SqlExecutor } from "@/lib/server/market-search";

describe("GET /api/search", () => {
  it("returns a Supabase-backed search response without exposing connection details", async () => {
    const executor: SqlExecutor = vi.fn().mockResolvedValue({
      rows: [{ payload: { total: 0, facets: {}, results: [] } }],
    });
    const response = await runSearchRequest(
      new Request("http://localhost/api/search?q=용인&kind=EVENT"),
      executor,
      () => 42,
      () => new Date("2026-08-18T03:00:00Z"),
    );
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.request.q).toBe("용인");
    expect(body.database).toBe("supabase-postgresql");
    expect(body.elapsedMs).toBe(42);
    expect(body.generatedAt).toBe("2026-08-18T03:00:00.000Z");
    expect(JSON.stringify(body)).not.toContain("SUPABASE_DB_URL");
  });
});
