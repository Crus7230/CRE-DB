import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  close: vi.fn(), createClient: vi.fn(), execute: vi.fn(), fetch: vi.fn(),
  readFileSync: vi.fn(), statSync: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("@libsql/client", () => ({ createClient: mocks.createClient }));
vi.mock("node:fs", () => ({ default: { readFileSync: mocks.readFileSync, statSync: mocks.statSync } }));

type CacheGlobals = typeof globalThis & {
  __creDashboardSqliteClients?: Record<string, unknown>;
  __creDashboardSqliteFingerprints?: Record<string, string>;
  __creDashboardSqliteInitializations?: Record<string, Promise<void>>;
};

const ENV_NAMES = [
  "DASHBOARD_DATA_PROVIDER", "DASHBOARD_HOSTED_DEPLOYMENT", "DASHBOARD_DATASET_VERSION",
  "DASHBOARD_QUERY_TIMEOUT_MS", "DASHBOARD_ENV_FILE", "SUPABASE_URL",
  "SUPABASE_PROJECT_REF", "SUPABASE_SECRET_KEY", "SUPABASE_PUBLISHABLE_KEY",
  "DASHBOARD_SUPABASE_RPC_SCHEMA", "SUPABASE_DB_SCHEMA", "TURSO_DATABASE_URL",
  "NEWS_DATABASE_URL", "TIMESERIES_DATABASE_URL", "TURSO_ENV_FILE", "VERCEL",
] as const;

function setSqliteEnvironment() {
  vi.stubEnv("DASHBOARD_DATA_PROVIDER", "sqlite");
  vi.stubEnv("DASHBOARD_DATASET_VERSION", "sqlite-test-v1");
  vi.stubEnv("TURSO_DATABASE_URL", "file:auth.db");
  vi.stubEnv("NEWS_DATABASE_URL", "file:news.db");
  vi.stubEnv("TIMESERIES_DATABASE_URL", "file:timeseries.db");
}

function setSupabaseEnvironment() {
  vi.stubEnv("DASHBOARD_DATA_PROVIDER", "supabase");
  vi.stubEnv("SUPABASE_URL", "https://rjalzmmiqhrdmhojbxsk.supabase.co");
  vi.stubEnv("SUPABASE_PROJECT_REF", "rjalzmmiqhrdmhojbxsk");
  vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test_only");
}

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  for (const name of ENV_NAMES) delete process.env[name];
  delete (globalThis as CacheGlobals).__creDashboardSqliteClients;
  delete (globalThis as CacheGlobals).__creDashboardSqliteFingerprints;
  delete (globalThis as CacheGlobals).__creDashboardSqliteInitializations;
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.createClient.mockReturnValue({ execute: mocks.execute, close: mocks.close });
  mocks.execute.mockImplementation(async (statement: string | { sql: string }) => ({
    rows: statement === "PRAGMA query_only" ? [{ query_only: 1 }] : [],
  }));
  mocks.statSync.mockReturnValue({ size: 100, mtimeMs: 1_000 });
  vi.stubGlobal("fetch", mocks.fetch);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  for (const name of ENV_NAMES) delete process.env[name];
  delete (globalThis as CacheGlobals).__creDashboardSqliteClients;
  delete (globalThis as CacheGlobals).__creDashboardSqliteFingerprints;
  delete (globalThis as CacheGlobals).__creDashboardSqliteInitializations;
});

