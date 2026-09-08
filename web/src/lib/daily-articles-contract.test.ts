import { describe, expect, it } from "vitest";
import { normalizeDailyArticles } from "@/lib/daily-articles-contract";

describe("normalizeDailyArticles", () => {
  it("normalizes optional intelligence fields without fabricating classifications", () => {
    const value = normalizeDailyArticles({
      selectedDate: "2026-08-29", latestAvailableDate: "2026-08-29", lastCollectedAt: null,
      generatedAt: "2026-08-29T00:00:00Z", total: 301, returned: 1,
      articles: [{
        id: "doc-1", title: "시장 기사", publisher: null,
        publishedAt: "2026-08-29T00:00:00Z", collectedAt: "2026-08-29T00:01:00Z",
        summary: null, summaryMode: "NONE", summaryGeneratedAt: null, href: null,
        topics: [{ key: "SALE", label: "매각", status: "CONFIRMED", provenance: "APPROVED_CLASSIFICATION" }],
      }],
    });
    expect(value.total).toBe(301);
    expect(value.returned).toBe(1);
    expect(value.articles[0].topics[0]).toMatchObject({ key: "SALE", provenance: "APPROVED_CLASSIFICATION" });
    expect(value.articles[0].evidenceGrade).toBeNull();
  });

  it("uses the article array length for older cached payloads without returned", () => {
    const value = normalizeDailyArticles({
      selectedDate: "2026-08-29", latestAvailableDate: "2026-08-29", lastCollectedAt: null,
      generatedAt: "2026-08-29T00:00:00Z", total: 1,
      articles: [{ id: "doc-1", title: "시장 기사", publisher: null, publishedAt: "2026-08-29T00:00:00Z", collectedAt: "2026-08-29T00:01:00Z", summary: null, summaryMode: "NONE", summaryGeneratedAt: null, href: null }],
    });
    expect(value.returned).toBe(1);
  });

  it("rejects a successful response with the wrong record shape", () => {
    expect(() => normalizeDailyArticles({ results: [], total: 0 })).toThrow("Invalid daily articles payload");
  });
});
