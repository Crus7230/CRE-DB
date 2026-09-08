import { describe, expect, it, vi } from "vitest";
import { searchMarket, type SqlExecutor } from "@/lib/server/market-search";
import type { SearchRequest } from "@/lib/search-contract";

const request: SearchRequest = {
  q: "데이터센터",
  kind: "ALL",
  category: "MARKET_EVIDENCE",
  classificationScheme: "",
  from: null,
  to: null,
  page: 1,
  pageSize: 20,
  includeTransactionsUnder1000Eok: false,
};

describe("searchMarket", () => {
  it("returns the existing JSON contract from one parameterized libSQL query", async () => {
    const executor: SqlExecutor = vi.fn().mockResolvedValue({
      rows: [{
        payload: {
          total: 1,
          facets: { EVENT: 1 },
          results: [{
            kind: "EVENT", id: "evt-1", title: "데이터센터 PF", subtitle: "PF",
            summary: "대주단 확정", date: "2026-08-13", status: "ACTIVE",
            confidence: 0.81, source: "canonical event", href: null,
            category: "PF", categoryLabel: "PF", metadata: { evidenceCount: 3 },
          }],
        },
      }],
    });

    const response = await searchMarket(executor, request);

    expect(response.total).toBe(1);
    expect(response.facets.EVENT).toBe(1);
    expect(response.facets.DOCUMENT).toBe(0);
    expect(response.results[0].title).toBe("데이터센터 PF");
    expect(response.results[0].metadata.evidenceCount).toBe(3);
    expect(executor).toHaveBeenCalledTimes(1);

    const [sql, values] = vi.mocked(executor).mock.calls[0];
    expect(sql).not.toContain("데이터센터");
    expect(sql).toContain("ranked_documents AS");
    expect(sql).toContain("row_number() OVER");
    expect(sql).toContain("MARKET_EVIDENCE");
    expect(sql).toContain("document_scope_assessments");
    expect(sql).toContain("DART_CRE_SCOPE_RULE_V1");
    expect(sql).toContain("NEWS_CRE_SCOPE_RULE_V3");
    expect(sql).toContain("MOLIT_SCOPE_TIERED_V2");
    expect(sql).toContain("organization_scope_assessments");
    expect(sql).toContain("ORG_CRE_SCOPE_RULE_V1");
    expect(sql).toContain("archived_serving_index");
    expect(sql).toContain("record_classifications");
    expect(sql).toContain("rc.review_status='APPROVED'");
    expect(sql).toContain("rc.assignment_role<>'LEGACY_BACKFILL'");
    expect(sql).toContain("primary_market_category_code");
    expect(sql).toContain("primary_document_purpose_code");
    expect(sql).toContain("'ARCHIVED_LOCAL'");
    expect(sql).toContain("'archiveLocator'");
    expect(sql).toContain("ars.is_current=1 AND ars.integrity_status='VALIDATED'");
    expect(sql).toContain("ai.record_kind='EVENT' AND EXISTS");
    expect(sql).toContain("csc.scheme_code=$9");
    expect(sql).toContain("rc.valid_from IS NULL");
    expect(sql).toContain("ct.valid_to IS NULL");
    expect(sql).toContain("'documentPurposeCode',rcs.primary_document_purpose_code");
    expect(sql).toContain("FROM v_document_entity_relations relation");
    expect(sql).toContain("count(DISTINCT relation.document_id)");
    expect(sql).toContain("CRE_CONFIRMED");
    expect(sql).toContain("cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION')");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|DISTINCT ON|\bLATERAL\b|\bILIKE\b|regexp_replace|clock_timestamp/i);
    expect(values).toEqual(["데이터센터", "ALL", null, null, 20, 0, "MARKET_EVIDENCE", false, ""]);
  });

  it("accepts a raw SQLite JSON payload without changing the response shape", async () => {
    const executor: SqlExecutor = vi.fn().mockResolvedValue({
      rows: [{ payload: JSON.stringify({ total: 0, facets: {}, results: [] }) }],
    });
    const response = await searchMarket(executor, request);
    expect(response).toMatchObject({ total: 0, results: [], facets: { EVENT: 0, DOCUMENT: 0 } });
  });
});
