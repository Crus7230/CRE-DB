import { describe, expect, it, vi } from "vitest";
import { getKeywordAnalytics } from "@/lib/server/keyword-analytics";

const payload = { generatedAt: "2026-08-22T00:00:00Z", algorithmVersion: "KO_TITLE_PHRASE_DF_V1", computedAt: "2026-08-22T00:00:00Z", windowStart: "2026-07-01", windowEnd: "2026-08-22", latestDate: "2026-08-22", summary: { keywordCount: 1, observationCount: 1, qualifiedKeywordCount: 1, excludedMissingPublicationCount: 60 }, keywords: [] };

describe("getKeywordAnalytics", () => {
  it("reads only versioned aggregates and ranks collection bias behind organic terms", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    expect(await getKeywordAnalytics(execute)).toEqual(payload);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("FROM keyword_observations_daily");
    expect(sql).toContain("JOIN keyword_dictionary");
    expect(sql).toContain("FROM analytics_refresh_runs");
    expect(sql).toContain("is_collection_bias ASC");
    expect(sql).not.toContain("document_versions");
    expect(sql).toContain("qualifiedKeywordCount");
    expect(sql).toContain("date(s.bucket_date,'-29 days')");
    expect(sql).toContain("json(CASE WHEN s.is_collection_bias=1 THEN 'true'");
    expect(sql).toContain("JOIN keyword_observations_daily x");
    expect(sql).toContain("ORDER BY keyword_id,bucket_date");
    expect(sql).toContain("FROM keyword_payload keyword");
    expect(sql).toContain("LIMIT ?1");
    expect(sql).toContain("CASE WHEN ?2<>0");
    expect(sql).not.toMatch(/\$[12]/);
    expect(sql).not.toContain("json(item) ORDER BY");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|clock_timestamp|\binterval\b/i);
    expect(execute.mock.calls[0][1]).toEqual([30, false]);
  });
  it("prioritizes qualified organic terms before limiting a briefing payload", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload }] });
    await getKeywordAnalytics(execute, 5, true);
    const sql = execute.mock.calls[0][0] as string;
    expect(sql).toContain("o.document_frequency>=2");
    expect(sql).toContain("o.burst_score>0");
    expect(sql).toContain("kd.is_collection_bias=0");
    expect(execute.mock.calls[0][1]).toEqual([5, true]);
  });
});
