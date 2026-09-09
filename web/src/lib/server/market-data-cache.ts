import { unstable_cache } from "next/cache";
import { normalizeDailyArticles, type DailyArticlesResponse } from "@/lib/daily-articles-contract";
import {
  normalizeEvidenceSearchResponse,
  type EvidenceSearchRequest,
  type EvidenceSearchResponse,
} from "@/lib/evidence-search-contract";
import { normalizeQuantitativeMarketPulse } from "@/lib/quantitative-market-pulse-contract";
import { getCategoryIndex } from "@/lib/server/category-index";
import { getDailyArticles } from "@/lib/server/daily-articles";
import {
  executeMarketSql,
  executeNewsSql,
  executeTimeseriesSql,
  fetchDashboardArticleDetail,
  fetchDashboardContextualEvidence,
  fetchDashboardDailyArticles,
  fetchDashboardMacroTimeseries,
  fetchDashboardMarketPulse,
  fetchDashboardPermitTimeseries,
  getDashboardDataProvider,
  getProjectCacheNamespace,
  getServingManifest,
} from "@/lib/server/db";
import { normalizeDocumentDetail, getDocumentDetail, type DocumentDetail } from "@/lib/server/document-intelligence";
import { searchLocalArticleEvidence } from "@/lib/server/evidence-search";
import { getInsightSignals } from "@/lib/server/insight-signals";
import { getKeywordAnalytics } from "@/lib/server/keyword-analytics";
import { normalizeCanonicalMacroTimeseries, getMacroTimeseries } from "@/lib/server/macro-timeseries";
import { searchMarket } from "@/lib/server/market-search";
import { getModelInterpretations } from "@/lib/server/model-interpretations";
import { getOperationsOverview } from "@/lib/server/operations-insights";
import { getOperationsTimeline } from "@/lib/server/operations-timeline";
import { normalizeCanonicalPermitTimeseries, getPermitTimeseries } from "@/lib/server/permit-timeseries";
import { getQuantitativeMarketPulse } from "@/lib/server/quantitative-market-pulse";
import {
  dashboardProcessDataCache,
  resetDashboardProcessDataCache,
  stableCacheKey,
} from "@/lib/server/bounded-data-cache";
import type { PermitTimeseriesRequest, PermitTimeseriesResponse } from "@/lib/permit-timeseries-contract";
import type { SearchRequest } from "@/lib/search-contract";

const MANIFEST_REVALIDATE_SECONDS = 30;
const NEWS_REVALIDATE_SECONDS = 15 * 60;
const MACRO_REVALIDATE_SECONDS = 60 * 60;
const WEEKLY_MARKET_REVALIDATE_SECONDS = 6 * 60 * 60;
const INTERACTIVE_REVALIDATE_SECONDS = 30;
const NEGATIVE_TTL_MS = 20_000;

type CacheMetrics = {
  persistentLoads: Record<string, number>;
};
type CacheMetricsGlobal = typeof globalThis & { __creDashboardCacheMetrics?: CacheMetrics };
const metricsGlobal = globalThis as CacheMetricsGlobal;

function metrics() {
  return metricsGlobal.__creDashboardCacheMetrics ??= { persistentLoads: {} };
}

function notePersistentLoad(scope: string) {
  const current = metrics();
  current.persistentLoads[scope] = (current.persistentLoads[scope] ?? 0) + 1;
}

class NegativePersistentResult<T> extends Error {
  constructor(readonly value: T) {
    super("Short-lived negative dashboard result");
    this.name = "NegativePersistentResult";
  }
}

async function positivePersistentLoad<T>(
  scope: string,
  loader: () => Promise<T>,
  isNegative: (value: T) => boolean,
) {
  notePersistentLoad(scope);
  const loaded = await loader();
  // Next's data cache must not retain an empty snapshot for a full data TTL.
  // Throwing bypasses persistent storage; the outer bounded process cache still
  // absorbs a short burst with NEGATIVE_TTL_MS.
  if (isNegative(loaded)) throw new NegativePersistentResult(loaded);
  return loaded;
}

async function unwrapNegative<T>(loader: () => Promise<T>) {
  try {
    return await loader();
  } catch (error) {
    if (error instanceof NegativePersistentResult) return error.value as T;
    throw error;
  }
}

