import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EvidenceSearchRequest } from "@/lib/evidence-search-contract";

const mocks = vi.hoisted(() => ({
  persistent: new Map<string, { expiresAt: number; value: unknown }>(),
  projectNamespace: "project-a",
  manifestVersion: "dataset-v1",
  getServingManifest: vi.fn(),
  fetchDaily: vi.fn(),
  fetchEvidence: vi.fn(),
  noop: vi.fn(),
}));

vi.mock("next/cache", () => ({
  unstable_cache: (
    loader: (...args: unknown[]) => Promise<unknown>,
    keyParts: string[],
    options?: { revalidate?: number },
  ) => async (...args: unknown[]) => {
    const key = JSON.stringify([keyParts, args]);
    const cached = mocks.persistent.get(key);
    if (cached && cached.expiresAt > Date.now()) return cached.value;
    const value = await loader(...args);
    mocks.persistent.set(key, {
      expiresAt: Date.now() + (options?.revalidate ?? 0) * 1_000,
      value,
    });
    return value;
  },
}));

vi.mock("@/lib/server/db", () => ({
  executeMarketSql: mocks.noop,
  executeNewsSql: mocks.noop,
  executeTimeseriesSql: mocks.noop,
  getDashboardDataProvider: () => "supabase",
  getProjectCacheNamespace: () => mocks.projectNamespace,
  getServingManifest: mocks.getServingManifest,
  fetchDashboardDailyArticles: mocks.fetchDaily,
  fetchDashboardArticleDetail: mocks.noop,
  fetchDashboardMacroTimeseries: mocks.noop,
  fetchDashboardMarketPulse: mocks.noop,
  fetchDashboardPermitTimeseries: mocks.noop,
  fetchDashboardContextualEvidence: mocks.fetchEvidence,
}));

vi.mock("@/lib/server/category-index", () => ({ getCategoryIndex: mocks.noop }));
vi.mock("@/lib/server/daily-articles", () => ({ getDailyArticles: mocks.noop }));
vi.mock("@/lib/server/document-intelligence", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/document-intelligence")>("@/lib/server/document-intelligence");
  return { ...actual, getDocumentDetail: mocks.noop };
});
vi.mock("@/lib/server/evidence-search", () => ({ searchLocalArticleEvidence: mocks.noop }));
vi.mock("@/lib/server/insight-signals", () => ({ getInsightSignals: mocks.noop }));
vi.mock("@/lib/server/keyword-analytics", () => ({ getKeywordAnalytics: mocks.noop }));
vi.mock("@/lib/server/macro-timeseries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/macro-timeseries")>("@/lib/server/macro-timeseries");
  return { ...actual, getMacroTimeseries: mocks.noop };
});
vi.mock("@/lib/server/market-search", () => ({ searchMarket: mocks.noop }));
vi.mock("@/lib/server/model-interpretations", () => ({ getModelInterpretations: mocks.noop }));
vi.mock("@/lib/server/operations-insights", () => ({ getOperationsOverview: mocks.noop }));
vi.mock("@/lib/server/operations-timeline", () => ({ getOperationsTimeline: mocks.noop }));
vi.mock("@/lib/server/permit-timeseries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/permit-timeseries")>("@/lib/server/permit-timeseries");
  return { ...actual, getPermitTimeseries: mocks.noop };
});
vi.mock("@/lib/server/quantitative-market-pulse", () => ({ getQuantitativeMarketPulse: mocks.noop }));

function dailyPayload(title: string, empty = false) {
  return {
    datasetVersion: mocks.manifestVersion,
    selectedDate: "2026-09-09",
    latestAvailableDate: "2026-09-09",
    lastCollectedAt: "2026-09-09T00:00:00Z",
    generatedAt: "2026-09-09T00:01:00Z",
    total: empty ? 0 : 1,
    returned: empty ? 0 : 1,
    articles: empty ? [] : [{
      id: "doc-1", title, publisher: "뉴스", publishedAt: "2026-09-09T00:00:00Z",
      collectedAt: "2026-09-09T00:00:10Z", summary: "요약", summaryMode: "BODY_EXTRACTIVE",
      summaryGeneratedAt: null, href: "https://example.com/1", topics: [],
    }],
  };
}

function evidencePayload(request: EvidenceSearchRequest, version: string) {
  return {
    datasetVersion: version,
    query: request.q,
    generatedAt: "2026-09-09T00:00:00Z",
    filters: { from: request.from, to: request.to, topic: request.topic },
    returned: 1,
    truncated: false,
    items: [{
      documentId: `${request.topic ?? "all"}-${request.from ?? "all"}`,
      title: request.q, publisher: "뉴스", publishedAt: "2026-09-09T00:00:00Z",
      href: "https://example.com/1", evidenceText: `${request.q} 기사`, score: 1,
    }],
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-09T00:00:00Z"));
  vi.resetModules();
  mocks.persistent.clear();
  mocks.projectNamespace = "project-a";
  mocks.manifestVersion = "dataset-v1";
  mocks.getServingManifest.mockReset().mockImplementation(async () => ({
    datasetVersion: mocks.manifestVersion,
    sourceAsOfAt: null, activatedAt: null, schemaVersion: "4.0.0", rowCounts: {}, tableHashes: {},
  }));
  mocks.fetchDaily.mockReset().mockImplementation(async () => dailyPayload("정상 기사"));
  mocks.fetchEvidence.mockReset().mockImplementation(async (request: EvidenceSearchRequest, version: string) => (
    evidencePayload(request, version)
  ));
  mocks.noop.mockReset();
  delete (globalThis as typeof globalThis & { __creDashboardProcessDataCache?: unknown }).__creDashboardProcessDataCache;
  delete (globalThis as typeof globalThis & { __creDashboardCacheMetrics?: unknown }).__creDashboardCacheMetrics;
});

