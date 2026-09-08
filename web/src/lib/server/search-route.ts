import { parseSearchParams, type SearchRequest } from "@/lib/search-contract";
import { searchMarket, type SqlExecutor } from "@/lib/server/market-search";

type MarketSearcher = (request: SearchRequest) => ReturnType<typeof searchMarket>;

export async function runSearchRequest(
  request: Request,
  execute: SqlExecutor,
  elapsed: () => number,
  clock: () => Date = () => new Date(),
  search: MarketSearcher = (params) => searchMarket(execute, params),
): Promise<Response> {
  const params = parseSearchParams(new URL(request.url).searchParams);
  const result = await search(params);
  return Response.json({
    ...result,
    elapsedMs: Math.max(0, Math.round(elapsed())),
    generatedAt: clock().toISOString(),
    database: "turso-libsql",
  }, { headers: { "Cache-Control": "private, max-age=30" } });
}