const persistentManifest = unstable_cache(
  (projectNamespace: string) => {
    void projectNamespace;
    return positivePersistentLoad("manifest", getServingManifest, () => false);
  },
  ["cre-dashboard-serving-manifest-v1"],
  { revalidate: MANIFEST_REVALIDATE_SECONDS, tags: ["cre-dashboard-serving-manifest"] },
);

async function cacheNamespace() {
  const projectNamespace = getProjectCacheNamespace();
  const manifest = await dashboardProcessDataCache().get(
    stableCacheKey("manifest", projectNamespace, null),
    () => persistentManifest(projectNamespace),
    {
      ttlMs: MANIFEST_REVALIDATE_SECONDS * 1_000,
      negativeTtlMs: NEGATIVE_TTL_MS,
      isNegative: () => false,
    },
  );
  return {
    datasetVersion: manifest.datasetVersion,
    namespace: `${projectNamespace}:${manifest.datasetVersion}`,
  };
}

type PersistentLoader<Input, Output> = (
  namespace: string,
  input: Input,
  datasetVersion: string,
) => Promise<Output>;

async function cachedData<Input, Output>(
  scope: string,
  input: Input,
  persistent: PersistentLoader<Input, Output>,
  ttlSeconds: number,
  isNegative: (value: Output) => boolean,
) {
  const { namespace, datasetVersion } = await cacheNamespace();
  return dashboardProcessDataCache().get(
    stableCacheKey(scope, namespace, input),
    () => unwrapNegative(() => persistent(namespace, input, datasetVersion)),
    {
      ttlMs: ttlSeconds * 1_000,
      negativeTtlMs: NEGATIVE_TTL_MS,
      isNegative,
    },
  );
}

async function loadDailyArticles(selectedDate: string, datasetVersion: string) {
  return getDashboardDataProvider() === "supabase"
    ? normalizeDailyArticles(await fetchDashboardDailyArticles(selectedDate, datasetVersion))
    : getDailyArticles(executeNewsSql, selectedDate);
}

const persistentDailyArticles = unstable_cache(
  (_namespace: string, selectedDate: string, datasetVersion: string) => positivePersistentLoad(
    "daily-articles",
    () => loadDailyArticles(selectedDate, datasetVersion),
    (value) => value.articles.length === 0,
  ),
  ["cre-dashboard-daily-articles-v4"],
  { revalidate: NEWS_REVALIDATE_SECONDS, tags: ["cre-dashboard-daily-articles"] },
);

export const getCachedDailyArticles = (selectedDate: string): Promise<DailyArticlesResponse> => cachedData(
  "daily-articles",
  selectedDate,
  persistentDailyArticles,
  NEWS_REVALIDATE_SECONDS,
  (value) => value.articles.length === 0,
);

async function loadArticleDetail(documentId: string, datasetVersion: string) {
  return getDashboardDataProvider() === "supabase"
    ? normalizeDocumentDetail(await fetchDashboardArticleDetail(documentId, datasetVersion))
    : getDocumentDetail(executeNewsSql, documentId, { allowArchiveFallback: false });
}

const persistentArticleDetail = unstable_cache(
  (_namespace: string, documentId: string, datasetVersion: string) => positivePersistentLoad(
    "article-detail",
    () => loadArticleDetail(documentId, datasetVersion),
    (value) => value === null,
  ),
  ["cre-dashboard-article-detail-v2"],
  { revalidate: NEWS_REVALIDATE_SECONDS, tags: ["cre-dashboard-article-detail"] },
);

export const getCachedArticleDetail = (documentId: string): Promise<DocumentDetail | null> => cachedData(
  "article-detail",
  documentId,
  persistentArticleDetail,
  NEWS_REVALIDATE_SECONDS,
  (value) => value === null,
);

async function loadMacroTimeseries(datasetVersion: string) {
  return getDashboardDataProvider() === "supabase"
    ? normalizeCanonicalMacroTimeseries(await fetchDashboardMacroTimeseries(datasetVersion))
    : getMacroTimeseries(executeTimeseriesSql);
}

