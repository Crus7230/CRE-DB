import { runCategoryIndexRequest } from "@/lib/server/category-route";
import { getCachedCategoryIndex } from "@/lib/server/market-data-cache";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return runCategoryIndexRequest(getCachedCategoryIndex);
}
