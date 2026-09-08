import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { closeMock, createClientMock, executeMock, readFileSyncMock } = vi.hoisted(() => ({
  closeMock: vi.fn(),
  createClientMock: vi.fn(),
  executeMock: vi.fn(),
  readFileSyncMock: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("@libsql/client", () => ({ createClient: createClientMock }));
vi.mock("node:fs", () => ({
  default: { readFileSync: readFileSyncMock },
}));

type GlobalWithClient = typeof globalThis & {
  __marketLibsqlClient?: unknown;
  __marketLibsqlClientFingerprint?: string;
};

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv("TURSO_DATABASE_URL", "");
  vi.stubEnv("TURSO_AUTH_TOKEN", "");
  vi.stubEnv("TURSO_ENV_FILE", "");
  delete process.env.TURSO_DATABASE_URL;
  delete process.env.TURSO_AUTH_TOKEN;
  delete process.env.TURSO_ENV_FILE;
  delete (globalThis as GlobalWithClient).__marketLibsqlClient;
  delete (globalThis as GlobalWithClient).__marketLibsqlClientFingerprint;
  executeMock.mockReset();
  readFileSyncMock.mockReset();
  createClientMock.mockReset();
  closeMock.mockReset();
  createClientMock.mockReturnValue({ execute: executeMock, close: closeMock });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  delete (globalThis as GlobalWithClient).__marketLibsqlClient;
  delete (globalThis as GlobalWithClient).__marketLibsqlClientFingerprint;
});

describe("libSQL database executor", () => {
  it("creates one lazy Turso client from process.env and preserves bind values", async () => {
    vi.stubEnv("TURSO_DATABASE_URL", "libsql://dashboard.example.turso.io");
    vi.stubEnv("TURSO_AUTH_TOKEN", "test-token");
    executeMock.mockResolvedValue({
      rows: [{ payload: "{\"ok\":true}", untouched: "value" }],
    });
    const { executeMarketSql } = await import("@/lib/server/db");

    await expect(executeMarketSql("SELECT ? AS payload", ["bound-value"]))
      .resolves.toEqual({ rows: [{ payload: { ok: true }, untouched: "value" }] });
    expect(createClientMock).toHaveBeenCalledOnce();
    expect(createClientMock).toHaveBeenCalledWith({
      url: "libsql://dashboard.example.turso.io",
      authToken: "test-token",
    });
    expect(readFileSyncMock).not.toHaveBeenCalled();
    expect(executeMock).toHaveBeenCalledWith({
      sql: "SELECT ? AS payload",
      args: ["bound-value"],
    });
  });

  it("uses the personal authority path only when process.env has no Turso authority", async () => {
    readFileSyncMock.mockReturnValue([
      "# test authority",
      "export TURSO_DATABASE_URL='libsql://authority.example.turso.io'",
      "TURSO_AUTH_TOKEN=authority-token",
    ].join("\n"));
    executeMock.mockResolvedValue({ rows: [] });
    const { executeAuthSql } = await import("@/lib/server/db");

    await executeAuthSql("SELECT 1", []);

    expect(readFileSyncMock).toHaveBeenCalledWith(
      String.raw`C:\10137_WorkSpace\env\.env.personal.txt`,
      "utf8",
    );
    expect(createClientMock).toHaveBeenCalledWith({
      url: "libsql://authority.example.turso.io",
      authToken: "authority-token",
    });
  });

  it("does not mix a process URL with a token from the fallback authority", async () => {
    vi.stubEnv("TURSO_DATABASE_URL", "libsql://process.example.turso.io");
    executeMock.mockResolvedValue({ rows: [] });
    const { executeAuthSql } = await import("@/lib/server/db");

    await expect(executeAuthSql("SELECT 1", []))
      .rejects.toThrow("TURSO_AUTH_TOKEN is not configured");
    expect(readFileSyncMock).not.toHaveBeenCalled();
    expect(createClientMock).not.toHaveBeenCalled();
  });

  it("allows an unauthenticated local file URL for read-only smoke checks", async () => {
    vi.stubEnv("TURSO_DATABASE_URL", "file:local-smoke.db");
    executeMock.mockResolvedValue({ rows: [{ payload: "not-json" }] });
    const { executeMarketSql } = await import("@/lib/server/db");

    await expect(executeMarketSql("SELECT payload FROM smoke", []))
      .resolves.toEqual({ rows: [{ payload: "not-json" }] });
    expect(createClientMock).toHaveBeenCalledWith({ url: "file:local-smoke.db" });
  });

  it("derives a lazy token-free cache authority from the normalized database URL", async () => {
    vi.stubEnv("TURSO_DATABASE_URL", "LIBSQL://Dashboard.Example.Turso.IO/?credential=ignored#fragment");
    vi.stubEnv("TURSO_AUTH_TOKEN", "first-token");
    const firstModule = await import("@/lib/server/db");

    expect(readFileSyncMock).not.toHaveBeenCalled();
    expect(createClientMock).not.toHaveBeenCalled();
    const firstNamespace = firstModule.getMarketCacheAuthorityNamespace();
    expect(firstNamespace).toMatch(/^url-[0-9a-f]{16}$/u);
    expect(firstNamespace).not.toContain("first-token");
    expect(firstModule.isLocalMarketDatabaseAuthority()).toBe(false);
    expect(createClientMock).not.toHaveBeenCalled();

    vi.resetModules();
    vi.stubEnv("TURSO_DATABASE_URL", "libsql://dashboard.example.turso.io");
    vi.stubEnv("TURSO_AUTH_TOKEN", "different-token");
    const sameAuthorityModule = await import("@/lib/server/db");
    expect(sameAuthorityModule.getMarketCacheAuthorityNamespace()).toBe(firstNamespace);

    vi.resetModules();
    vi.stubEnv("TURSO_DATABASE_URL", "file:local-smoke.db");
    delete process.env.TURSO_AUTH_TOKEN;
    const localModule = await import("@/lib/server/db");
    expect(localModule.getMarketCacheAuthorityNamespace()).not.toBe(firstNamespace);
    expect(localModule.isLocalMarketDatabaseAuthority()).toBe(true);
  });

  it("rejects a stuck query after the bounded timeout", async () => {
    vi.useFakeTimers();
    vi.stubEnv("TURSO_DATABASE_URL", "file:local-smoke.db");
    vi.stubEnv("TURSO_QUERY_TIMEOUT_MS", "1000");
    executeMock.mockReturnValue(new Promise(() => undefined));
    const { executeMarketSql } = await import("@/lib/server/db");

    const pending = executeMarketSql("SELECT 1", []);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "DatabaseQueryTimeoutError",
      code: "DATABASE_QUERY_TIMEOUT",
      timeoutMs: 1000,
    });
    await vi.advanceTimersByTimeAsync(1000);
    await assertion;
    vi.useRealTimers();
  });

  it("replaces a hot-reload client when the secret-safe configuration fingerprint changes", async () => {
    vi.stubEnv("TURSO_DATABASE_URL", "libsql://first.example.turso.io");
    vi.stubEnv("TURSO_AUTH_TOKEN", "first-token");
    executeMock.mockResolvedValue({ rows: [] });
    const firstModule = await import("@/lib/server/db");
    await firstModule.executeMarketSql("SELECT 1", []);

    vi.resetModules();
    vi.stubEnv("TURSO_DATABASE_URL", "libsql://second.example.turso.io");
    vi.stubEnv("TURSO_AUTH_TOKEN", "second-token");
    const secondModule = await import("@/lib/server/db");
    await secondModule.executeMarketSql("SELECT 1", []);

    expect(closeMock).toHaveBeenCalledOnce();
    expect(createClientMock).toHaveBeenCalledTimes(2);
    expect(createClientMock).toHaveBeenLastCalledWith({
      url: "libsql://second.example.turso.io",
      authToken: "second-token",
    });
  });
});