const persistentMacroTimeseries = unstable_cache(
  (_namespace: string, _input: null, datasetVersion: string) => positivePersistentLoad(
    "macro-timeseries",
    () => loadMacroTimeseries(datasetVersion),
    () => false,
  ),
  ["cre-dashboard-macro-timeseries-v3"],
  { revalidate: MACRO_REVALIDATE_SECONDS, tags: ["cre-dashboard-macro-timeseries"] },
);

export const getCachedMacroTimeseries = () => cachedData(
  "macro-timeseries",
  null,
  persistentMacroTimeseries,
  MACRO_REVALIDATE_SECONDS,
  () => false,
);

async function loadPermitTimeseries(request: PermitTimeseriesRequest, datasetVersion: string) {
  return getDashboardDataProvider() === "supabase"
    ? normalizeCanonicalPermitTimeseries(await fetchDashboardPermitTimeseries(request, datasetVersion))
    : getPermitTimeseries(executeTimeseriesSql, request);
}

const persistentPermitTimeseries = unstable_cache(
  (_namespace: string, request: PermitTimeseriesRequest, datasetVersion: string) => positivePersistentLoad(
    "permit-timeseries",
    () => loadPermitTimeseries(request, datasetVersion),
    (value) => value.series.length === 0,
  ),
  ["cre-dashboard-permit-timeseries-v2"],
  { revalidate: WEEKLY_MARKET_REVALIDATE_SECONDS, tags: ["cre-dashboard-permit-timeseries"] },
);

export const getCachedPermitTimeseries = (
  request: PermitTimeseriesRequest,
): Promise<PermitTimeseriesResponse> => cachedData(
  "permit-timeseries",
  request,
  persistentPermitTimeseries,
  WEEKLY_MARKET_REVALIDATE_SECONDS,
  (value) => value.series.length === 0,
);

async function loadMarketPulse(datasetVersion: string) {
  return getDashboardDataProvider() === "supabase"
    ? normalizeQuantitativeMarketPulse(await fetchDashboardMarketPulse(datasetVersion))
    : getQuantitativeMarketPulse(executeTimeseriesSql);
}

const persistentMarketPulse = unstable_cache(
  (_namespace: string, _input: null, datasetVersion: string) => positivePersistentLoad(
    "market-pulse",
    () => loadMarketPulse(datasetVersion),
    () => false,
  ),
  ["cre-dashboard-market-pulse-v5"],
  { revalidate: WEEKLY_MARKET_REVALIDATE_SECONDS, tags: ["cre-dashboard-market-pulse"] },
);

export const getCachedQuantitativeMarketPulse = () => cachedData(
  "market-pulse",
  null,
  persistentMarketPulse,
  WEEKLY_MARKET_REVALIDATE_SECONDS,
  () => false,
);

async function loadEvidenceSearch(request: EvidenceSearchRequest, datasetVersion: string) {
  return getDashboardDataProvider() === "supabase"
    ? normalizeEvidenceSearchResponse(
      await fetchDashboardContextualEvidence(request, datasetVersion),
      request,
      datasetVersion,
    )
    : searchLocalArticleEvidence(executeNewsSql, request, datasetVersion);
}

const persistentEvidenceSearch = unstable_cache(
  (_namespace: string, request: EvidenceSearchRequest, datasetVersion: string) => positivePersistentLoad(
    "evidence-search",
    () => loadEvidenceSearch(request, datasetVersion),
    (value) => value.items.length === 0,
  ),
  ["cre-dashboard-evidence-search-v1"],
  { revalidate: INTERACTIVE_REVALIDATE_SECONDS, tags: ["cre-dashboard-evidence-search"] },
);

export const getCachedEvidenceSearch = (
  request: EvidenceSearchRequest,
): Promise<EvidenceSearchResponse> => cachedData(
  "evidence-search",
  request,
  persistentEvidenceSearch,
  INTERACTIVE_REVALIDATE_SECONDS,
  (value) => value.items.length === 0,
);

// The following legacy analytical endpoints remain available only to the
// explicit local sqlite provider. Hosted Supabase never falls back to the old
// Turso/archive authority when a compact RPC is absent.
const persistentCategoryIndex = unstable_cache(
  (namespace: string, input: null) => {
    void namespace;
    void input;
    return positivePersistentLoad("category-index", () => getCategoryIndex(executeMarketSql), () => false);
  },
  ["cre-dashboard-local-category-index-v4"],
  { revalidate: NEWS_REVALIDATE_SECONDS, tags: ["cre-dashboard-category-index"] },
);
export const getCachedCategoryIndex = () => cachedData(
  "category-index", null, persistentCategoryIndex, NEWS_REVALIDATE_SECONDS, () => false,
);

