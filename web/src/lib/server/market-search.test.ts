import { describe, expect, it, vi } from "vitest";
import { searchMarket, type SqlExecutor } from "@/lib/server/market-search";
import type { SearchRequest } from "@/lib/search-contract";

const request: SearchRequest = {
  q: "데이터센터",
  kind: "ALL",
  category: "PF",
  from: null,
  to: null,
  page: 1,
  pageSize: 20,
  includeTransactionsUnder1000Eok: false,
};

describe("searchMarket", () => {
  it("returns normalized results and facets from one parameterized query", async () => {
    const executor: SqlExecutor = vi.fn().mockResolvedValue({
      rows: [
        {
          payload: {
            total: 1,
            facets: { EVENT: 1 },
            results: [
              {
                kind: "EVENT",
                id: "evt-1",
                title: "용인 데이터센터 PF",
                subtitle: "PF · MAIN_PF_COMMITTED",
                summary: "대주단 약정",
                date: "2026-08-13",
                status: "ACTIVE",
                confidence: 0.81,
                source: "canonical event",
                href: null,
                category: "PF",
                categoryLabel: "PF",
                metadata: { asset: "용인 남사 데이터센터" },
              },
            ],
          },
        },
      ],
    });

    const response = await searchMarket(executor, request);

    expect(response.total).toBe(1);
    expect(response.facets.EVENT).toBe(1);
    expect(response.facets.DOCUMENT).toBe(0);
    expect(response.results[0].title).toBe("용인 데이터센터 PF");
    expect(executor).toHaveBeenCalledTimes(1);
    const [sql, values] = vi.mocked(executor).mock.calls[0];
    expect(sql).not.toContain("데이터센터");
    expect(sql).toContain("latest_documents AS");
    expect(sql).not.toContain("SELECT DISTINCT ON (document_id) *");
    expect(sql).not.toContain("dv.stored_text");
    expect(sql).not.toContain("JOIN LATERAL (\n    SELECT *\n    FROM market_intelligence.document_versions");
    expect(values).toEqual(["데이터센터", "ALL", null, null, 20, 0, "PF", false]);
  });
});
