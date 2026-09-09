import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProcessDataCacheOverloadError } from "@/lib/server/bounded-data-cache";

const mocks = vi.hoisted(() => ({ getCachedEvidenceSearch: vi.fn() }));
vi.mock("@/lib/server/market-data-cache", () => ({
  getCachedEvidenceSearch: mocks.getCachedEvidenceSearch,
}));

import { POST } from "@/app/api/evidence-search/route";

const responsePayload = {
  datasetVersion: "dataset-v1",
  query: "매각",
  generatedAt: "2026-09-09T00:00:00Z",
  filters: { from: null, to: null, topic: null },
  returned: 0,
  truncated: false,
  maxResults: 8,
  items: [],
};

function request(body: unknown, headers: Record<string, string> = {}) {
  return new Request("https://dashboard.example/api/evidence-search", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

describe("POST /api/evidence-search", () => {
  beforeEach(() => {
    mocks.getCachedEvidenceSearch.mockReset().mockResolvedValue(responsePayload);
  });

  it("returns a private response from the bounded cache service", async () => {
    const response = await POST(request({ q: " 매각 ", topK: 8 }));

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("server-timing")).toMatch(/^data;dur=/u);
    expect(mocks.getCachedEvidenceSearch).toHaveBeenCalledWith({
      q: "매각", from: null, to: null, topic: null, topK: 8,
    });
  });

  it("accepts the browser origin derived from Host when Next uses an internal localhost URL", async () => {
    const response = await POST(new Request("http://localhost:3015/api/evidence-search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Host: "127.0.0.1:3015",
        Origin: "http://127.0.0.1:3015",
      },
      body: JSON.stringify({ q: "매각", topK: 8 }),
    }));
    expect(response.status).toBe(200);
    expect(mocks.getCachedEvidenceSearch).toHaveBeenCalledOnce();
  });

  it("rejects invalid, oversized, and cross-origin requests before a data call", async () => {
    expect((await POST(request({ q: "매" }))).status).toBe(400);
    expect((await POST(request({ q: "매각" }, { "Content-Length": "5000" }))).status).toBe(400);
    expect((await POST(request({ q: "매각" }, { Origin: "https://attacker.example" }))).status).toBe(403);
    expect(mocks.getCachedEvidenceSearch).not.toHaveBeenCalled();
  });

  it("returns an explicit retryable overload response", async () => {
    mocks.getCachedEvidenceSearch.mockRejectedValue(new ProcessDataCacheOverloadError(64));
    const response = await POST(request({ q: "매각" }));
    expect(response.status).toBe(503);
    expect(response.headers.get("retry-after")).toBe("1");
    expect(await response.json()).toMatchObject({ code: "DATA_CACHE_OVERLOADED" });
  });
});
