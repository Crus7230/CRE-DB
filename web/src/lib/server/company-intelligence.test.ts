import { describe, expect, it } from "vitest";
import { getCompanyDetail } from "@/lib/server/company-intelligence";

describe("getCompanyDetail relation lineage", () => {
  it("uses typed relation projection while keeping name matches as signals", async () => {
    let sql = "";
    const payload = {
      organization: { organizationId: "org-1", name: "회사", organizationType: "COMPANY", stockCode: null, industry: null, marketCap: null, overallRank: null },
      counts: { events: 0, assets: 0, documents: 0, occupancies: 0 }, events: [], assets: [], documents: [], occupancies: [],
    };
    await getCompanyDetail(async (text) => { sql = text; return { rows: [{ payload }] }; }, "org-1");
    expect(sql).toContain("v_document_entity_relations");
    expect(sql).toContain("RESOLVED_MENTION");
    expect(sql).toContain("VERIFIED_CLAIM");
    expect(sql).toContain("EXACT_NAME_SIGNAL");
  });
});
