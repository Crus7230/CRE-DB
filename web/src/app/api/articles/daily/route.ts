import { parseDailyArticleDate } from "@/lib/daily-articles-contract";
import { executeMarketSql } from "@/lib/server/db";
import { getDailyArticles } from "@/lib/server/daily-articles";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  try {
    const url = new URL(request.url);
    const selectedDate = parseDailyArticleDate(url.searchParams.get("date"));
    const payload = await getDailyArticles(executeMarketSql, selectedDate);
    return Response.json(payload, { headers: { "Cache-Control": "private, max-age=60" } });
  } catch (error) {
    console.error("Daily article search failed", error instanceof Error ? error.message : "unknown error");
    return Response.json(
      { error: "오늘의 시장기사를 불러오지 못했습니다.", code: "DAILY_ARTICLES_UNAVAILABLE" },
      { status: 503 },
    );
  }
}
