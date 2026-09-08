import { resolveDailyArticleDate } from "@/lib/daily-articles-contract";
import {
  infrastructureUnavailableResponse,
  jsonWithServerTiming,
  safeErrorDescriptor,
} from "@/lib/server/api-response";
import { getCachedDailyArticles } from "@/lib/server/market-data-cache";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const startedAt = performance.now();
  try {
    const url = new URL(request.url);
    const selectedDate = resolveDailyArticleDate(url.searchParams.get("date"));
    const payload = await getCachedDailyArticles(selectedDate);
    return jsonWithServerTiming(
      payload,
      { headers: { "Cache-Control": "private, max-age=900" } },
      "data",
      startedAt,
    );
  } catch (error) {
    console.error("Daily article search failed", safeErrorDescriptor(error));
    return infrastructureUnavailableResponse(
      "DAILY_ARTICLES_UNAVAILABLE",
      startedAt,
      { "Cache-Control": "no-store" },
    );
  }
}
