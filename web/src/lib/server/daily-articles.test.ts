import { describe, expect, it, vi } from "vitest";
import { parseDailyArticleDate, resolveDailyArticleDate, todayInSeoul } from "@/lib/daily-articles-contract";
import { getDailyArticles, type DailyArticleSqlExecutor } from "@/lib/server/daily-articles";

const payload = {
  selectedDate: "2026-08-19",
  latestAvailableDate: "2026-08-19",
  lastCollectedAt: "2026-08-19T08:00:00Z",
  generatedAt: "2026-08-19T08:01:00Z",
  total: 0,
  returned: 0,
  articles: [],
};

describe("daily articles", () => {
  it("uses the Seoul calendar date and rejects invalid dates", () => {
    expect(todayInSeoul(new Date("2026-08-18T16:00:00Z"))).toBe("2026-08-19");
    expect(parseDailyArticleDate("2026-02-30", new Date("2026-08-18T16:00:00Z"))).toBe("2026-08-19");
    expect(parseDailyArticleDate("2026-08-18")).toBe("2026-08-18");
    expect(resolveDailyArticleDate(null)).toBe("LATEST");
    expect(resolveDailyArticleDate("2026-08-18")).toBe("2026-08-18");
  });

  it("binds the date selector and resolves LATEST inside SQLite", async () => {
    const execute = vi.fn<DailyArticleSqlExecutor>(async () => ({ rows: [{ payload }] }));
    await expect(getDailyArticles(execute, "LATEST")).resolves.toEqual(payload);
    expect(execute).toHaveBeenCalledWith(expect.stringContaining("CASE WHEN $1='LATEST'"), ["LATEST"]);
    expect(execute.mock.calls[0]?.[0]).toContain("(SELECT selected_date FROM selected_day)");
  });

  it("reads only the prevalidated article and category projections", async () => {
    const execute = vi.fn<DailyArticleSqlExecutor>(async () => ({ rows: [{ payload }] }));
    await getDailyArticles(execute, "2026-08-19");

    const sql = execute.mock.calls[0]?.[0] ?? "";
    expect(sql).toContain("serving_daily_article_dates");
    expect(sql).toContain("serving_daily_articles");
    expect(sql).toContain("serving_daily_article_topics");
    expect(sql).toContain("ORDER BY topic_rank,term_code");
    expect(sql).not.toMatch(/document_scope_assessments|record_classifications|document_versions|document_enrichments/);
    expect(sql).toContain("'documentPurpose',CASE");
    expect(sql).toContain("'evidenceGrade',CASE");
  });

  it("counts all eligible rows before limiting the returned article list", async () => {
    const execute = vi.fn<DailyArticleSqlExecutor>(async () => ({ rows: [{ payload }] }));
    await getDailyArticles(execute, "2026-08-19");

    const sql = execute.mock.calls[0]?.[0] ?? "";
    expect(sql).toContain("dates.article_count");
    expect(sql).toContain("'returned',(SELECT count(*) FROM selected_articles)");
    expect(sql).toContain("SELECT * FROM selected_articles");
    expect(sql).toContain("ORDER BY published_at DESC,document_id");
    expect(sql).not.toContain(") ORDER BY published_at DESC,document_id");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|\bLATERAL\b|DISTINCT ON|clock_timestamp/i);
  });

  it("fails closed on a malformed serving payload", async () => {
    const execute = vi.fn<DailyArticleSqlExecutor>(async () => ({
      rows: [{ payload: { ...payload, articles: [{ id: "missing-required-fields" }] } }],
    }));
    await expect(getDailyArticles(execute, "LATEST")).rejects.toThrow("Invalid");
  });
});
