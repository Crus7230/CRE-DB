import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LargeTransactionsResponse } from "@/lib/large-transactions-contract";

const mocks = vi.hoisted(() => ({
  persistent: new Map<string, unknown>(),
  provider: "sqlite" as "sqlite" | "supabase",
  projectNamespace: "project-a",
  manifestVersion: "dataset-v1",
  getProjectNamespace: vi.fn(),
  getManifest: vi.fn(),
  execute: vi.fn(),
  fetchPulse: vi.fn(),
  load: vi.fn(),
  normalizeCompact: vi.fn(),
  selectCompact: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({
  unstable_cache: (
    loader: (...args: unknown[]) => Promise<unknown>,
    keyParts: string[],
  ) => async (...args: unknown[]) => {
    const key = JSON.stringify([keyParts, args]);
    if (mocks.persistent.has(key)) return mocks.persistent.get(key);
    const value = await loader(...args);
    mocks.persistent.set(key, value);
    return value;
  },
}));
vi.mock("@/lib/server/db", () => ({
  executeTimeseriesSql: mocks.execute,
  fetchDashboardMarketPulse: mocks.fetchPulse,
  getDashboardDataProvider: () => mocks.provider,
  getProjectCacheNamespace: mocks.getProjectNamespace,
  getServingManifest: mocks.getManifest,
}));
vi.mock("@/lib/server/large-transactions", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/large-transactions")>(
    "@/lib/server/large-transactions",
  );
  return {
    ...actual,
    getLargeTransactions: mocks.load,
    normalizeCompactLargeTransactionsPulse: mocks.normalizeCompact,
    getLargeTransactionsFromCompactSnapshot: mocks.selectCompact,
  };
});

