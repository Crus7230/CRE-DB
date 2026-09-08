import { executeMarketSql } from "@/lib/server/db";
import { runContextualSearchRequest } from "@/lib/server/contextual-search-route";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const started = performance.now();
  try {
    return await runContextualSearchRequest(
      request,
      executeMarketSql,
      () => performance.now() - started,
    );
  } catch (error) {
    console.error("Contextual intelligence search failed", error instanceof Error ? error.message : "unknown error");
    const invalidRequest = error instanceof Error && error.message.startsWith("Invalid contextual search");
    return Response.json(
      {
        error: invalidRequest ? "검색 조건을 확인해 주세요." : "문맥형 시장 검색에 실패했습니다.",
        code: invalidRequest ? "INVALID_SEARCH_REQUEST" : "CONTEXTUAL_SEARCH_UNAVAILABLE",
      },
      { status: invalidRequest ? 400 : 503 },
    );
  }
}