afterEach(() => vi.useRealTimers());

describe("market data cache", () => {
  it("separates manifest calls from data calls and makes warm requests without another database load", async () => {
    const cache = await import("@/lib/server/market-data-cache");
    const cold = await cache.getCachedDailyArticles("LATEST");
    const warm = await cache.getCachedDailyArticles("LATEST");
    expect(warm).toEqual(cold);
    expect(mocks.getServingManifest).toHaveBeenCalledTimes(1);
    expect(mocks.fetchDaily).toHaveBeenCalledTimes(1);
    expect(mocks.fetchDaily).toHaveBeenCalledWith("LATEST", "dataset-v1");
    expect(cache.getMarketDataCacheDiagnostics().process.hits).toBeGreaterThanOrEqual(1);
  });

  it("keeps date and topic filters isolated while coalescing an identical evidence search", async () => {
    const cache = await import("@/lib/server/market-data-cache");
    const base: EvidenceSearchRequest = { q: "매각", from: null, to: null, topic: null, topK: 8 };
    const topic = { ...base, topic: "SALE" };
    const dated = { ...base, from: "2026-09-01" };
    const [first, same] = await Promise.all([
      cache.getCachedEvidenceSearch(base), cache.getCachedEvidenceSearch(base),
    ]);
    await cache.getCachedEvidenceSearch(topic);
    await cache.getCachedEvidenceSearch(dated);
    expect(same).toEqual(first);
    expect(mocks.fetchEvidence).toHaveBeenCalledTimes(3);
    expect(mocks.fetchEvidence.mock.calls.map(([request]) => request)).toEqual([base, topic, dated]);
  });

  it("switches to a fresh payload after the manifest version changes", async () => {
    const cache = await import("@/lib/server/market-data-cache");
    await cache.getCachedDailyArticles("LATEST");
    mocks.manifestVersion = "dataset-v2";
    mocks.fetchDaily.mockImplementation(async (_date: string, version: string) => ({
      ...dailyPayload(version === "dataset-v2" ? "신규 기사" : "기존 기사"), datasetVersion: version,
    }));
    await vi.advanceTimersByTimeAsync(31_000);
    const current = await cache.getCachedDailyArticles("LATEST");
    expect(current.articles[0].title).toBe("신규 기사");
    expect(mocks.getServingManifest).toHaveBeenCalledTimes(2);
    expect(mocks.fetchDaily.mock.calls.map(([, version]) => version)).toEqual(["dataset-v1", "dataset-v2"]);
  });

  it("does not let an invalid or failed refresh poison the next healthy request", async () => {
    const cache = await import("@/lib/server/market-data-cache");
    const healthy = await cache.getCachedDailyArticles("LATEST");
    mocks.fetchDaily.mockResolvedValue({ invalid: true });
    expect(await cache.getCachedDailyArticles("LATEST")).toEqual(healthy);
    expect(mocks.fetchDaily).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(15 * 60 * 1_000 + 1);
    await expect(cache.getCachedDailyArticles("LATEST")).rejects.toThrow(/Invalid daily articles payload/u);
    mocks.fetchDaily.mockImplementation(async () => dailyPayload("복구 기사"));
    await expect(cache.getCachedDailyArticles("LATEST")).resolves.toMatchObject({
      articles: [{ title: "복구 기사" }],
    });
    expect(mocks.fetchDaily).toHaveBeenCalledTimes(3);
  });

  it("keeps empty results only for the short negative TTL and never in the persistent tier", async () => {
    mocks.fetchDaily.mockImplementation(async () => dailyPayload("", true));
    const cache = await import("@/lib/server/market-data-cache");
    await cache.getCachedDailyArticles("LATEST");
    await cache.getCachedDailyArticles("LATEST");
    expect(mocks.fetchDaily).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(20_001);
    await cache.getCachedDailyArticles("LATEST");
    expect(mocks.fetchDaily).toHaveBeenCalledTimes(2);
  });

  it("uses the persistent Next data tier across a cleared process cache", async () => {
    const cache = await import("@/lib/server/market-data-cache");
    await cache.getCachedDailyArticles("LATEST");
    cache.resetMarketDataCacheDiagnostics();
    await cache.getCachedDailyArticles("LATEST");
    expect(mocks.fetchDaily).toHaveBeenCalledTimes(1);
    expect(mocks.getServingManifest).toHaveBeenCalledTimes(1);
  });

  it("isolates cache entries by Supabase project namespace", async () => {
    const cache = await import("@/lib/server/market-data-cache");
    await cache.getCachedDailyArticles("LATEST");
    mocks.projectNamespace = "project-b";
    cache.resetMarketDataCacheDiagnostics();
    await cache.getCachedDailyArticles("LATEST");
    expect(mocks.getServingManifest).toHaveBeenCalledTimes(2);
    expect(mocks.fetchDaily).toHaveBeenCalledTimes(2);
  });
});
