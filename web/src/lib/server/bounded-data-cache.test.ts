import { describe, expect, it, vi } from "vitest";
import {
  BoundedSingleflightCache,
  ProcessDataCacheOverloadError,
} from "@/lib/server/bounded-data-cache";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const positiveOptions = {
  ttlMs: 100,
  negativeTtlMs: 10,
  isNegative: () => false,
};

describe("BoundedSingleflightCache", () => {
  it("serves positive hits until the TTL and reloads exactly at expiry", async () => {
    let now = 1_000;
    const cache = new BoundedSingleflightCache(4, 4, () => now);
    const loader = vi.fn()
      .mockResolvedValueOnce("first")
      .mockResolvedValueOnce("second");

    await expect(cache.get("key", loader, positiveOptions)).resolves.toBe("first");
    now = 1_099;
    await expect(cache.get("key", loader, positiveOptions)).resolves.toBe("first");
    now = 1_100;
    await expect(cache.get("key", loader, positiveOptions)).resolves.toBe("second");

    expect(loader).toHaveBeenCalledTimes(2);
    expect(cache.diagnostics()).toEqual({
      hits: 1,
      misses: 2,
      singleflightHits: 0,
      negativeHits: 0,
      loads: 2,
      errors: 0,
      overloads: 0,
      evictions: 0,
      entries: 1,
      pending: 0,
    });
  });

  it("uses the shorter negative TTL and counts only served negative hits", async () => {
    let now = 2_000;
    const cache = new BoundedSingleflightCache(4, 4, () => now);
    const loader = vi.fn()
      .mockResolvedValueOnce([] as string[])
      .mockResolvedValueOnce(["fresh"]);
    const options = {
      ttlMs: 100,
      negativeTtlMs: 5,
      isNegative: (value: string[]) => value.length === 0,
    };

    await expect(cache.get("key", loader, options)).resolves.toEqual([]);
    now = 2_004;
    await expect(cache.get("key", loader, options)).resolves.toEqual([]);
    now = 2_005;
    await expect(cache.get("key", loader, options)).resolves.toEqual(["fresh"]);

    expect(loader).toHaveBeenCalledTimes(2);
    expect(cache.diagnostics()).toMatchObject({
      hits: 1,
      negativeHits: 1,
      misses: 2,
      loads: 2,
      entries: 1,
      pending: 0,
    });
  });

  it("never caches a rejected load and permits an immediate retry", async () => {
    const cache = new BoundedSingleflightCache(4, 4);
    const failure = new Error("transient");
    const loader = vi.fn()
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce("recovered");

    await expect(cache.get("key", loader, positiveOptions)).rejects.toBe(failure);
    expect(cache.diagnostics()).toMatchObject({
      errors: 1,
      entries: 0,
      pending: 0,
    });

    await expect(cache.get("key", loader, positiveOptions)).resolves.toBe("recovered");
    expect(loader).toHaveBeenCalledTimes(2);
    expect(cache.diagnostics()).toMatchObject({
      misses: 2,
      loads: 2,
      errors: 1,
      entries: 1,
      pending: 0,
    });
  });

  it("evicts the least recently used entry when maximumEntries is reached", async () => {
    const cache = new BoundedSingleflightCache(2, 4);
    const loaders = {
      a: vi.fn().mockResolvedValue("A"),
      b: vi.fn().mockResolvedValue("B"),
      c: vi.fn().mockResolvedValue("C"),
    };

    await cache.get("a", loaders.a, positiveOptions);
    await cache.get("b", loaders.b, positiveOptions);
    await cache.get("a", loaders.a, positiveOptions);
    await cache.get("c", loaders.c, positiveOptions);
    await cache.get("b", loaders.b, positiveOptions);

    expect(loaders.a).toHaveBeenCalledOnce();
    expect(loaders.b).toHaveBeenCalledTimes(2);
    expect(loaders.c).toHaveBeenCalledOnce();
    expect(cache.diagnostics()).toMatchObject({
      hits: 1,
      misses: 4,
      loads: 4,
      evictions: 2,
      entries: 2,
      pending: 0,
    });
  });

  it("allows same-key singleflight at maximumPending but rejects a new key", async () => {
    const cache = new BoundedSingleflightCache(4, 1);
    const inFlight = deferred<string>();
    const loader = vi.fn(() => inFlight.promise);

    const first = cache.get("shared", loader, positiveOptions);
    const joined = cache.get("shared", loader, positiveOptions);
    await expect(cache.get("other", async () => "other", positiveOptions)).rejects.toEqual(
      expect.objectContaining<Partial<ProcessDataCacheOverloadError>>({
        name: "ProcessDataCacheOverloadError",
        code: "DATA_CACHE_OVERLOADED",
        maximumPending: 1,
      }),
    );

    expect(loader).toHaveBeenCalledOnce();
    expect(cache.diagnostics()).toMatchObject({
      singleflightHits: 1,
      overloads: 1,
      pending: 1,
    });

    inFlight.resolve("shared-value");
    await expect(Promise.all([first, joined])).resolves.toEqual([
      "shared-value",
      "shared-value",
    ]);
    expect(cache.diagnostics().pending).toBe(0);
  });

  it("starts distinct loaders concurrently up to maximumPending", async () => {
    const cache = new BoundedSingleflightCache(4, 2);
    const firstDeferred = deferred<string>();
    const secondDeferred = deferred<string>();
    const started: string[] = [];

    const first = cache.get("first", () => {
      started.push("first");
      return firstDeferred.promise;
    }, positiveOptions);
    const second = cache.get("second", () => {
      started.push("second");
      return secondDeferred.promise;
    }, positiveOptions);

    expect(started).toEqual(["first", "second"]);
    expect(cache.diagnostics()).toMatchObject({
      loads: 2,
      pending: 2,
      overloads: 0,
    });

    secondDeferred.resolve("second-value");
    firstDeferred.resolve("first-value");
    await expect(Promise.all([first, second])).resolves.toEqual([
      "first-value",
      "second-value",
    ]);
  });

  it("prevents a pre-clear generation from deleting or repopulating the new generation", async () => {
    const cache = new BoundedSingleflightCache(4, 2);
    const oldDeferred = deferred<string>();
    const newDeferred = deferred<string>();
    const oldLoader = vi.fn(() => oldDeferred.promise);
    const newLoader = vi.fn(() => newDeferred.promise);

    const oldRequest = cache.get("same-key", oldLoader, positiveOptions);
    expect(cache.diagnostics().pending).toBe(1);

    cache.clear();
    expect(cache.diagnostics()).toEqual({
      hits: 0,
      misses: 0,
      singleflightHits: 0,
      negativeHits: 0,
      loads: 0,
      errors: 0,
      overloads: 0,
      evictions: 0,
      entries: 0,
      pending: 0,
    });

    const newRequest = cache.get("same-key", newLoader, positiveOptions);
    oldDeferred.resolve("stale-value");
    await expect(oldRequest).resolves.toBe("stale-value");

    expect(cache.diagnostics()).toMatchObject({
      loads: 1,
      entries: 0,
      pending: 1,
    });
    const joinedNewRequest = cache.get("same-key", newLoader, positiveOptions);
    expect(newLoader).toHaveBeenCalledOnce();

    newDeferred.resolve("fresh-value");
    await expect(Promise.all([newRequest, joinedNewRequest])).resolves.toEqual([
      "fresh-value",
      "fresh-value",
    ]);
    await expect(cache.get("same-key", newLoader, positiveOptions)).resolves.toBe(
      "fresh-value",
    );

    expect(oldLoader).toHaveBeenCalledOnce();
    expect(newLoader).toHaveBeenCalledOnce();
    expect(cache.diagnostics()).toMatchObject({
      hits: 1,
      singleflightHits: 1,
      loads: 1,
      entries: 1,
      pending: 0,
    });
  });
});
