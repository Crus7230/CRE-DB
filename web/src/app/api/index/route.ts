import { getCategoryIndex } from "@/lib/server/category-index";
import { runCategoryIndexRequest } from "@/lib/server/category-route";
import { executeMarketSql } from "@/lib/server/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return runCategoryIndexRequest(() => getCategoryIndex(executeMarketSql));
}
