import { describe, expect, it } from "vitest";
import { getCompanies, getCompanyDetail } from "@/lib/server/company-intelligence";

const emptyDetail = {
  organization: { organizationId: "org-1", name: "회사", organizationType: "COMPANY", stockCode: null, industry: null, marketCap: null, overallRank: null },
  counts: { events: 0, assets: 0, documents: 0, occupancies: 0, locationEvidence: 0 },
  events: [], assets: [], documents: [], occupancies: [], locationEvidence: [],
};

function aggregateBodies(sql: string): string[] {
  const names = ["json_group_array", "json_group_object", "group_concat"];
  const lowerSql = sql.toLowerCase();
  const bodies: string[] = [];

  for (let offset = 0; offset < sql.length;) {
    const starts = names
      .map((name) => lowerSql.indexOf(`${name}(`, offset))
      .filter((index) => index >= 0);
    if (starts.length === 0) break;

    const start = Math.min(...starts);
    const open = lowerSql.indexOf("(", start);
    let depth = 1;
    let quoted = false;
    let cursor = open + 1;
    for (; cursor < sql.length && depth > 0; cursor += 1) {
      if (sql[cursor] === "'") {
        if (quoted && sql[cursor + 1] === "'") cursor += 1;
        else quoted = !quoted;
      } else if (!quoted && sql[cursor] === "(") depth += 1;
      else if (!quoted && sql[cursor] === ")") depth -= 1;
    }
    bodies.push(sql.slice(open + 1, cursor - 1));
    offset = cursor;
  }

  return bodies;
}

describe("getCompanyDetail relation lineage", () => {
  it("uses typed relation projection while keeping name matches as labelled evidence", async () => {
    let sql = "";
    await getCompanyDetail(async (text) => { sql = text; return { rows: [{ payload: emptyDetail }] }; }, "org-1");
    expect(sql).toContain("v_document_entity_relations");
    expect(sql).toContain("RESOLVED_MENTION");
    expect(sql).toContain("VERIFIED_CLAIM");
    expect(sql).toContain("EXACT_NAME_SIGNAL");
  });

  it("uses the same managed, action-bound evidence contract in list and detail", async () => {
    let listSql = "";
    let detailSql = "";
    const listPayload = {
      snapshotDate: null,
      items: [],
      industries: [],
      coverage: { verifiedOccupancies: 0, companiesWithLocationEvidence: 0, managedLocationDocuments: 0, signalNote: "" },
    };
    await getCompanies(async (text) => { listSql = text; return { rows: [{ payload: listPayload }] }; }, {
      view: "TENANT_SIGNALS", industry: "", q: "", limit: 100,
    });
    await getCompanyDetail(async (text) => { detailSql = text; return { rows: [{ payload: emptyDetail }] }; }, "org-1");

    for (const sql of [listSql, detailSql]) {
      expect(sql).toContain("record_classifications");
      expect(sql).toContain("MARKET_CATEGORY");
      expect(sql).toContain("CORPORATE_RELOCATION");
      expect(sql).toContain("location_evidence AS");
      expect(sql).toContain("location_document_corpus AS");
      expect(sql).toContain("location_name_matches AS");
      expect(sql).toContain("본사 이전");
      expect(sql).toContain("행위주체 검토 전");
      expect(sql).toContain("replace(lower(coalesce(dv.title,'')),lower(sd.publisher_name),'')");
      expect(sql).toContain("match_position");
      expect(sql).toContain("NOT LIKE '%' || lower(p.organization_name) || '에 이어%'");
      expect(sql).toContain("row_number() OVER");
      expect(sql).toContain("instr(content_text,'본사')");
      expect(sql).toContain("json_group_array");

      for (const postgresOnly of [
        "market_intelligence.", "DISTINCT ON", "LATERAL", "jsonb_", "::", " ILIKE ",
        "regexp_replace", " FULL OUTER JOIN ", " ~ ",
      ]) {
        expect(sql.toUpperCase()).not.toContain(postgresOnly.toUpperCase());
      }
    }
  });

  it("orders aggregate input through derived tables without aggregate-local clauses", async () => {
    let listSql = "";
    let detailSql = "";
    const listPayload = {
      snapshotDate: null,
      items: [],
      industries: [],
      coverage: { verifiedOccupancies: 0, companiesWithLocationEvidence: 0, managedLocationDocuments: 0, signalNote: "" },
    };

    await getCompanies(async (text) => { listSql = text; return { rows: [{ payload: listPayload }] }; }, {
      view: "TENANT_SIGNALS", industry: "", q: "", limit: 100,
    });
    await getCompanyDetail(async (text) => { detailSql = text; return { rows: [{ payload: emptyDetail }] }; }, "org-1");

    for (const sql of [listSql, detailSql]) {
      const bodies = aggregateBodies(sql);
      expect(bodies.length).toBeGreaterThan(0);
      expect(bodies.every((body) => !body.toUpperCase().includes("ORDER BY"))).toBe(true);
      expect(sql.toUpperCase()).not.toContain(" FILTER ");
    }

    expect(listSql).toContain("FROM (SELECT * FROM filtered ORDER BY");
    expect(listSql).toContain("LIMIT ?4) ordered_items");
    expect(listSql).toContain("FROM (SELECT * FROM industries ORDER BY name) ordered_industries");
    expect(detailSql).toContain("FROM (SELECT * FROM company_events ORDER BY");
    expect(detailSql).toContain("FROM (SELECT * FROM company_assets ORDER BY name,asset_id) ordered_assets");
    expect(detailSql).toContain("FROM (SELECT * FROM docs ORDER BY");
    expect(detailSql).toContain("FROM (SELECT * FROM occupancies ORDER BY");
    expect(detailSql).toContain("ordered_location_evidence");
  });

  it("only counts hard-gated verified tenant occupancies", async () => {
    let sql = "";
    await getCompanies(async (text) => {
      sql = text;
      return { rows: [{ payload: {
        snapshotDate: null, items: [], industries: [],
        coverage: { verifiedOccupancies: 0, companiesWithLocationEvidence: 0, managedLocationDocuments: 0, signalNote: "" },
      } }] };
    }, { view: "TENANT_SIGNALS", industry: "", q: "", limit: 100 });

    expect(sql).toContain("occupancy_status IN ('CONTRACTED','OCCUPIED')");
    expect(sql).toContain("review_status='APPROVED' AND verification_status='VERIFIED'");
    expect(sql).toContain("source_claim_id IS NOT NULL");
  });

  it("accepts libSQL JSON text while preserving the response payload", async () => {
    const listPayload = {
      snapshotDate: "2026-09-03",
      items: [],
      industries: [],
      coverage: { verifiedOccupancies: 0, companiesWithLocationEvidence: 0, managedLocationDocuments: 0, signalNote: "" },
    };
    const detailPayload = { ...emptyDetail, organization: { ...emptyDetail.organization, name: "문자열 회사" } };

    const list = await getCompanies(async () => ({ rows: [{ payload: JSON.stringify(listPayload) }] }), {
      view: "OVERALL", industry: "", q: "", limit: 10,
    });
    const detail = await getCompanyDetail(
      async () => ({ rows: [{ payload: JSON.stringify(detailPayload) }] }),
      "org-1",
    );

    expect(list.snapshotDate).toBe("2026-09-03");
    expect(detail.organization.name).toBe("문자열 회사");
  });
});
