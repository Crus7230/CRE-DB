import { describe, expect, it, vi } from "vitest";
import {
  localEvidenceSearchSql,
  searchLocalArticleEvidence,
} from "@/lib/server/evidence-search";

describe("local article evidence search", () => {
  it("queries only the compact news projection with literal matching and a hard limit", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload: {
      datasetVersion: "local-v1",
      query: "매각",
      generatedAt: "2026-09-09T01:00:00.000Z",
      returned: 1,
      truncated: false,
      items: [{
        documentId: "doc-1", title: "오피스 매각", publisher: "뉴스",
        publishedAt: "2026-09-08T00:00:00Z", href: "https://example.com/1",
        evidenceText: "오피스 매각 기사", score: 1,
      }],
    } }] });
    const request = {
      q: "매각", from: "2026-09-01", to: "2026-09-09", topic: "SALE", topK: 8,
    } as const;

    const result = await searchLocalArticleEvidence(
      execute,
      request,
      "local-v1",
      () => new Date("2026-09-09T01:00:00.000Z"),
    );

    expect(result.items).toHaveLength(1);
    expect(execute).toHaveBeenCalledWith(localEvidenceSearchSql, [
      "매각", "2026-09-01", "2026-09-09", "SALE", 8,
      "local-v1", "2026-09-09T01:00:00.000Z",
    ]);
    expect(localEvidenceSearchSql).toContain("serving_daily_articles");
    expect(localEvidenceSearchSql).toContain("LIMIT $5 + 1");
    expect(localEvidenceSearchSql).toContain("count(*) FROM candidates)>$5");
    expect(localEvidenceSearchSql).toContain("instr(lower(article.title),lower($1))");
    expect(localEvidenceSearchSql).not.toContain("contextual_search_records");
  });

  it("rejects a payload returned for another snapshot", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload: {
      datasetVersion: "old-v0", query: "매각", generatedAt: "2026-09-09T01:00:00Z",
      returned: 0, truncated: false, items: [],
    } }] });
    await expect(searchLocalArticleEvidence(execute, {
      q: "매각", from: null, to: null, topic: null, topK: 8,
    }, "local-v1")).rejects.toThrow(/version mismatch/u);
  });
});
