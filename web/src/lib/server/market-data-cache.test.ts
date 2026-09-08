import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PermitTimeseriesRequest } from "@/lib/permit-timeseries-contract";
import type { SearchRequest } from "@/lib/search-contract";

const mocks = vi.hoisted(() => ({
  authorityNamespace: vi.fn(() => "url-authority-test"),
  cacheInvocations: [] as Array<{ key: string; args: unknown[] }>,
  services: {
    categoryIndex: vi.fn(),
    dailyArticles: vi.fn(),
    operationsOverview: vi.fn(),
    operationsTimeline: vi.fn(),
    keywordAnalytics: vi.fn(),
    insightSignals: vi.fn(),
    modelInterpretations: vi.fn(),
    quantitativePulse: vi.fn(),
    macroTimeseries: vi.fn(),
    permitTimeseries: vi.fn(),
    marketSearch: vi.fn(),
  },
}));

vi.mock("next/cache", () => ({
  unstable_cache: vi.fn((
    loader: (...args: unknown[]) => unknown,
    keyParts: string[],
  ) => (...args: unknown[]) => {
    mocks.cacheInvocations.push({ key: keyParts[0] ?? "", args });
    return loader(...args);
  }),
}));
vi.mock("@/lib/server/db", () => ({
  executeMarketSql: vi.fn(),
  getMarketCacheAuthorityNamespace: mocks.authorityNamespace,
}));
vi.mock("@/lib/server/category-index", () => ({ getCategoryIndex: mocks.services.categoryIndex }));
vi.mock("@/lib/server/daily-articles", () => ({ getDailyArticles: mocks.services.dailyArticles }));
vi.mock("@/lib/server/operations-insights", () => ({ getOperationsOverview: mocks.services.operationsOverview }));
vi.mock("@/lib/server/operations-timeline", () => ({ getOperationsTimeline: mocks.services.operationsTimeline }));
vi.mock("@/lib/server/keyword-analytics", () => ({ getKeywordAnalytics: mocks.services.keywordAnalytics }));
vi.mock("@/lib/server/insight-signals", () => ({ getInsightSignals: mocks.services.insightSignals }));
vi.mock("@/lib/server/model-interpretations", () => ({ getModelInterpretations: mocks.services.modelInterpretations }));
vi.mock("@/lib/server/quantitative-market-pulse", () => ({ getQuantitativeMarketPulse: mocks.services.quantitativePulse }));
vi.mock("@/lib/server/macro-timeseries", () => ({ getMacroTimeseries: mocks.services.macroTimeseries }));
vi.mock("@/lib/server/permit-timeseries", () => ({ getPermitTimeseries: mocks.services.permitTimeseries }));
vi.mock("@/lib/server/market-search", () => ({ searchMarket: mocks.services.marketSearch }));

beforeEach(() => {
  vi.resetModules();
  mocks.authorityNamespace.mockClear();
  mocks.cacheInvocations.length = 0;
  for (const service of Object.values(mocks.services)) {
    service.mockReset();
    service.mockResolvedValue({});
  }
});

describe("market data cache authority", () => {
  it("resolves the database namespace lazily and includes it in every persistent cache call", async () => {
    const cache = await import("@/lib/server/market-data-cache");
    expect(mocks.authorityNamespace).not.toHaveBeenCalled();

    const permitRequest: PermitTimeseriesRequest = {
      groupBy: "EVENT_TYPE",
      from: null,
      to: null,
      eventType: "PERMIT",
      assetType: null,
      district: null,
      constructionAction: null,
    };
    const searchRequest: SearchRequest = {
      q: "office",
      kind: "ALL",
      category: "",
      classificationScheme: "",
      from: null,
      to: null,
      page: 1,
      pageSize: 20,
      includeTransactionsUnder1000Eok: false,
    };

    await Promise.all([
      cache.getCachedCategoryIndex(),
      cache.getCachedDailyArticles("2026-09-08"),
      cache.getCachedOperationsOverview(),
      cache.getCachedOperationsTimeline(30),
      cache.getCachedKeywordAnalytics(10, true),
      cache.getCachedInsightSignals(10, true),
      cache.getCachedModelInterpretations(10),
      cache.getCachedQuantitativeMarketPulse(),
      cache.getCachedMacroTimeseries(),
      cache.getCachedPermitTimeseries(permitRequest),
      cache.getCachedMarketSearch(searchRequest),
    ]);

    expect(mocks.authorityNamespace).toHaveBeenCalledTimes(11);
    expect(mocks.cacheInvocations).toHaveLength(11);
    expect(new Set(mocks.cacheInvocations.map(({ key }) => key)).size).toBe(11);
    for (const invocation of mocks.cacheInvocations) {
      expect(invocation.args[0]).toBe("url-authority-test");
    }
    expect(mocks.cacheInvocations.find(({ key }) => key.includes("daily-articles"))?.args)
      .toEqual(["url-authority-test", "2026-09-08"]);
    expect(mocks.cacheInvocations.find(({ key }) => key.includes("permit-timeseries"))?.args)
      .toEqual(["url-authority-test", permitRequest]);
  });

  it("uses a changed authority namespace as a distinct argument to the same cache factory", async () => {
    const cache = await import("@/lib/server/market-data-cache");
    mocks.authorityNamespace
      .mockReturnValueOnce("url-local-qa")
      .mockReturnValueOnce("url-production-turso");

    await cache.getCachedDailyArticles("2026-09-08");
    await cache.getCachedDailyArticles("2026-09-08");

    const dailyCalls = mocks.cacheInvocations.filter(({ key }) => key.includes("daily-articles"));
    expect(dailyCalls.map(({ args }) => args)).toEqual([
      ["url-local-qa", "2026-09-08"],
      ["url-production-turso", "2026-09-08"],
    ]);
  });
});
