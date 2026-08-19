import { describe, expect, it, vi } from "vitest";
import { parseDailyArticleDate, todayInSeoul } from "@/lib/daily-articles-contract";
import { getDailyArticles } from "@/lib/server/daily-articles";

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
    const execute = vi.fn(async () => ({ rows: [{ payload }] }));
    await expect(getDailyArticles(execute, "2026-08-19")).resolves.toEqual(payload);
    expect(execute).toHaveBeenCalledWith(expect.stringContaining("$1::date"), ["2026-08-19"]);
  });
});
