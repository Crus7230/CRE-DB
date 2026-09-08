import { describe, expect, it } from "vitest";
import { getDocumentDetail } from "@/lib/server/document-intelligence";

function expectTursoCompatibleAggregates(sql: string) {
  for (const name of ["json_group_array", "json_group_object", "group_concat"]) {
    let searchFrom = 0;
    while ((searchFrom = sql.indexOf(`${name}(`, searchFrom)) >= 0) {
      const argumentStart = searchFrom + name.length + 1;
      let depth = 1;
      let inString = false;
      let cursor = argumentStart;
      for (; cursor < sql.length && depth > 0; cursor += 1) {
        const character = sql[cursor];
        if (character === "'") {
          if (inString && sql[cursor + 1] === "'") cursor += 1;
          else inString = !inString;
        } else if (!inString && character === "(") depth += 1;
        else if (!inString && character === ")") depth -= 1;
      }
      expect(depth).toBe(0);
      expect(sql.slice(argumentStart, cursor - 1).toUpperCase()).not.toContain("ORDER BY");
      searchFrom = cursor;
    }
  }
}

describe("getDocumentDetail relation lineage", () => {
  it("loads typed canonical relations from the database projection", async () => {
    let sql = "";
    let values: readonly unknown[] = [];
    const issuedSql: string[] = [];
    const payload = {
      id: "doc-1", title: "근거 문서", publisher: "source", documentType: "ARTICLE",
      sourceUrl: null, author: null, publishedAt: null, collectedAt: null,
      rightsStatus: "METADATA_ONLY", contentMode: "METADATA", summaryMode: "NONE",
      summaryGeneratedAt: null, summaryPipeline: null, summary: null, safeExcerpt: null,
      snippet: null, storedText: null, eventSignals: [], keywords: [], transaction: null,
      classifications: [{
        schemeCode: "DOCUMENT_PURPOSE", schemeLabel: "문서 목적",
        termCode: "MARKET_INTELLIGENCE", termLabel: "시장 동향",
        parentCode: null, parentLabel: null, isPrimary: true,
        assignmentRole: "LEGACY_BACKFILL", evidenceStatus: "MEDIA_DIRECT",
        reviewStatus: "APPROVED", confidence: 1,
      }],
      relatedEntities: [{ kind: "EVENT", id: "event-1", title: "매각 이벤트", relationBasis: "CANONICAL_EVENT", relationRole: "SUPPORTING", evidenceStatus: "V2", confidence: 0.9 }],
    };
    const result = await getDocumentDetail(async (text, params) => {
      issuedSql.push(text);
      if (text.includes("serving_daily_article_details")) return { rows: [] };
      sql = text;
      values = params;
      return { rows: [{ payload }] };
    }, "doc-1", { allowArchiveFallback: true });

    expect(issuedSql).toHaveLength(2);
    expect(issuedSql[0]).toContain("serving_daily_article_details");
    expect(sql).toContain("v_document_entity_relations");
    expect(sql).toContain("relationBasis");
    expect(sql).toContain("evidenceStatus");
    expect(sql).toContain("'classifications',json(COALESCE(cls.items");
    expect(sql).toContain("rc.target_kind='DOCUMENT'");
    expect(sql).toContain("rc.valid_from IS NULL");
    expect(sql).toContain("row_number() OVER");
    expect(sql).toContain(") ordered_events");
    expect(sql).toContain(") ordered_relations");
    expectTursoCompatibleAggregates(sql);
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|\bLATERAL\b|DISTINCT ON|array_agg|regexp_replace/i);
    expect(result?.classifications[0].termCode).toBe("MARKET_INTELLIGENCE");
    expect(values).toEqual(["doc-1"]);
    expect(result?.relatedEntities[0].relationBasis).toBe("CANONICAL_EVENT");
  });

  it("returns a compact detail directly without issuing raw archive SQL", async () => {
    const issuedSql: string[] = [];
    const payload = {
      summaryMode: "NONE",
      summary: null,
      eventSignals: [],
    };

    const result = await getDocumentDetail(async (text) => {
      issuedSql.push(text);
      return { rows: [{ payload }] };
    }, "doc-serving", { allowArchiveFallback: true });

    expect(result?.summary).toBeNull();
    expect(issuedSql).toHaveLength(1);
    expect(issuedSql[0]).toContain("serving_daily_article_details");
    expect(issuedSql[0]).not.toContain("document_versions");
  });

  it("returns a controlled miss on remote compact data without issuing raw-table SQL", async () => {
    const issuedSql: string[] = [];

    const result = await getDocumentDetail(async (text) => {
      issuedSql.push(text);
      return { rows: [] };
    }, "doc-missing");

    expect(result).toBeNull();
    expect(issuedSql).toHaveLength(1);
    expect(issuedSql[0]).toContain("serving_daily_article_details");
    expect(issuedSql[0]).not.toContain("document_versions");
    expect(issuedSql[0]).not.toContain("source_documents");
  });

  it("moves object-shaped event extraction JSON out of display summaries", async () => {
    const extraction = {
      asset: "테스트 자산",
      process_code: "PROCESS-1",
      amounts: [{ basis: "closing_asset_value", value_krw: "100000000" }],
    };
    const rawExtraction = JSON.stringify(extraction);
    const payload = {
      summaryMode: "EVENT_EXTRACTION",
      summary: rawExtraction,
      eventSignals: [{ summary: rawExtraction }],
    };

    const result = await getDocumentDetail(async () => ({ rows: [{ payload }] }), "doc-1");

    expect(result?.summary).toBeNull();
    expect(result?.eventExtraction).toEqual(extraction);
    expect(result?.eventSignals[0].summary).toBeNull();
  });

  it("preserves human-readable event extraction summaries", async () => {
    const payload = {
      summaryMode: "EVENT_EXTRACTION",
      summary: "거래가 종결되었으며 확인된 금액은 1억원입니다.",
      eventSignals: [{ summary: "우선협상대상자가 선정되었습니다." }],
    };

    const result = await getDocumentDetail(async () => ({ rows: [{ payload }] }), "doc-1");

    expect(result?.summary).toBe(payload.summary);
    expect(result?.eventExtraction).toBeNull();
    expect(result?.eventSignals[0].summary).toBe(payload.eventSignals[0].summary);
  });

  it("suppresses malformed object-looking extraction text", async () => {
    const malformed = '{"asset":"테스트 자산"';
    const payload = {
      summaryMode: "EVENT_EXTRACTION",
      summary: malformed,
      eventSignals: [{ summary: malformed }],
    };

    const result = await getDocumentDetail(async () => ({ rows: [{ payload }] }), "doc-1");

    expect(result?.summary).toBeNull();
    expect(result?.eventExtraction).toBeNull();
    expect(result?.eventSignals[0].summary).toBeNull();
  });
});
