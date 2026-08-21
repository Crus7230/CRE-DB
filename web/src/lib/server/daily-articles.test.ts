import { describe, expect, it, vi } from "vitest";
import { parseDailyArticleDate, todayInSeoul } from "@/lib/daily-articles-contract";
import { getDailyArticles, type DailyArticleSqlExecutor } from "@/lib/server/daily-articles";

const payload = {
  selectedDate: "2026-08-19",
  latestAvailableDate: "2026-08-19",
  lastCollectedAt: "2026-08-19T08:00:00Z",
  generatedAt: "2026-08-19T08:01:00Z",
  total: 0,
  articles: [],
};

describe("daily articles", () => {
  it("uses the Seoul calendar date and rejects invalid dates", () => {
    expect(todayInSeoul(new Date("2026-08-18T16:00:00Z"))).toBe("2026-08-19");
    expect(parseDailyArticleDate("2026-02-30", new Date("2026-08-18T16:00:00Z"))).toBe("2026-08-19");
    expect(parseDailyArticleDate("2026-08-18")).toBe("2026-08-18");
  });

  it("binds the selected date instead of interpolating it into SQL", async () => {
    const execute = vi.fn<DailyArticleSqlExecutor>(async () => ({ rows: [{ payload }] }));
    await expect(getDailyArticles(execute, "2026-08-19")).resolves.toEqual(payload);
    expect(execute).toHaveBeenCalledWith(expect.stringContaining("$1::date"), ["2026-08-19"]);
  });

  it("returns API-managed topics with classification provenance", async () => {
    const execute = vi.fn<DailyArticleSqlExecutor>(async () => ({ rows: [{ payload }] }));
    await getDailyArticles(execute, "2026-08-19");

    const sql = execute.mock.calls[0]?.[0] ?? "";
    expect(sql).toContain("collection_job_categories");
    expect(sql).toContain("em.status_code = 'APPROVED'");
    expect(sql).toContain("'topics', topics");
    expect(sql).toContain("'COLLECTION_QUERY'::text AS provenance");
    expect(sql).toContain("er.document_version_id = lv.document_version_id");
    expect(sql).toContain("rd.document_version_id = lv.document_version_id");
    expect(sql).toContain("max(em.confidence) AS confidence_rank");
    expect(sql).toContain("min(rd.result_rank) AS relevance_rank");
    expect(sql).toContain("cr.status_code = 'COMPLETED'");
    expect(sql).toContain("cjc.is_primary = 1");
    expect(sql).toContain("ec.is_active = 1");
    expect(sql).toContain("WHEN 'INVESTMENT' THEN 'EQUITY_INVESTMENT'");
    expect(sql).toContain("WHEN 'NEW_SUPPLY' THEN 'SUPPLY'");
    expect(sql).toContain("WHEN 'CORPORATE_RELOCATION' THEN 'RELOCATION'");
    expect(sql).toContain("market_category_terms");
    expect(sql).toContain("managed_term.term_name_ko");
    expect(sql).toContain("'documentPurpose',CASE");
    expect(sql).toContain("'evidenceGrade',CASE");
    expect(sql).toContain("rc.valid_from IS NULL");
    expect(sql).toContain("rc.valid_to IS NULL");
    expect(sql).not.toContain("topic_version.document_id = lv.document_id");
  });
});
