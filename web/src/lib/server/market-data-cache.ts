import { unstable_cache } from "next/cache";
import { getCategoryIndex } from "@/lib/server/category-index";
import { getDailyArticles } from "@/lib/server/daily-articles";
import { executeMarketSql, getMarketCacheAuthorityNamespace } from "@/lib/server/db";
import { getInsightSignals } from "@/lib/server/insight-signals";
import { getKeywordAnalytics } from "@/lib/server/keyword-analytics";
import { getModelInterpretations } from "@/lib/server/model-interpretations";
import { searchMarket } from "@/lib/server/market-search";
import { getOperationsOverview } from "@/lib/server/operations-insights";
import { getOperationsTimeline } from "@/lib/server/operations-timeline";
import { getQuantitativeMarketPulse } from "@/lib/server/quantitative-market-pulse";
import { getMacroTimeseries } from "@/lib/server/macro-timeseries";
import { getPermitTimeseries } from "@/lib/server/permit-timeseries";
import type { SearchRequest } from "@/lib/search-contract";
import type { PermitTimeseriesRequest } from "@/lib/permit-timeseries-contract";

// These projections are identical for every approved user. Cache windows track
// each source cadence so a weekly dataset cannot repeatedly spend remote reads
// while faster news remains reasonably fresh. Maximum post-refresh visibility
// delay is therefore 15 minutes for news, 1 hour for macro, and 6 hours for the
// weekly transaction / permit projections.
const NEWS_REVALIDATE_SECONDS = 15 * 60;
const MACRO_REVALIDATE_SECONDS = 60 * 60;
const WEEKLY_MARKET_REVALIDATE_SECONDS = 6 * 60 * 60;

const cachedCategoryIndex = unstable_cache(
  (cacheAuthority: string) => {
    void cacheAuthority;
    return getCategoryIndex(executeMarketSql);
  },
  ["cre-db-turso-category-index-v3"],
  { revalidate: NEWS_REVALIDATE_SECONDS, tags: ["cre-db-turso-category-index"] },
);
export const getCachedCategoryIndex = () => cachedCategoryIndex(getMarketCacheAuthorityNamespace());

const cachedDailyArticles = unstable_cache(
  (_cacheAuthority: string, selectedDate: string) => getDailyArticles(executeMarketSql, selectedDate),
  ["cre-db-turso-daily-articles-v3"],
  { revalidate: NEWS_REVALIDATE_SECONDS, tags: ["cre-db-turso-daily-articles"] },
);
export const getCachedDailyArticles = (selectedDate: string) => (
  cachedDailyArticles(getMarketCacheAuthorityNamespace(), selectedDate)
);

const cachedOperationsOverview = unstable_cache(
  (cacheAuthority: string) => {
    void cacheAuthority;
    return getOperationsOverview(executeMarketSql);
  },
  ["cre-db-turso-operations-overview-v2"],
  { revalidate: 300, tags: ["cre-db-turso-operations"] },
);
export const getCachedOperationsOverview = () => cachedOperationsOverview(getMarketCacheAuthorityNamespace());

const cachedOperationsTimeline = unstable_cache(
  (_cacheAuthority: string, windowDays: number) => getOperationsTimeline(executeMarketSql, windowDays),
  ["cre-db-turso-operations-timeline-v2"],
  { revalidate: 300, tags: ["cre-db-turso-operations"] },
);
export const getCachedOperationsTimeline = (windowDays: number) => (
  cachedOperationsTimeline(getMarketCacheAuthorityNamespace(), windowDays)
);

const cachedKeywordAnalytics = unstable_cache(
  (_cacheAuthority: string, limit: number, briefingPriority = false) => (
    getKeywordAnalytics(executeMarketSql, limit, briefingPriority)
  ),
  ["cre-db-turso-keyword-analytics-v2"],
  { revalidate: 300, tags: ["cre-db-turso-analytics"] },
);
export const getCachedKeywordAnalytics = (limit: number, briefingPriority = false) => (
  cachedKeywordAnalytics(getMarketCacheAuthorityNamespace(), limit, briefingPriority)
);

const cachedInsightSignals = unstable_cache(
  (_cacheAuthority: string, limit: number, reviewableOnly = false) => (
    getInsightSignals(executeMarketSql, limit, reviewableOnly)
  ),
  ["cre-db-turso-insight-signals-v2"],
  { revalidate: 300, tags: ["cre-db-turso-analytics"] },
);
export const getCachedInsightSignals = (limit: number, reviewableOnly = false) => (
  cachedInsightSignals(getMarketCacheAuthorityNamespace(), limit, reviewableOnly)
);

const cachedModelInterpretations = unstable_cache(
  (_cacheAuthority: string, limit: number) => getModelInterpretations(executeMarketSql, limit),
  ["cre-db-turso-model-interpretations-v1"],
  { revalidate: 300, tags: ["cre-db-turso-analytics"] },
);
export const getCachedModelInterpretations = (limit: number) => (
  cachedModelInterpretations(getMarketCacheAuthorityNamespace(), limit)
);

const cachedQuantitativeMarketPulse = unstable_cache(
  (cacheAuthority: string) => {
    void cacheAuthority;
    return getQuantitativeMarketPulse(executeMarketSql);
  },
  ["cre-db-turso-quantitative-market-pulse-v4"],
  { revalidate: WEEKLY_MARKET_REVALIDATE_SECONDS, tags: ["cre-db-turso-market-pulse"] },
);
export const getCachedQuantitativeMarketPulse = () => (
  cachedQuantitativeMarketPulse(getMarketCacheAuthorityNamespace())
);

const cachedMacroTimeseries = unstable_cache(
  (cacheAuthority: string) => {
    void cacheAuthority;
    return getMacroTimeseries(executeMarketSql);
  },
  ["cre-db-turso-macro-timeseries-v2"],
  { revalidate: MACRO_REVALIDATE_SECONDS, tags: ["cre-db-turso-macro-timeseries"] },
);
export const getCachedMacroTimeseries = () => cachedMacroTimeseries(getMarketCacheAuthorityNamespace());

const cachedPermitTimeseries = unstable_cache(
  (_cacheAuthority: string, request: PermitTimeseriesRequest) => getPermitTimeseries(executeMarketSql, request),
  ["cre-db-turso-permit-timeseries-v1"],
  { revalidate: WEEKLY_MARKET_REVALIDATE_SECONDS, tags: ["cre-db-turso-permit-timeseries"] },
);
export const getCachedPermitTimeseries = (request: PermitTimeseriesRequest) => (
  cachedPermitTimeseries(getMarketCacheAuthorityNamespace(), request)
);

// Short-lived exact-query caching absorbs repeated tab navigation and filter
// taps without making rapidly changing search results feel stale.
const cachedMarketSearch = unstable_cache(
  (_cacheAuthority: string, request: SearchRequest) => searchMarket(executeMarketSql, request),
  ["cre-db-turso-market-search-v3"],
  { revalidate: 30, tags: ["cre-db-turso-market-search"] },
);
export const getCachedMarketSearch = (request: SearchRequest) => (
  cachedMarketSearch(getMarketCacheAuthorityNamespace(), request)
);