describe("dashboard database provider", () => {
  it("uses the last duplicate authority assignment without reading unrelated values", async () => {
    const { parseDatabaseAuthority } = await import("@/lib/server/db");
    const parsed = parseDatabaseAuthority([
      "SUPABASE_URL=https://aaaaaaaaaaaaaaaaaaaa.supabase.co",
      "UNRELATED_SECRET=must-not-be-read",
      "export SUPABASE_URL='https://rjalzmmiqhrdmhojbxsk.supabase.co'",
      "DASHBOARD_DATA_PROVIDER=supabase",
    ].join("\n"));
    expect(parsed.get("SUPABASE_URL")).toBe("https://rjalzmmiqhrdmhojbxsk.supabase.co");
    expect(parsed.has("UNRELATED_SECRET")).toBe(false);
  });

  it("requires an explicit provider and forbids sqlite only on hosted deployments", async () => {
    vi.stubEnv("TURSO_DATABASE_URL", "file:auth.db");
    let database = await import("@/lib/server/db");
    expect(() => database.getDashboardDataProvider()).toThrow(/explicitly configured/u);

    vi.resetModules();
    setSqliteEnvironment();
    vi.stubEnv("VERCEL", "1");
    database = await import("@/lib/server/db");
    expect(() => database.getDashboardDataProvider()).toThrow(/require.*supabase/u);
    expect(mocks.createClient).not.toHaveBeenCalled();
  });

  it("keeps explicit local split sqlite available under next start production mode", async () => {
    setSqliteEnvironment();
    vi.stubEnv("NODE_ENV", "production");
    const database = await import("@/lib/server/db");
    await expect(database.executeNewsSql("SELECT 1", [])).resolves.toEqual({ rows: [] });
    expect(database.getDashboardDataProvider()).toBe("sqlite");
    expect(mocks.createClient).toHaveBeenCalledWith({ url: "file:news.db" });
  });

  it("routes split reads to query-only files and rejects an old remote Turso authority", async () => {
    setSqliteEnvironment();
    let database = await import("@/lib/server/db");
    await database.executeMarketSql("SELECT 'auth'", []);
    await database.executeNewsSql("SELECT 'news'", []);
    await database.executeTimeseriesSql("SELECT 'timeseries'", []);
    expect(mocks.createClient).toHaveBeenNthCalledWith(1, { url: "file:auth.db" });
    expect(mocks.createClient).toHaveBeenNthCalledWith(2, { url: "file:news.db" });
    expect(mocks.createClient).toHaveBeenNthCalledWith(3, { url: "file:timeseries.db" });
    expect(mocks.execute.mock.calls.filter(([statement]) => statement === "PRAGMA query_only")).toHaveLength(2);
    expect(database.getProjectCacheNamespace()).toMatch(/^sqlite-[0-9a-f]{16}$/u);
    expect(database.canUseNewsArchiveFallback()).toBe(false);

    vi.resetModules();
    setSqliteEnvironment();
    vi.stubEnv("NEWS_DATABASE_URL", "libsql://old-project.turso.io");
    database = await import("@/lib/server/db");
    await expect(database.executeNewsSql("SELECT 1", [])).rejects.toThrow(/local file/u);
  });

  it("replaces HMR clients and namespaces when a local database URL changes", async () => {
    setSqliteEnvironment();
    let database = await import("@/lib/server/db");
    const firstNamespace = database.getProjectCacheNamespace();
    await database.executeMarketSql("SELECT 1", []);

    vi.resetModules();
    setSqliteEnvironment();
    vi.stubEnv("TURSO_DATABASE_URL", "file:auth-next.db");
    database = await import("@/lib/server/db");
    const secondNamespace = database.getProjectCacheNamespace();
    await database.executeMarketSql("SELECT 1", []);
    expect(secondNamespace).not.toBe(firstNamespace);
    expect(mocks.close).toHaveBeenCalledOnce();
    expect(mocks.createClient).toHaveBeenLastCalledWith({ url: "file:auth-next.db" });
  });

  it("uses only a server apikey and pins data RPCs to the manifest version", async () => {
    setSupabaseEnvironment();
    mocks.fetch.mockImplementation(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const database = await import("@/lib/server/db");
    await database.fetchDashboardDailyArticles("LATEST", "dataset-v1");
    await database.fetchDashboardPermitTimeseries({
      groupBy: "ASSET_TYPE", from: "2025-01", to: "2026-08", eventType: null,
      assetType: "OFFICE", district: "강남구", constructionAction: null,
    }, "dataset-v1");
    await database.fetchDashboardContextualEvidence({
      q: "매각", from: null, to: null, topic: "SALE", topK: 8,
    }, "dataset-v1");

    const [dailyUrl, dailyInit] = mocks.fetch.mock.calls[0] as [string, RequestInit];
    expect(dailyUrl).toMatch(/\/rest\/v1\/rpc\/dashboard_daily_articles$/u);
    const headers = new Headers(dailyInit.headers);
    expect(headers.get("apikey")).toBe("sb_secret_test_only");
    expect(headers.has("authorization")).toBe(false);
    expect(headers.get("content-profile")).toBe("public");
    expect(dailyInit.cache).toBe("no-store");
    expect(JSON.parse(String(dailyInit.body))).toEqual({
      p_date: null, p_limit: 200, p_dataset_version: "dataset-v1",
    });
    expect(JSON.parse(String((mocks.fetch.mock.calls[1][1] as RequestInit).body))).toMatchObject({
      p_from: "2025-01-01", p_to: "2026-08-01", p_asset_type: "OFFICE",
      p_district: "강남구", p_dataset_version: "dataset-v1",
    });
    expect(JSON.parse(String((mocks.fetch.mock.calls[2][1] as RequestInit).body))).toEqual({
      q: "매각", filters: { from: null, to: null, topic: "SALE" }, top_k: 8,
      p_dataset_version: "dataset-v1",
    });
    expect(database.getProjectCacheNamespace()).toMatch(/^supabase-[0-9a-f]{16}$/u);
  });

  it("fails before fetch when URL, ref, or a legacy JWT authority disagree", async () => {
    setSupabaseEnvironment();
    vi.stubEnv("SUPABASE_PROJECT_REF", "aaaaaaaaaaaaaaaaaaaa");
    let database = await import("@/lib/server/db");
    expect(() => database.getProjectCacheNamespace()).toThrow(/does not match/u);

    vi.resetModules();
    setSupabaseEnvironment();
    const payload = Buffer.from(JSON.stringify({ ref: "aaaaaaaaaaaaaaaaaaaa" })).toString("base64url");
    vi.stubEnv("SUPABASE_SECRET_KEY", `eyJ.${payload}.signature`);
    database = await import("@/lib/server/db");
    expect(() => database.getProjectCacheNamespace()).toThrow(/API key does not match/u);
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it("times out a stalled response body and sqlite execution that ignores AbortSignal", async () => {
    vi.useFakeTimers();
    setSupabaseEnvironment();
    vi.stubEnv("DASHBOARD_QUERY_TIMEOUT_MS", "1000");
    mocks.fetch.mockResolvedValue({ ok: true, json: () => new Promise(() => undefined) });
    let database = await import("@/lib/server/db");
    let pending = database.fetchDashboardMacroTimeseries("dataset-v1");
    let assertion = expect(pending).rejects.toMatchObject({ code: "DATABASE_QUERY_TIMEOUT", timeoutMs: 1000 });
    await vi.advanceTimersByTimeAsync(1000);
    await assertion;

    vi.resetModules();
    setSqliteEnvironment();
    vi.stubEnv("DASHBOARD_QUERY_TIMEOUT_MS", "1000");
    mocks.execute.mockReturnValue(new Promise(() => undefined));
    database = await import("@/lib/server/db");
    pending = database.executeMarketSql("SELECT 1", []);
    assertion = expect(pending).rejects.toMatchObject({ code: "DATABASE_QUERY_TIMEOUT", timeoutMs: 1000 });
    await vi.advanceTimersByTimeAsync(1000);
    await assertion;
  });

  it("keeps authorization and data-call diagnostics separate", async () => {
    setSupabaseEnvironment();
    mocks.fetch
      .mockResolvedValueOnce(new Response(JSON.stringify({
        authorized: true, subject_id: "subject-1", authz_version: 1, dataset_version: "dataset-v1",
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ dataset_version: "dataset-v1" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ articles: [] }), { status: 200 }));
    const database = await import("@/lib/server/db");
    await database.authorizeDashboardSubject("subject-1");
    await database.getServingManifest();
    await database.fetchDashboardDailyArticles("LATEST", "dataset-v1");
    expect(database.getDatabaseDiagnostics()).toMatchObject({
      authRpcCalls: 1, manifestRpcCalls: 1, dataRpcCalls: 1,
      sqliteAuthQueries: 0, sqliteDataQueries: 0,
    });
  });

  it("fails closed when the local limiter returns duplicate keys or non-boolean blocked", async () => {
    setSqliteEnvironment();
    mocks.execute
      .mockResolvedValueOnce({ rows: [] })
      .mockResolvedValueOnce({ rows: [
        { rate_limit_key: "ip:1", blocked: 0 }, { rate_limit_key: "ip:1", blocked: 0 },
      ] });
    const database = await import("@/lib/server/db");
    await expect(database.consumeDashboardLoginAttempts(["ip:1", "email:a"]))
      .rejects.toThrow(/duplicate key/u);

    mocks.execute
      .mockResolvedValueOnce({ rows: [] })
      .mockResolvedValueOnce({ rows: [{ rate_limit_key: "ip:1", blocked: null }] });
    await expect(database.consumeDashboardLoginAttempts(["ip:1"]))
      .rejects.toThrow(/invalid/u);
  });
});