function emptyResponse(
  month: string,
  page: number,
  datasetVersion: string,
): LargeTransactionsResponse {
  return {
    datasetVersion,
    generatedAt: "2026-09-09T00:00:00Z",
    month,
    minAreaPyeong: 5_000,
    minAreaM2: 5_000 * 400 / 121,
    areaBasis: "TRANSACTED_BUILDING_AREA",
    totalCount: 0,
    baseTransactionCount: 0,
    page,
    pageSize: 20,
    totalPages: 0,
    rows: [],
    coverage: { status: "COMPLETE", expectedDistrictCount: 25, completedDistrictCount: 25 },
    source: {
      code: "MOLIT_REAL_TRANSACTION",
      label: "국토교통부 실거래 공개시스템",
      geography: "서울특별시",
      completedPartitionsOnly: true,
      exactPayloadDeduplicated: true,
      currentServingOnly: true,
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-10T00:00:00Z"));
  vi.resetModules();
  mocks.provider = "sqlite";
  mocks.projectNamespace = "project-a";
  mocks.manifestVersion = "dataset-v1";
  mocks.persistent.clear();
  mocks.getProjectNamespace.mockReset().mockImplementation(() => mocks.projectNamespace);
  mocks.getManifest.mockReset().mockImplementation(async () => ({
    datasetVersion: mocks.manifestVersion,
    sourceAsOfAt: null,
    activatedAt: null,
    schemaVersion: null,
    rowCounts: {},
    tableHashes: {},
  }));
  mocks.execute.mockReset();
  mocks.fetchPulse.mockReset().mockImplementation(async (version) => ({ datasetVersion: version }));
  mocks.load.mockReset().mockImplementation(async (_execute, request, version) => (
    emptyResponse(request.month, request.page, version)
  ));
  mocks.normalizeCompact.mockReset().mockImplementation((raw, version) => ({
    raw,
    datasetVersion: version,
  }));
  mocks.selectCompact.mockReset().mockImplementation((snapshot, request) => (
    emptyResponse(request.month, request.page, snapshot.datasetVersion)
  ));
  delete (globalThis as typeof globalThis & { __creDashboardProcessDataCache?: unknown })
    .__creDashboardProcessDataCache;
});

afterEach(() => vi.useRealTimers());

describe("large transactions cache", () => {
  it("singleflights identical page requests and isolates different pages", async () => {
    const cache = await import("@/lib/server/large-transactions-cache");
    const request = { month: "2026-07", page: 1 };
    await Promise.all([
      cache.getCachedLargeTransactions(request),
      cache.getCachedLargeTransactions(request),
    ]);
    await cache.getCachedLargeTransactions({ month: "2026-07", page: 2 });

    expect(mocks.getManifest).toHaveBeenCalledTimes(1);
    expect(mocks.load).toHaveBeenCalledTimes(2);
    expect(mocks.load.mock.calls.map(([, item]) => item.page)).toEqual([1, 2]);
  });

  it("keys data by provider namespace and dataset version and refreshes after the TTL", async () => {
    const cache = await import("@/lib/server/large-transactions-cache");
    const request = { month: "2026-07", page: 1 };
    await cache.getCachedLargeTransactions(request);
    await cache.getCachedLargeTransactions(request);
    expect(mocks.load).toHaveBeenCalledTimes(1);

    mocks.manifestVersion = "dataset-v2";
    await vi.advanceTimersByTimeAsync(30_001);
    const refreshed = await cache.getCachedLargeTransactions(request);
    expect(refreshed.datasetVersion).toBe("dataset-v2");
    expect(mocks.getManifest).toHaveBeenCalledTimes(2);
    expect(mocks.load).toHaveBeenCalledTimes(2);
  });

  it("loads and validates one versioned Supabase envelope for multiple requested pages", async () => {
    mocks.provider = "supabase";
    const cache = await import("@/lib/server/large-transactions-cache");
    await cache.getCachedLargeTransactions({ month: "2026-07", page: 1 });
    await cache.getCachedLargeTransactions({ month: "2026-07", page: 2 });

    expect(mocks.getProjectNamespace).toHaveBeenCalledTimes(2);
    expect(mocks.getManifest).toHaveBeenCalledTimes(1);
    expect(mocks.fetchPulse).toHaveBeenCalledTimes(1);
    expect(mocks.fetchPulse).toHaveBeenCalledWith("dataset-v1");
    expect(mocks.normalizeCompact).toHaveBeenCalledTimes(1);
    expect(mocks.selectCompact.mock.calls.map(([, item]) => item.page)).toEqual([1, 2]);
    expect(mocks.load).not.toHaveBeenCalled();
    expect(mocks.execute).not.toHaveBeenCalled();
  });

  it("fetches a new compact envelope after the active manifest version changes", async () => {
    mocks.provider = "supabase";
    const cache = await import("@/lib/server/large-transactions-cache");
    const request = { month: "2026-07", page: 1 };
    await cache.getCachedLargeTransactions(request);
    mocks.manifestVersion = "dataset-v2";
    await vi.advanceTimersByTimeAsync(30_001);
    const refreshed = await cache.getCachedLargeTransactions(request);
    expect(refreshed.datasetVersion).toBe("dataset-v2");
    expect(mocks.fetchPulse.mock.calls.map(([version]) => version)).toEqual([
      "dataset-v1",
      "dataset-v2",
    ]);
  });

  it("reuses the validated persistent envelope after the bounded process cache is cleared", async () => {
    mocks.provider = "supabase";
    const cache = await import("@/lib/server/large-transactions-cache");
    const bounded = await import("@/lib/server/bounded-data-cache");
    const request = { month: "2026-07", page: 1 };
    await cache.getCachedLargeTransactions(request);
    bounded.resetDashboardProcessDataCache();
    await cache.getCachedLargeTransactions(request);
    expect(mocks.getManifest).toHaveBeenCalledTimes(2);
    expect(mocks.fetchPulse).toHaveBeenCalledTimes(1);
    expect(mocks.normalizeCompact).toHaveBeenCalledTimes(1);
    expect(mocks.selectCompact).toHaveBeenCalledTimes(2);
  });

  it("does not persist a missing or malformed compact envelope as an empty result", async () => {
    mocks.provider = "supabase";
    mocks.normalizeCompact.mockImplementationOnce(() => {
      throw new Error("missing compact detail");
    });
    const cache = await import("@/lib/server/large-transactions-cache");
    const request = { month: "2026-07", page: 1 };
    await expect(cache.getCachedLargeTransactions(request)).rejects.toThrow("missing compact detail");
    await expect(cache.getCachedLargeTransactions(request)).resolves.toMatchObject({
      datasetVersion: "dataset-v1",
    });
    expect(mocks.fetchPulse).toHaveBeenCalledTimes(2);
    expect(mocks.selectCompact).toHaveBeenCalledTimes(1);
  });

  it("never caches a failed load and retries the next request", async () => {
    mocks.load.mockRejectedValueOnce(new Error("timeout"));
    const cache = await import("@/lib/server/large-transactions-cache");
    const request = { month: "2026-07", page: 1 };
    await expect(cache.getCachedLargeTransactions(request)).rejects.toThrow("timeout");
    await expect(cache.getCachedLargeTransactions(request)).resolves.toMatchObject({
      datasetVersion: "dataset-v1",
    });
    expect(mocks.load).toHaveBeenCalledTimes(2);
  });
});
