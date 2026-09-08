import { getCachedInsightSignals } from "@/lib/server/market-data-cache";
export const runtime = "nodejs";
export async function GET(request: Request) {
  try {
    const parameters = new URL(request.url).searchParams;
    const limit = Number(parameters.get("limit") || "20");
    const reviewableOnly = parameters.get("reviewable") === "1";
    return Response.json(await getCachedInsightSignals(limit, reviewableOnly), { headers: { "cache-control": "private, max-age=300" } });
  } catch (error) {
    const value = error as { name?: string; code?: string };
    console.error("insight signals request failed", { name: value?.name, code: value?.code });
    return Response.json({ error: "인사이트 신호를 불러오지 못했습니다." }, { status: 503 });
  }
}
