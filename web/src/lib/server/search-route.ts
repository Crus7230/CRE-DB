import { parseSearchParams } from "@/lib/search-contract";
import { searchMarket, type SqlExecutor } from "@/lib/server/market-search";

export async function runSearchRequest(
  request: Request,
  execute: SqlExecutor,
  elapsed: () => number,
  clock: () => Date = () => new Date(),
): Promise<Response> {
  const params = parseSearchParams(new URL(request.url).searchParams);
  const result = await searchMarket(execute, params);
  return Response.json({
    ...result,
    elapsedMs: Math.max(0, Math.round(elapsed())),
    generatedAt: clock().toISOString(),
    database: "supabase-postgresql",
  });
}
