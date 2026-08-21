import { afterEach, describe, expect, it, vi } from "vitest";
import { AUTH_REJECTED_MESSAGE, verifySessionToken } from "@/lib/server/auth-session";

const { executeAuthSqlMock } = vi.hoisted(() => ({ executeAuthSqlMock: vi.fn() }));
vi.mock("@/lib/server/db", () => ({ executeAuthSql: executeAuthSqlMock }));

import { POST } from "@/app/api/auth/login/route";

const SUBJECT_ID = "49caafcd-f6c5-4d79-92bd-6f4cd968cf25";
const SESSION_SECRET = "0123456789abcdef0123456789abcdef";

afterEach(() => {
  delete process.env.DASHBOARD_SESSION_SECRET;
  delete process.env.VERCEL;
  executeAuthSqlMock.mockReset();
  vi.restoreAllMocks();
});

describe("POST /api/auth/login", () => {
  it("returns one generic rejection for missing, disabled, revoked, or expired access", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    executeAuthSqlMock.mockResolvedValue({ rows: [] });
    for (const state of ["missing", "disabled", "revoked", "expired"]) {
      const response = await POST(new Request("http://localhost/api/auth/login", { method: "POST", body: JSON.stringify({ email: `${state}@example.com` }) }));
      expect(response.status).toBe(401);
      expect(await response.json()).toEqual({ error: AUTH_REJECTED_MESSAGE });
      expect(response.headers.get("set-cookie")).toBeNull();
    }
  });

  it("normalizes an approved email and sets the Android-compatible 12-hour cookie", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    executeAuthSqlMock.mockResolvedValue({ rows: [{ subject_id: SUBJECT_ID }] });
    const response = await POST(new Request("http://localhost/api/auth/login", { method: "POST", body: JSON.stringify({ email: "  Person@Example.COM " }) }));
    const cookie = response.headers.get("set-cookie") ?? "";
    const token = cookie.match(/^cre_db_session=([^;]+)/u)?.[1] ?? "";

    expect(response.status).toBe(200);
    expect(cookie).toContain("cre_db_session=");
    expect(cookie).toContain("Max-Age=43200");
    expect(cookie.toLowerCase()).toContain("httponly");
    expect(cookie.toLowerCase()).toContain("samesite=lax");
    expect(cookie).not.toContain("person@example.com");
    expect(cookie.toLowerCase()).not.toContain("; secure");
    expect(executeAuthSqlMock.mock.calls[0][1]).toEqual(["person@example.com"]);
    expect((await verifySessionToken(token, SESSION_SECRET))?.subjectId).toBe(SUBJECT_ID);
  });

  it("marks the session cookie Secure for HTTPS deployments", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    executeAuthSqlMock.mockResolvedValue({ rows: [{ subject_id: SUBJECT_ID }] });
    const response = await POST(new Request("https://cre-db.example/api/auth/login", { method: "POST", body: JSON.stringify({ email: "person@example.com" }) }));
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")?.toLowerCase()).toContain("; secure");
  });

  it("does not disclose malformed-email membership with a different message", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    const response = await POST(new Request("http://localhost/api/auth/login", { method: "POST", body: JSON.stringify({ email: "not-an-email" }) }));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: AUTH_REJECTED_MESSAGE });
    expect(executeAuthSqlMock).not.toHaveBeenCalled();
  });

  it("does not leak email or database details when the allowlist lookup fails", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    executeAuthSqlMock.mockRejectedValue(new Error("database detail containing person@example.com"));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await POST(new Request("http://localhost/api/auth/login", { method: "POST", body: JSON.stringify({ email: "person@example.com" }) }));

    expect(response.status).toBe(503);
    expect(JSON.stringify(await response.json())).not.toContain("person@example.com");
    expect(consoleError).toHaveBeenCalledWith("Dashboard email allowlist lookup failed");
  });

  it("rejects login bodies over 4 KiB before querying the allowlist", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    const response = await POST(new Request("http://localhost/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: `${"a".repeat(4_096)}@example.com` }),
    }));

    expect(response.status).toBe(413);
    expect(executeAuthSqlMock).not.toHaveBeenCalled();
  });

  it("fails closed when the configured session secret is too short", async () => {
    process.env.DASHBOARD_SESSION_SECRET = "short-secret";
    const response = await POST(new Request("http://localhost/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: "person@example.com" }),
    }));

    expect(response.status).toBe(503);
    expect(executeAuthSqlMock).not.toHaveBeenCalled();
  });
});
