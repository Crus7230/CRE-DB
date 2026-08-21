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
                metadata: { asset: "용인 남사 데이터센터", evidenceCount: 3 },
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
    expect(response.results[0].metadata.evidenceCount).toBe(3);
    expect(executor).toHaveBeenCalledTimes(1);
    const [sql, values] = vi.mocked(executor).mock.calls[0];
    expect(sql).not.toContain("데이터센터");
    expect(sql).toContain("latest_documents AS");
    expect(sql).not.toContain("SELECT DISTINCT ON (document_id) *");
    expect(sql).not.toContain("dv.stored_text");
    expect(sql).not.toContain("JOIN LATERAL (\n    SELECT *\n    FROM market_intelligence.document_versions");
    expect(sql).toContain("MARKET_EVIDENCE");
    expect(sql).toContain("RSS_ITEM");
    expect(sql).toContain("document_scope_assessments");
    expect(sql).toContain("DART_CRE_SCOPE_RULE_V1");
    expect(sql).toContain("NEWS_CRE_SCOPE_RULE_V1");
    expect(sql).toContain("MOLIT_SCOPE_TIERED_V2");
    expect(sql).toContain("organization_scope_assessments");
    expect(sql).toContain("ORG_CRE_SCOPE_RULE_V1");
    expect(sql).toContain("market_intelligence.archived_serving_index");
    expect(sql).toContain("market_intelligence.record_classifications");
    expect(sql).toContain("market_intelligence.classification_terms");
    expect(sql).toContain("primary_market_category_code");
    expect(sql).toContain("primary_document_purpose_code");
    expect(sql).toContain("'ARCHIVED_LOCAL'");
    expect(sql).toContain("'archiveLocator'");
    expect(sql).toContain("ars.is_current=1 AND ars.integrity_status='VALIDATED'");
    expect(sql).toContain("ai.record_kind='EVENT' AND EXISTS");
    expect(sql).toContain("market_intelligence.classification_schemes");
    expect(sql).toContain("csc.scheme_code=$9");
    expect(sql).toContain("rc.valid_from IS NULL");
    expect(sql).toContain("rc.valid_to IS NULL");
    expect(sql).toContain("s.valid_from IS NULL");
    expect(sql).toContain("s.valid_to IS NULL");
    expect(sql).toContain("t.valid_from IS NULL");
    expect(sql).toContain("t.valid_to IS NULL");
    expect(sql).toContain("ct.valid_from IS NULL");
    expect(sql).toContain("'documentPurposeCode',rcs.primary_document_purpose_code");
    expect(sql).toContain("'documentPurposeLabel',rcs.primary_document_purpose_label");
    expect(sql).toContain("'evidenceGradeCode',rcs.primary_evidence_grade_code");
    expect(sql).toContain("'evidenceGradeLabel',rcs.primary_evidence_grade_label");
    expect(sql).toContain("'classificationCount',rcs.classification_count");
    expect(sql).toContain("page_base AS");
    expect(sql).toContain("market_intelligence.v_document_entity_relations");
    expect(sql).toContain("count(DISTINCT relation.document_id)::int");
    expect(sql).toContain("'evidenceCount',CASE WHEN f.kind='EVENT'");
    expect(sql).toContain("CRE_CONFIRMED");
    expect(sql).toContain("cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION')");
    expect(values).toEqual(["데이터센터", "ALL", null, null, 20, 0, "MARKET_EVIDENCE", false, ""]);
  });
});
