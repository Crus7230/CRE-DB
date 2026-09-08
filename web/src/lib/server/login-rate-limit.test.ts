import { createClient } from "@libsql/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthSqlExecutor } from "@/lib/server/email-allowlist";
import {
  clearLoginAttempts,
  consumeLoginAttempts,
  loginRateLimitKeys,
} from "@/lib/server/login-rate-limit";

const SECRET = "0123456789abcdef0123456789abcdef";
const clients: Array<ReturnType<typeof createClient>> = [];

afterEach(() => {
  for (const client of clients.splice(0)) client.close();
});

function resultRows(values: readonly unknown[], blockedKey?: string) {
  return [...new Set(values as readonly string[])].map((rateLimitKey) => ({
    rate_limit_key: rateLimitKey,
    blocked: rateLimitKey === blockedKey ? 1 : 0,
  }));
}

function mockExecutor(blockedKey?: string) {
  return vi.fn(async (text: string, values: readonly unknown[]) => ({
    rows: text.includes("RETURNING rate_limit_key") ? resultRows(values, blockedKey) : [],
  }));
}

describe("loginRateLimitKeys", () => {
  it("prefers the Vercel-controlled forwarding header when forwarded headers conflict", async () => {
    const conflicting = new Request("https://example.com/api/auth/login", {
      headers: {
        "x-vercel-forwarded-for": "203.0.113.7, 10.0.0.1",
        "x-real-ip": "198.51.100.9",
        "x-forwarded-for": "192.0.2.5",
      },
    });
    const vercelOnly = new Request("https://example.com/api/auth/login", {
      headers: { "x-vercel-forwarded-for": "203.0.113.7" },
    });
    const spoofOnly = new Request("https://example.com/api/auth/login", {
      headers: { "x-real-ip": "198.51.100.9" },
    });
    const [conflict, vercel, spoof] = await Promise.all([
      loginRateLimitKeys(conflicting, SECRET, "person@example.com"),
      loginRateLimitKeys(vercelOnly, SECRET, "person@example.com"),
      loginRateLimitKeys(spoofOnly, SECRET, "person@example.com"),
    ]);

    expect(conflict[0]).toBe(vercel[0]);
    expect(conflict[0]).not.toBe(spoof[0]);
    expect(conflict[1]).toBe(vercel[1]);
  });

  it("atomically consumes both pseudonymous keys with one SQLite upsert", async () => {
    const execute = mockExecutor();
    const keys = ["key-a", "key-b"];

    expect(await consumeLoginAttempts(execute, keys)).toBe(false);
    await clearLoginAttempts(execute, keys);

    expect(execute).toHaveBeenCalledTimes(3);
    expect(execute.mock.calls[0][0]).toContain("DELETE FROM dashboard_login_rate_limits");
    expect(execute.mock.calls[0][1]).toEqual([]);
    expect(execute.mock.calls[1][1]).toEqual(keys);
    expect(execute.mock.calls[2][1]).toEqual(keys);
    expect(execute.mock.calls[1][0]).toContain("WITH requested_keys(rate_limit_key)");
    expect(execute.mock.calls[1][0]).toContain("ON CONFLICT(rate_limit_key) DO UPDATE");
    expect(execute.mock.calls[1][0]).not.toMatch(/::|clock_timestamp|interval|bool_or|app_security\./u);
  });

  it("pads a single limiter key without consuming it twice", async () => {
    const execute = mockExecutor();

    expect(await consumeLoginAttempts(execute, ["key-a"])).toBe(false);
    expect(execute.mock.calls[1][1]).toEqual(["key-a", "key-a"]);
  });

  it("returns blocked when either limiter row is blocked", async () => {
    const execute = mockExecutor("key-b");
    expect(await consumeLoginAttempts(execute, ["key-a", "key-b"])).toBe(true);
  });

  it("fails closed on incomplete, malformed, or missing limiter keys", async () => {
    const incomplete = vi.fn()
      .mockResolvedValueOnce({ rows: [] })
      .mockResolvedValueOnce({ rows: [{ rate_limit_key: "key-a", blocked: 0 }] });
    await expect(consumeLoginAttempts(incomplete, ["key-a", "key-b"]))
      .rejects.toThrow("incomplete");

    const malformed = vi.fn()
      .mockResolvedValueOnce({ rows: [] })
      .mockResolvedValueOnce({ rows: [
        { rate_limit_key: "key-a", blocked: 0 },
        { rate_limit_key: "key-b", blocked: null },
      ] });
    await expect(consumeLoginAttempts(malformed, ["key-a", "key-b"]))
      .rejects.toThrow("invalid");
    await expect(consumeLoginAttempts(vi.fn(), [])).rejects.toThrow("requires");
  });

  it("enforces and clears both keys against real libSQL", async () => {
    const client = createClient({ url: "file::memory:" });
    clients.push(client);
    await client.execute(`
      CREATE TABLE dashboard_login_rate_limits(
        rate_limit_key TEXT PRIMARY KEY,
        window_started_at TEXT NOT NULL,
        attempt_count INTEGER NOT NULL,
        blocked_until TEXT,
        updated_at TEXT NOT NULL
      )
    `);
    await client.execute(`
      INSERT INTO dashboard_login_rate_limits(
        rate_limit_key, window_started_at, attempt_count, blocked_until, updated_at
      ) VALUES ('stale-key', datetime('now', '-8 days'), 3, NULL, datetime('now', '-8 days'))
    `);
    const execute: AuthSqlExecutor = async (sql, args) => {
      const result = await client.execute({ sql, args: [...args] });
      return { rows: result.rows.map((row) => Object.fromEntries(Object.entries(row))) };
    };

    for (let attempt = 1; attempt < 10; attempt += 1) {
      expect(await consumeLoginAttempts(execute, ["key-a", "key-b"])).toBe(false);
    }
    expect(await consumeLoginAttempts(execute, ["key-a", "key-b"])).toBe(true);

    const consumed = await client.execute(`
      SELECT rate_limit_key, attempt_count
      FROM dashboard_login_rate_limits
      ORDER BY rate_limit_key
    `);
    expect(consumed.rows.map((row) => ({
      rate_limit_key: row.rate_limit_key,
      attempt_count: row.attempt_count,
    }))).toEqual([
      { rate_limit_key: "key-a", attempt_count: 10 },
      { rate_limit_key: "key-b", attempt_count: 10 },
    ]);

    await clearLoginAttempts(execute, ["key-a", "key-b"]);
    const cleared = await client.execute("SELECT count(*) AS count FROM dashboard_login_rate_limits");
    expect(cleared.rows[0].count).toBe(0);
  });
});
