import { describe, expect, it } from "vitest";
import { getEntityDetail } from "@/lib/server/entity-intelligence";

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
    expect(sql).toContain("'classifications',json(COALESCE");
    expect(sql).toContain(`rc.target_kind='${kind}'`);
    expect(sql).toContain("rc.valid_from IS NULL");
    expect(sql).toContain("row_number() OVER");
    expect(sql).toContain(") ordered_classifications");
    expectTursoCompatibleAggregates(sql);
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|\bLATERAL\b|DISTINCT ON|clock_timestamp/i);
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
