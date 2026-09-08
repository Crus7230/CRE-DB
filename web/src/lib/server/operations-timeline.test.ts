import { describe, expect, it, vi } from "vitest";
import { getOperationsTimeline } from "@/lib/server/operations-timeline";

const payload = {
  generatedAt: "2026-08-22T00:00:00Z",
  windowDays: 90,
  publicationKnownCount: 1,
  publicationUnknownCount: 2,
  archivedDocumentExcludedCount: 3,
  series: [{ date: "2026-08-21", publicationCount: 1, eventCount: 2, ingestionCount: 4 }],
};

describe("getOperationsTimeline", () => {
  it("uses SQLite clocks, a recursive calendar, distinct documents and validated archive events", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    const result = await getOperationsTimeline(execute, 90);
    expect(result.series[0].publicationCount).toBe(1);
    const [sql, values] = execute.mock.calls[0];
    expect(values).toEqual([90]);
    expect(sql).toContain("ldv.published_at");
    expect(sql).toContain("ldv.collected_at");
    expect(sql).toContain("e.event_date_start");
    expect(sql).toContain("count(DISTINCT document_id)");
    expect(sql).toContain("integrity_status='VALIDATED'");
    expect(sql).toContain("record_kind='EVENT'");
    expect(sql).toContain("WITH RECURSIVE input AS");
    expect(sql).toContain("SELECT date(day,'+1 day'),end_date");
    expect(sql).toContain("strftime('%Y-%m-%dT%H:%M:%fZ','now')");
    expect(sql).toContain("json_group_array(json_object(");
    expect(sql).not.toMatch(/coalesce\s*\(\s*ldv\.published_at\s*,\s*ldv\.collected_at/i);
    expect(sql).not.toContain("record_kind='DOCUMENT' AND event_date_start");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|DISTINCT ON|clock_timestamp|AT TIME ZONE|date_trunc|generate_series|\bLATERAL\b|interval\s/i);
  });
  it("rejects unsupported windows without querying",async()=>{
    const execute=vi.fn();
    await expect(getOperationsTimeline(execute,31)).rejects.toThrow(RangeError);
    expect(execute).not.toHaveBeenCalled();
  });
});
