import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTH_REJECTED_MESSAGE, verifySessionToken } from "@/lib/server/auth-session";

const { readMock, writeMock } = vi.hoisted(() => ({
  readMock: vi.fn(),
  writeMock: vi.fn(),
}));

vi.mock("@/lib/server/db", () => ({
  executeAuthSql: readMock,
  executeAuthWriteSql: writeMock,
}));

import { AUTH_INFRASTRUCTURE_MESSAGE, POST } from "@/app/api/auth/login/route";

const SUBJECT_ID = "49caafcd-f6c5-4d79-92bd-6f4cd968cf25";
const SESSION_SECRET = "0123456789abcdef0123456789abcdef";

function limiterRows(values: readonly string[], blocked = false) {
  return [...new Set(values)].map((rateLimitKey) => ({
    rate_limit_key: rateLimitKey,
    blocked: blocked ? 1 : 0,
  }));
}

beforeEach(() => {
  process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
  readMock.mockResolvedValue({ rows: [{ subject_id: SUBJECT_ID }] });
  writeMock.mockImplementation(async (text: string, values: readonly string[]) => ({
    rows: text.includes("RETURNING rate_limit_key") ? limiterRows(values) : [],
  }));
});

afterEach(() => {
  delete process.env.DASHBOARD_SESSION_SECRET;
  delete process.env.VERCEL;
  readMock.mockReset();
  writeMock.mockReset();
  vi.restoreAllMocks();
});

const request = (body: unknown, url = "http://localhost/api/auth/login") => new Request(url, {
  method: "POST",
  headers: { "x-forwarded-for": "203.0.113.10" },
  body: JSON.stringify(body),
});

describe("POST /api/auth/login", () => {
  it("rejects unapproved or invalid email with one generic rejection", async () => {
    for (const email of ["missing@example.com", "bad"]) {
      if (email === "missing@example.com") readMock.mockResolvedValueOnce({ rows: [] });
      const response = await POST(request({ email }));
      expect(response.status).toBe(401);
      expect(await response.json()).toEqual({ error: AUTH_REJECTED_MESSAGE });
      expect(response.headers.get("set-cookie")).toBeNull();
    }
  });

  it("normalizes an approved email, clears throttling state, and sets a signed cookie", async () => {
    const response = await POST(request({ email: "  Person@Example.COM " }));
    const cookie = response.headers.get("set-cookie") ?? "";
    const token = cookie.match(/^cre_db_session=([^;]+)/u)?.[1] ?? "";

    expect(response.status).toBe(200);
    expect(cookie.toLowerCase()).toContain("httponly");
    expect(cookie.toLowerCase()).toContain("samesite=lax");
    expect(cookie).not.toContain("person@example.com");
    expect((await verifySessionToken(token, SESSION_SECRET))?.subjectId).toBe(SUBJECT_ID);
    expect(readMock.mock.calls[0][1]).toEqual(["person@example.com"]);
    expect(writeMock).toHaveBeenCalledTimes(3);
    const consumeKeys = writeMock.mock.calls[1][1];
    const clearKeys = writeMock.mock.calls[2][1];
    expect(consumeKeys).toHaveLength(2);
    expect(clearKeys).toEqual(consumeKeys);
    expect(JSON.stringify(consumeKeys)).not.toContain("person@example.com");
    expect(JSON.stringify(consumeKeys)).not.toContain("203.0.113.10");
  });

  it("returns a shared 429 when either database-backed limiter key blocks the client", async () => {
    writeMock.mockImplementation(async (text: string, values: readonly string[]) => ({
      rows: text.includes("RETURNING rate_limit_key") ? limiterRows(values, true) : [],
    }));
    const response = await POST(request({ email: "person@example.com" }));

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("900");
    expect(readMock).not.toHaveBeenCalled();
  });

  it("fails closed when a limiter update returns an incomplete result", async () => {
    writeMock.mockImplementation(async (text: string, values: readonly string[]) => ({
      rows: text.includes("RETURNING rate_limit_key") ? limiterRows(values).slice(0, 1) : [],
    }));
    const response = await POST(request({ email: "person@example.com" }));

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: AUTH_INFRASTRUCTURE_MESSAGE,
      code: "AUTH_INFRASTRUCTURE_UNAVAILABLE",
    });
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(readMock).not.toHaveBeenCalled();
  });

  it("distinguishes an allowlist infrastructure outage from an unapproved email", async () => {
    readMock.mockRejectedValueOnce(Object.assign(new Error("secret dsn"), { code: "BLOCKED" }));
    const response = await POST(request({ email: "person@example.com" }));

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: AUTH_INFRASTRUCTURE_MESSAGE,
      code: "AUTH_INFRASTRUCTURE_UNAVAILABLE",
    });
    expect(AUTH_INFRASTRUCTURE_MESSAGE).not.toBe(AUTH_REJECTED_MESSAGE);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("fails closed when the session secret is missing", async () => {
    delete process.env.DASHBOARD_SESSION_SECRET;
    const response = await POST(request({ email: "person@example.com" }));
    expect(response.status).toBe(503);
    expect(writeMock).not.toHaveBeenCalled();
  });

  it("rejects bodies over 4 KiB before rate-limit or allowlist queries", async () => {
    const response = await POST(request({ email: `${"a".repeat(4096)}@example.com` }));
    expect(response.status).toBe(413);
    expect(writeMock).not.toHaveBeenCalled();
    expect(readMock).not.toHaveBeenCalled();
  });

  it("sets Secure on HTTPS", async () => {
    const response = await POST(request(
      { email: "person@example.com" },
      "https://cre-db.example/api/auth/login",
    ));
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")?.toLowerCase()).toContain("; secure");
  });
});
