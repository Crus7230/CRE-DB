import { afterEach, describe, expect, it } from "vitest";
import { POST } from "@/app/api/auth/logout/route";

afterEach(() => {
  delete process.env.VERCEL;
});

describe("POST /api/auth/logout", () => {
  it("deletes the local-development cookie without an unusable Secure attribute", async () => {
    const response = await POST(new Request("http://localhost/api/auth/logout", { method: "POST" }));
    const cookie = response.headers.get("set-cookie") ?? "";

    expect(response.status).toBe(200);
    expect(cookie).toContain("cre_db_session=;");
    expect(cookie).toContain("Max-Age=0");
    expect(cookie.toLowerCase()).not.toContain("; secure");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("uses Secure when deleting an HTTPS session cookie", async () => {
    const response = await POST(new Request("https://cre-db.example/api/auth/logout", { method: "POST" }));
    expect(response.headers.get("set-cookie")?.toLowerCase()).toContain("; secure");
  });
});
