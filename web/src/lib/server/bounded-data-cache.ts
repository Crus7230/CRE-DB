type CacheEntry = {
  value: unknown;
  expiresAt: number;
  negative: boolean;
};

export type ProcessCacheDiagnostics = {
  hits: number;
  misses: number;
  singleflightHits: number;
  negativeHits: number;
  loads: number;
  errors: number;
  overloads: number;
  evictions: number;
  entries: number;
  pending: number;
};

export type ProcessCacheOptions<T> = {
  ttlMs: number;
  negativeTtlMs: number;
  isNegative: (value: T) => boolean;
};

export class BoundedSingleflightCache {
  private readonly entries = new Map<string, CacheEntry>();
  private readonly pending = new Map<string, Promise<unknown>>();
  private readonly counters = {
    hits: 0,
    misses: 0,
    singleflightHits: 0,
    negativeHits: 0,
    loads: 0,
    errors: 0,
    overloads: 0,
    evictions: 0,
  };
  private generation = 0;

  constructor(
    private readonly maximumEntries = 256,
    private readonly maximumPending = 64,
    private readonly now: () => number = () => Date.now(),
  ) {
    if (!Number.isInteger(maximumEntries) || maximumEntries < 1) {
      throw new Error("Process cache maximumEntries must be a positive integer");
    }
    if (!Number.isInteger(maximumPending) || maximumPending < 1) {
      throw new Error("Process cache maximumPending must be a positive integer");
    }
  }

  async get<T>(
    key: string,
    loader: () => Promise<T>,
    options: ProcessCacheOptions<T>,
  ): Promise<T> {
    const currentTime = this.now();
    const cached = this.entries.get(key);
    if (cached && cached.expiresAt > currentTime) {
      this.entries.delete(key);
      this.entries.set(key, cached);
      this.counters.hits += 1;
      if (cached.negative) this.counters.negativeHits += 1;
      return cached.value as T;
    }
    if (cached) this.entries.delete(key);

    const existing = this.pending.get(key);
    if (existing) {
      this.counters.singleflightHits += 1;
      return existing as Promise<T>;
    }

    if (this.pending.size >= this.maximumPending) {
      this.counters.overloads += 1;
      throw new ProcessDataCacheOverloadError(this.maximumPending);
    }

    this.counters.misses += 1;
    this.counters.loads += 1;
    const loadGeneration = this.generation;
    const load: Promise<T> = loader().then((loaded) => {
      const negative = options.isNegative(loaded);
      const ttlMs = negative ? options.negativeTtlMs : options.ttlMs;
      if (ttlMs > 0 && loadGeneration === this.generation) {
        this.prune(this.now());
        while (this.entries.size >= this.maximumEntries) {
          const oldest = this.entries.keys().next().value as string | undefined;
          if (oldest === undefined) break;
          this.entries.delete(oldest);
          this.counters.evictions += 1;
        }
        this.entries.set(key, { value: loaded, expiresAt: this.now() + ttlMs, negative });
      }
      return loaded;
    }).catch((error: unknown) => {
      // A failed query never replaces a previously valid entry and never creates
      // a negative entry. The next request can retry immediately.
      this.counters.errors += 1;
      throw error;
    }).finally(() => {
      if (this.pending.get(key) === load) this.pending.delete(key);
    });
    this.pending.set(key, load);
    return load;
  }

  clear() {
    this.generation += 1;
    this.entries.clear();
    this.pending.clear();
    for (const key of Object.keys(this.counters) as Array<keyof typeof this.counters>) {
      this.counters[key] = 0;
    }
  }

  diagnostics(): ProcessCacheDiagnostics {
    this.prune(this.now());
    return {
      ...this.counters,
      entries: this.entries.size,
      pending: this.pending.size,
    };
  }

  private prune(currentTime: number) {
    for (const [key, entry] of this.entries) {
      if (entry.expiresAt <= currentTime) this.entries.delete(key);
    }
  }
}

export class ProcessDataCacheOverloadError extends Error {
  readonly code = "DATA_CACHE_OVERLOADED";

  constructor(readonly maximumPending: number) {
    super("Dashboard data cache has too many distinct pending loads");
    this.name = "ProcessDataCacheOverloadError";
  }
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  if (typeof value === "number" && !Number.isFinite(value)) return String(value);
  return value;
}

export function stableCacheKey(scope: string, namespace: string, input: unknown) {
  return `${scope}:${namespace}:${JSON.stringify(canonicalize(input))}`;
}

type CacheGlobal = typeof globalThis & { __creDashboardProcessDataCache?: BoundedSingleflightCache };
const cacheGlobal = globalThis as CacheGlobal;

export function dashboardProcessDataCache() {
  return cacheGlobal.__creDashboardProcessDataCache ??= new BoundedSingleflightCache();
}

export function resetDashboardProcessDataCache() {
  dashboardProcessDataCache().clear();
}
