import "server-only";

import { unstable_cache } from "next/cache";
import type { LargeTransactionsRequest, LargeTransactionsResponse } from "@/lib/large-transactions-contract";
import {
  dashboardProcessDataCache,
  stableCacheKey,
} from "@/lib/server/bounded-data-cache";
import {
  executeTimeseriesSql,
  fetchDashboardMarketPulse,
  getDashboardDataProvider,
  getProjectCacheNamespace,
  getServingManifest,
} from "@/lib/server/db";
import {
  getLargeTransactions,
  getLargeTransactionsFromCompactSnapshot,
  LargeTransactionDetailUnavailableError,
  normalizeCompactLargeTransactionsPulse,
} from "@/lib/server/large-transactions";

const CACHE_TTL_MS = 30_000;
const COMPACT_REVALIDATE_SECONDS = 6 * 60 * 60;

export { LargeTransactionDetailUnavailableError };

const persistentCompactSnapshot = unstable_cache(
  async (projectNamespace: string, datasetVersion: string) => {
    void projectNamespace;
    return normalizeCompactLargeTransactionsPulse(
      await fetchDashboardMarketPulse(datasetVersion),
      datasetVersion,
    );
  },
  ["cre-dashboard-large-transactions-compact-v1"],
  {
    revalidate: COMPACT_REVALIDATE_SECONDS,
    tags: ["cre-dashboard-large-transactions-compact"],
  },
);

export async function getCachedLargeTransactions(
  request: LargeTransactionsRequest,
): Promise<LargeTransactionsResponse> {
  const provider = getDashboardDataProvider();
  const cache = dashboardProcessDataCache();
  const projectNamespace = getProjectCacheNamespace();
  const manifest = await cache.get(
    stableCacheKey("large-transactions-manifest", `${provider}:${projectNamespace}`, null),
    getServingManifest,
    { ttlMs: CACHE_TTL_MS, negativeTtlMs: CACHE_TTL_MS, isNegative: () => false },
  );
  const namespace = `${provider}:${projectNamespace}:${manifest.datasetVersion}`;
  if (provider === "supabase") {
    const compactSnapshot = await cache.get(
      stableCacheKey("large-transactions-compact", namespace, null),
      () => persistentCompactSnapshot(projectNamespace, manifest.datasetVersion),
      {
        ttlMs: COMPACT_REVALIDATE_SECONDS * 1_000,
        negativeTtlMs: CACHE_TTL_MS,
        isNegative: () => false,
      },
    );
    return cache.get(
      stableCacheKey("large-transactions", namespace, request),
      async () => getLargeTransactionsFromCompactSnapshot(compactSnapshot, request),
      { ttlMs: CACHE_TTL_MS, negativeTtlMs: CACHE_TTL_MS, isNegative: () => false },
    );
  }
  return cache.get(
    stableCacheKey("large-transactions", namespace, request),
    () => getLargeTransactions(
      executeTimeseriesSql,
      request,
      manifest.datasetVersion,
    ),
    { ttlMs: CACHE_TTL_MS, negativeTtlMs: CACHE_TTL_MS, isNegative: () => false },
  );
}
