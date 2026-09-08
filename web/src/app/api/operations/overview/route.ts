import { getCachedOperationsOverview } from "@/lib/server/market-data-cache";
import { runOperationsOverviewRequest } from "@/lib/server/operations-insights-route";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return runOperationsOverviewRequest(getCachedOperationsOverview);
}
