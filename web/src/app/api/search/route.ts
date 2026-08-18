import { executeMarketSql } from "@/lib/server/db";
import { runSearchRequest } from "@/lib/server/search-route";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const started = performance.now();
  try {
    return await runSearchRequest(request, executeMarketSql, () => performance.now() - started);
  } catch (error) {
    console.error("Market search failed", error instanceof Error ? error.message : "unknown error");
    return Response.json(
      { error: "시장 데이터베이스 검색에 실패했습니다.", code: "SEARCH_UNAVAILABLE" },
      { status: 503 },
    );
  }
}
