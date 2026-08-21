import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createSessionToken, SESSION_COOKIE } from "@/lib/server/auth-session";
import { proxy } from "@/proxy";

const SUBJECT_ID = "49caafcd-f6c5-4d79-92bd-6f4cd968cf25";
const SESSION_SECRET = "0123456789abcdef0123456789abcdef";

afterEach(() => {
  delete process.env.DASHBOARD_SESSION_SECRET;
  vi.useRealTimers();
});

describe("dashboard proxy", () => {
  it("redirects unauthenticated pages to login", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    const response = await proxy(new NextRequest("https://example.com/"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("https://example.com/login");
  });

  it("returns 401 JSON for unauthenticated APIs", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    const response = await proxy(new NextRequest("https://example.com/api/index"));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "인증이 필요합니다." });
  });

  it("accepts a valid unexpired signed session and rejects an expired one", async () => {
    process.env.DASHBOARD_SESSION_SECRET = SESSION_SECRET;
    const issuedAt = new Date("2026-08-21T00:00:00Z");
    const token = await createSessionToken(SUBJECT_ID, SESSION_SECRET, issuedAt);
    const validRequest = new NextRequest("https://example.com/api/index", { headers: { Cookie: `${SESSION_COOKIE}=${token}` } });
    const expiredRequest = new NextRequest("https://example.com/api/index", { headers: { Cookie: `${SESSION_COOKIE}=${token}` } });

    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-21T11:59:59Z"));
    expect((await proxy(validRequest)).status).toBe(200);
    vi.setSystemTime(new Date("2026-08-21T12:00:00Z"));
    expect((await proxy(expiredRequest)).status).toBe(401);
  });
});
