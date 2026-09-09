import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTH_REJECTED_MESSAGE, verifySessionToken } from "@/lib/server/auth-session";

const mocks = vi.hoisted(() => ({
  findSubject: vi.fn(),
  consumeLoginAttempts: vi.fn(),
  clearLoginAttempts: vi.fn(),
}));

vi.mock("@/lib/server/db", () => ({
  findDashboardSubjectByEmail: mocks.findSubject,
  consumeDashboardLoginAttempts: mocks.consumeLoginAttempts,
  clearDashboardLoginAttempts: mocks.clearLoginAttempts,
}));

import { AUTH_INFRASTRUCTURE_MESSAGE, POST } from "@/app/api/auth/login/route";

const SUBJECT_ID = "49caafcd-f6c5-4d79-92bd-6f4cd968cf25";
const SESSION_SECRET = "0123456789abcdef0123456789abcdef";

beforeEach(() => {
  process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
  mocks.findSubject.mockReset().mockResolvedValue(SUBJECT_ID);
  mocks.consumeLoginAttempts.mockReset().mockResolvedValue(false);
  mocks.clearLoginAttempts.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  delete process.env.DASHBOARD_SESSION_SECRET;
  delete process.env.VERCEL;
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
      if (email === "missing@example.com") mocks.findSubject.mockResolvedValueOnce(null);
      const response = await POST(request({ email }));
      expect(response.status).toBe(401);
      expect(await response.json()).toEqual({ error: AUTH_REJECTED_MESSAGE });
      expect(response.headers.get("set-cookie")).toBeNull();
    }

    expect(mocks.findSubject).toHaveBeenCalledOnce();
    expect(mocks.findSubject).toHaveBeenCalledWith("missing@example.com");
    expect(mocks.clearLoginAttempts).not.toHaveBeenCalled();
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
    expect(mocks.findSubject).toHaveBeenCalledWith("person@example.com");
    expect(mocks.consumeLoginAttempts).toHaveBeenCalledOnce();
    expect(mocks.clearLoginAttempts).toHaveBeenCalledOnce();

    const consumeKeys = mocks.consumeLoginAttempts.mock.calls[0][0] as string[];
    const clearKeys = mocks.clearLoginAttempts.mock.calls[0][0] as string[];
    expect(consumeKeys).toHaveLength(2);
    expect(clearKeys).toEqual(consumeKeys);
    expect(JSON.stringify(consumeKeys)).not.toContain("person@example.com");
    expect(JSON.stringify(consumeKeys)).not.toContain("203.0.113.10");
  });

  it("returns a shared 429 when the database action reports either limiter key blocked", async () => {
    mocks.consumeLoginAttempts.mockResolvedValueOnce(true);
    const response = await POST(request({ email: "person@example.com" }));

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("900");
    expect(mocks.findSubject).not.toHaveBeenCalled();
    expect(mocks.clearLoginAttempts).not.toHaveBeenCalled();
  });

  it("fails closed when the limiter action rejects an incomplete update", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.consumeLoginAttempts.mockRejectedValueOnce(
      new Error("Login rate-limit update was incomplete"),
    );
    const response = await POST(request({ email: "person@example.com" }));

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: AUTH_INFRASTRUCTURE_MESSAGE,
      code: "AUTH_INFRASTRUCTURE_UNAVAILABLE",
    });
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(mocks.findSubject).not.toHaveBeenCalled();
    expect(mocks.clearLoginAttempts).not.toHaveBeenCalled();
  });

  it("distinguishes an allowlist infrastructure outage from an unapproved email", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.findSubject.mockRejectedValueOnce(Object.assign(new Error("secret dsn"), { code: "BLOCKED" }));
    const response = await POST(request({ email: "person@example.com" }));

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: AUTH_INFRASTRUCTURE_MESSAGE,
      code: "AUTH_INFRASTRUCTURE_UNAVAILABLE",
    });
    expect(AUTH_INFRASTRUCTURE_MESSAGE).not.toBe(AUTH_REJECTED_MESSAGE);
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(mocks.clearLoginAttempts).not.toHaveBeenCalled();
  });

  it("fails closed when the session secret is missing", async () => {
    delete process.env.DASHBOARD_SESSION_SECRET;
    const response = await POST(request({ email: "person@example.com" }));
    expect(response.status).toBe(503);
    expect(mocks.consumeLoginAttempts).not.toHaveBeenCalled();
    expect(mocks.findSubject).not.toHaveBeenCalled();
  });

  it("rejects bodies over 4 KiB before rate-limit or allowlist actions", async () => {
    const response = await POST(request({ email: `${"a".repeat(4096)}@example.com` }));
    expect(response.status).toBe(413);
    expect(mocks.consumeLoginAttempts).not.toHaveBeenCalled();
    expect(mocks.findSubject).not.toHaveBeenCalled();
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
