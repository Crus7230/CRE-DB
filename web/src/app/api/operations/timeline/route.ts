import { isOperationsTimelineWindowDays } from "@/lib/operations-timeline-contract";
import { getCachedOperationsTimeline } from "@/lib/server/market-data-cache";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const requested = Number(new URL(request.url).searchParams.get("windowDays") ?? "90");
  if (!isOperationsTimelineWindowDays(requested)) return Response.json({ error: "windowDays는 30, 90, 365 중 하나여야 합니다." }, { status: 400, headers: { "Cache-Control": "no-store" } });
  try {
    return Response.json(await getCachedOperationsTimeline(requested), { headers: { "Cache-Control": "private, max-age=300" } });
  } catch (error) {
    const value = error as { name?: unknown; code?: unknown };
    console.error("operations timeline request failed", { name: typeof value.name === "string" ? value.name : "Error", code: typeof value.code === "string" ? value.code : undefined });
    return Response.json({ error: "시계열을 불러오지 못했습니다." }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
