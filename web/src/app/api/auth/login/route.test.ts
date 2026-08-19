import { afterEach, describe, expect, it } from "vitest";
import { POST } from "@/app/api/auth/login/route";

afterEach(() => {
  delete process.env.DASHBOARD_ACCESS_CODE;
  delete process.env.DASHBOARD_SESSION_SECRET;
});

describe("POST /api/auth/login", () => {
  it("rejects an incorrect shared access code", async () => {
    process.env.DASHBOARD_ACCESS_CODE = "correct-code";
    process.env.DASHBOARD_SESSION_SECRET = "session-secret";
    const response = await POST(new Request("http://localhost/api/auth/login", { method: "POST", body: JSON.stringify({ code: "wrong-code" }) }));
    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("sets an HttpOnly signed session cookie for the correct code", async () => {
    process.env.DASHBOARD_ACCESS_CODE = "correct-code";
    process.env.DASHBOARD_SESSION_SECRET = "session-secret";
    const response = await POST(new Request("http://localhost/api/auth/login", { method: "POST", body: JSON.stringify({ code: "correct-code" }) }));
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(response.status).toBe(200);
    expect(cookie).toContain("cre_db_session=");
    expect(cookie.toLowerCase()).toContain("httponly");
    expect(cookie.toLowerCase()).toContain("samesite=lax");
    expect(cookie).not.toContain("correct-code");
    expect(cookie.toLowerCase()).not.toContain("; secure");
  });

  it("marks the session cookie Secure for HTTPS deployments", async () => {
    process.env.DASHBOARD_ACCESS_CODE = "correct-code";
    process.env.DASHBOARD_SESSION_SECRET = "session-secret";
    const response = await POST(new Request("https://cre-db.example/api/auth/login", { method: "POST", body: JSON.stringify({ code: "correct-code" }) }));
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")?.toLowerCase()).toContain("; secure");
  });
});
