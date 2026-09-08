import { describe, expect, it, vi } from "vitest";
import { getCategoryIndex, type CategorySqlExecutor } from "@/lib/server/category-index";

describe("getCategoryIndex", () => {
  it("normalizes database taxonomy groups without interpolating user input", async () => {
    const execute: CategorySqlExecutor = vi.fn().mockResolvedValue({
      rows: [{ payload: { groups: [
        { group: "EVENT_CATEGORY", label: "이벤트 카테고리", kind: "EVENT", items: [{ key: "PF", label: "PF", itemCount: 645, canonicalCount: 0 }] },
        { group: "DOCUMENT_TYPE", label: "근거 목적", kind: "DOCUMENT", items: [{ key: "MARKET_EVIDENCE", label: "시장동향 근거", itemCount: 7400 }] },
        {
          group: "MARKET_CATEGORY", classificationScheme: "MARKET_CATEGORY",
          label: "시장 카테고리", kind: "ALL", targetKinds: ["EVENT", "SALE_PROCESS"],
          countSemantics: "SERVING_TARGETS", vocabularyVersion: "1.0.0",
          items: [{
            key: "SALE", label: "매각", itemCount: 32,
            parentKey: "TRANSACTION", parentLabel: "거래",
            countsByKind: { EVENT: 16, SALE_PROCESS: 16 },
          }],
        },
      ] } }],
    });

    const result = await getCategoryIndex(execute);

    expect(result.groups).toHaveLength(3);
    expect(result.groups[0].items[0]).toMatchObject({ key: "PF", itemCount: 645 });
    expect(result.groups[1].items[0]).toMatchObject({ key: "MARKET_EVIDENCE", label: "시장동향 근거" });
    expect(result.groups[2]).toMatchObject({
      classificationScheme: "MARKET_CATEGORY",
      targetKinds: ["EVENT", "SALE_PROCESS"],
      countSemantics: "SERVING_TARGETS",
    });
    expect(result.groups[2].items[0]).toMatchObject({
      itemCount: 32,
      parentKey: "TRANSACTION",
      countsByKind: { EVENT: 16, SALE_PROCESS: 16 },
    });
    expect(execute).toHaveBeenCalledTimes(1);
    const [sql, values] = vi.mocked(execute).mock.calls[0];
    expect(values).toEqual([]);
    expect(sql).toContain("document_scope_assessments");
    expect(sql).toContain("DART_CRE_SCOPE_RULE_V1");
    expect(sql).toContain("NEWS_CRE_SCOPE_RULE_V3");
    expect(sql).toContain("NEWS_CRE_SCOPE_RULE_V2");
    expect(sql).toContain("NEWS_CRE_SCOPE_RULE_V1");
    expect(sql).toContain("WHEN 'NEWS_CRE_SCOPE_RULE_V3' THEN 0");
    expect(sql).toContain("MOLIT_SCOPE_TIERED_V2");
    expect(sql).toContain("organization_scope_assessments");
    expect(sql).toContain("ORG_CRE_SCOPE_RULE_V1");
    expect(sql).toContain("CRE_CONFIRMED");
    expect(sql).toContain("archived_serving_index");
    expect(sql).toContain("archive_snapshots");
    expect(sql).toContain("classification_schemes");
    expect(sql).toContain("classification_terms");
    expect(sql).toContain("record_classifications");
    expect(sql).toContain("rc.review_status='APPROVED'");
    expect(sql).toContain("rc.assignment_role<>'LEGACY_BACKFILL'");
    expect(sql).not.toContain("rc.review_status NOT IN ('REJECTED','SUPERSEDED')");
    expect(sql).toContain("'MARKET_CATEGORY'");
    expect(sql).toContain("'DOCUMENT_PURPOSE'");
    expect(sql).toContain("'ASSET_CLASS'");
    expect(sql).toContain("'EVIDENCE_GRADE'");
    expect(sql).toContain("'classificationScheme','MARKET_CATEGORY'");
    expect(sql).toContain("'countsByKind',json(counts_by_kind)");
    expect(sql).toContain("json_group_object(target_kind,item_count)");
    expect(sql).toContain("json_group_array(json_object(");
    expect(sql).toContain("row_number() OVER (");
    expect(sql).toContain("PARTITION BY document_id");
    expect(sql).toContain("strftime('%Y-%m-%dT%H:%M:%fZ','now')");
    expect(sql).toContain("json_extract(ar.metadata_json,'$.documentType')");
    expect(sql).toContain("parent.term_code AS parent_key");
    expect(sql).toContain("rc.valid_from IS NULL");
    expect(sql).toContain("t.valid_from IS NULL");
    expect(sql).toContain("integrity_status='VALIDATED'");
    expect(sql).toContain("is_current=1");
    expect(sql).toContain("cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION')");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|DISTINCT ON|clock_timestamp|AT TIME ZONE|date_trunc|generate_series|\bLATERAL\b/i);
    expect(sql).not.toMatch(/->>|!~|\s~\s/);
  });
});
