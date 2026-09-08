import { describe, expect, it, vi } from "vitest";
import { getModelInterpretations } from "@/lib/server/model-interpretations";

const payload = { generatedAt: "2026", models: [], statusCounts: [], interpretations: [] };

describe("getModelInterpretations", () => {
  it("serves only persisted versioned outputs with grounded evidence", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    expect(await getModelInterpretations(execute)).toEqual(payload);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("FROM insight_interpretations");
    expect(sql).toContain("FROM analytics_model_registry");
    expect(sql).toContain("FROM insight_interpretation_evidence");
    expect(sql).toContain("json_group_array");
    expect(sql).toContain("ORDER BY l.interpretation_id,se.evidence_rank,se.insight_signal_evidence_id");
    expect(sql).toContain("FROM models model");
    expect(sql).toContain("FROM selected s");
    expect(sql).not.toContain(") ORDER BY se.evidence_rank");
    expect(sql).not.toContain(") ORDER BY model_name");
    expect(sql).not.toContain("count)\n    ORDER BY interpretation_status");
    expect(sql).not.toContain("api_key");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|clock_timestamp/i);
  });
});