const persistentOperationsOverview = unstable_cache(
  (namespace: string, input: null) => {
    void namespace;
    void input;
    return positivePersistentLoad("operations-overview", () => getOperationsOverview(executeMarketSql), () => false);
  },
  ["cre-dashboard-local-operations-overview-v3"],
  { revalidate: 300, tags: ["cre-dashboard-operations"] },
);
export const getCachedOperationsOverview = () => cachedData(
  "operations-overview", null, persistentOperationsOverview, 300, () => false,
);

const persistentOperationsTimeline = unstable_cache(
  (_namespace: string, windowDays: number) => positivePersistentLoad(
    "operations-timeline", () => getOperationsTimeline(executeMarketSql, windowDays), () => false,
  ),
  ["cre-dashboard-local-operations-timeline-v3"],
  { revalidate: 300, tags: ["cre-dashboard-operations"] },
);
export const getCachedOperationsTimeline = (windowDays: number) => cachedData(
  "operations-timeline", windowDays, persistentOperationsTimeline, 300, () => false,
);

type LimitAndFlag = { limit: number; flag: boolean };
const persistentKeywordAnalytics = unstable_cache(
  (_namespace: string, input: LimitAndFlag) => positivePersistentLoad(
    "keyword-analytics",
    () => getKeywordAnalytics(executeMarketSql, input.limit, input.flag),
    () => false,
  ),
  ["cre-dashboard-local-keyword-analytics-v3"],
  { revalidate: 300, tags: ["cre-dashboard-analytics"] },
);
export const getCachedKeywordAnalytics = (limit: number, briefingPriority = false) => cachedData(
  "keyword-analytics",
  { limit, flag: briefingPriority },
  persistentKeywordAnalytics,
  300,
  () => false,
);

const persistentInsightSignals = unstable_cache(
  (_namespace: string, input: LimitAndFlag) => positivePersistentLoad(
    "insight-signals",
    () => getInsightSignals(executeMarketSql, input.limit, input.flag),
    () => false,
  ),
  ["cre-dashboard-local-insight-signals-v3"],
  { revalidate: 300, tags: ["cre-dashboard-analytics"] },
);
export const getCachedInsightSignals = (limit: number, reviewableOnly = false) => cachedData(
  "insight-signals",
  { limit, flag: reviewableOnly },
  persistentInsightSignals,
  300,
  () => false,
);

const persistentModelInterpretations = unstable_cache(
  (_namespace: string, limit: number) => positivePersistentLoad(
    "model-interpretations", () => getModelInterpretations(executeMarketSql, limit), () => false,
  ),
  ["cre-dashboard-local-model-interpretations-v2"],
  { revalidate: 300, tags: ["cre-dashboard-analytics"] },
);
export const getCachedModelInterpretations = (limit: number) => cachedData(
  "model-interpretations", limit, persistentModelInterpretations, 300, () => false,
);

const persistentMarketSearch = unstable_cache(
  (_namespace: string, request: SearchRequest) => positivePersistentLoad(
    "market-search",
    () => searchMarket(executeMarketSql, request),
    (value) => value.results.length === 0,
  ),
  ["cre-dashboard-local-market-search-v4"],
  { revalidate: INTERACTIVE_REVALIDATE_SECONDS, tags: ["cre-dashboard-market-search"] },
);
export const getCachedMarketSearch = (request: SearchRequest) => cachedData(
  "market-search",
  request,
  persistentMarketSearch,
  INTERACTIVE_REVALIDATE_SECONDS,
  (value) => value.results.length === 0,
);

export function getMarketDataCacheDiagnostics() {
  return {
    process: dashboardProcessDataCache().diagnostics(),
    persistentLoads: { ...metrics().persistentLoads },
  };
}

export function resetMarketDataCacheDiagnostics() {
  resetDashboardProcessDataCache();
  metricsGlobal.__creDashboardCacheMetrics = { persistentLoads: {} };
}
