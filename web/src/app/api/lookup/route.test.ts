// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
vi.mock("server-only", () => ({}));
vi.mock("@/lib/server/smart-lookup-http", () => ({ createLookupContext: vi.fn(() => ({})) }));
vi.mock("@/lib/server/smart-lookup", () => ({ LookupInputError: class extends Error {}, validateLookupRequest: vi.fn((input) => input), runSmartLookup: vi.fn(async () => ({ stage: "empty", cards: [] })) }));
import { createSessionToken, SESSION_COOKIE } from "@/lib/server/auth-session";
import { runSmartLookup } from "@/lib/server/smart-lookup";
import { POST } from "./route";

const secret = "test-session-secret-at-least-32-characters";
async function request(body: string, extra: Record<string, string> = {}, authenticated = true) {
  const token = authenticated ? await createSessionToken("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", secret) : "";
  return new NextRequest("http://localhost:3006/api/lookup", { method: "POST", headers: { "content-type": "application/json", cookie: `${SESSION_COOKIE}=${token}`, ...extra }, body });
}
beforeEach(() => { process.env.DASHBOARD_SESSION_SECRET = secret; vi.clearAllMocks(); });
describe("lookup protected route", () => {
  it("does not call a source without authentication", async () => {
    expect((await POST(await request('{"query":"삼성전자"}', {}, false))).status).toBe(401);
    expect(runSmartLookup).not.toHaveBeenCalled();
  });
  it("rejects cross-origin requests", async () => {
    expect((await POST(await request('{"query":"삼성전자"}', { origin: "https://evil.test" }))).status).toBe(403);
    expect(runSmartLookup).not.toHaveBeenCalled();
  });
  it("accepts the browser Host origin when Next reconstructs request.url with a different local hostname", async () => {
    const result = await POST(await request('{"query":"삼성전자"}', {
      host: "127.0.0.1:3006",
      origin: "http://127.0.0.1:3006",
    }));
    expect(result.status).toBe(200);
    expect(runSmartLookup).toHaveBeenCalledOnce();
  });
  it("rejects invalid JSON", async () => {
    expect((await POST(await request("broken"))).status).toBe(400);
    expect(runSmartLookup).not.toHaveBeenCalled();
  });
  it("returns private responses for authenticated lookup", async () => {
    const result = await POST(await request('{"query":"삼성전자"}'));
    expect(result.status).toBe(200);
    expect(result.headers.get("cache-control")).toBe("private, no-store");
    expect(runSmartLookup).toHaveBeenCalledOnce();
  });
});
