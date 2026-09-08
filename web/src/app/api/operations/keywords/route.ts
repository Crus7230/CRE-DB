import { getCachedKeywordAnalytics } from "@/lib/server/market-data-cache";
export const runtime = "nodejs";
export async function GET(request: Request) {
  try {
    const parameters = new URL(request.url).searchParams;
    const value = Number(parameters.get("limit") || "30");
    const briefingPriority = parameters.get("briefing") === "1";
    return Response.json(await getCachedKeywordAnalytics(value, briefingPriority), { headers: { "cache-control": "private, max-age=300" } });
  } catch (error) {
    const value = error as { name?: string; code?: string };
    console.error("keyword analytics request failed", { name: value?.name, code: value?.code });
    return Response.json({ error: "키워드 분석을 불러오지 못했습니다." }, { status: 503 });
  }
}
