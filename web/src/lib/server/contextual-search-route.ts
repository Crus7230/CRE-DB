import { parseContextualSearchParams } from "@/lib/contextual-search-contract";
import { searchContextualIntelligence } from "@/lib/server/contextual-search";
import type { SqlExecutor } from "@/lib/server/market-search";

export async function runContextualSearchRequest(
  request: Request,
  execute: SqlExecutor,
  elapsed: () => number,
  clock: () => Date = () => new Date(),
): Promise<Response> {
  const params = parseContextualSearchParams(new URL(request.url).searchParams);
  const result = await searchContextualIntelligence(execute, params);
  return Response.json({
    ...result,
    elapsedMs: Math.max(0, Math.round(elapsed())),
    generatedAt: clock().toISOString(),
    database: "turso-libsql",
  }, { headers: { "Cache-Control": "private, max-age=30" } });
}
