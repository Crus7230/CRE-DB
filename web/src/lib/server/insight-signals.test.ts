import { describe, expect, it, vi } from "vitest";
import { getInsightSignals } from "@/lib/server/insight-signals";

const payload = { generatedAt: "2026-08-22T00:00:00Z", algorithmVersion: "KEYWORD_BURST_SIGNAL_V1", statusCounts: [], signals: [] };
describe("getInsightSignals", () => {
  it("returns reviewable signals with source-grounded evidence", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    expect(await getInsightSignals(execute, 20)).toEqual(payload);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("FROM insight_signals");
    expect(sql).toContain("FROM insight_signal_evidence");
    expect(sql).toContain("LEFT JOIN source_documents");
    expect(sql).toContain("LEFT JOIN document_versions");
    expect(sql).toContain("review_status");
    expect(sql).toContain("max(computed_at)");
    expect(sql).toContain("FROM insight_signal_evidence e");
    expect(sql).toContain("ORDER BY e.evidence_rank,e.insight_signal_evidence_id");
    expect(sql).toContain("FROM statuses status");
    expect(sql).toContain("FROM payloads signal");
    expect(sql).not.toContain(") ORDER BY review_status");
    expect(sql).not.toContain("json(item) ORDER BY");
    expect(sql).not.toContain("review_status='APPROVED'");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|clock_timestamp/i);
    expect(execute.mock.calls[0][1]).toEqual([20, false]);
  });
  it("filters reviewable statuses before limiting the briefing queue", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    await getInsightSignals(execute, 4, true);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("s.review_status IN ('UNREVIEWED','PENDING')");
    expect(sql).toContain("s.severity_code WHEN 'HIGH'");
    expect(sql).toContain("$2<>0");
    expect(execute.mock.calls[0][1]).toEqual([4, true]);
  });
});
