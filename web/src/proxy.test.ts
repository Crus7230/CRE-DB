import { afterEach, describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";

afterEach(() => {
  delete process.env.DASHBOARD_ACCESS_CODE;
  delete process.env.DASHBOARD_SESSION_SECRET;
});

describe("dashboard proxy", () => {
  it("redirects unauthenticated pages to login", () => {
    process.env.DASHBOARD_ACCESS_CODE = "team-code";
    process.env.DASHBOARD_SESSION_SECRET = "session-secret";
    const response = proxy(new NextRequest("https://example.com/"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("https://example.com/login");
  });

  it("returns 401 JSON for unauthenticated APIs", async () => {
    process.env.DASHBOARD_ACCESS_CODE = "team-code";
    process.env.DASHBOARD_SESSION_SECRET = "session-secret";
    const response = proxy(new NextRequest("https://example.com/api/index"));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "인증이 필요합니다." });
  });
});
