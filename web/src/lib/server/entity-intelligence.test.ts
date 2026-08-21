import { describe, expect, it } from "vitest";
import { getEntityDetail } from "@/lib/server/entity-intelligence";

const payload = {
  kind: "EVENT", id: "event-1", title: "이벤트", subtitle: null, status: "ACTIVE",
  overview: [], assets: [], events: [], organizations: [], projects: [], capital: [],
  processes: [], documents: [], classifications: [],
};

describe("getEntityDetail relation graph", () => {
  it.each(["EVENT", "ASSET"] as const)("loads %s documents through the lineage projection", async (kind) => {
    let sql = "";
    await getEntityDetail(async (text) => { sql = text; return { rows: [{ payload: { ...payload, kind } }] }; }, kind, "entity-1");
    expect(sql).toContain("v_document_entity_relations");
    expect(sql).toContain("relation_basis");
    expect(sql).toContain("'classifications',coalesce(cls.items");
    expect(sql).toContain(`rc.target_kind='${kind}'`);
    expect(sql).toContain("rc.valid_from IS NULL");
  });

  it("returns event projects, capital mandates, and sale processes", async () => {
    let sql = "";
    await getEntityDetail(async (text) => { sql = text; return { rows: [{ payload }] }; }, "EVENT", "event-1");
    expect(sql).toContain("event_projects");
    expect(sql).toContain("lp_mandates");
    expect(sql).toContain("sale_processes");
    expect(sql).toContain("'projects'");
    expect(sql).toContain("'capital'");
    expect(sql).toContain("'processes'");
  });
});
