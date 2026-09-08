import { describe, expect, it, vi } from "vitest";
import { runOperationsOverviewRequest } from "@/lib/server/operations-insights-route";

describe("runOperationsOverviewRequest", () => {
  it("returns a private response", async () => {
    const response = await runOperationsOverviewRequest(async () => ({ ok: true } as never));
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("private, max-age=60");
  });

  it("does not expose database errors, queries or connection details", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await runOperationsOverviewRequest(async () => {
      throw new Error("postgres://secret@example.invalid query=SELECT cursor=private");
    });
    expect(response.status).toBe(503);
    const body = await response.text();
    expect(body).toContain("운영 현황을 불러오지 못했습니다");
    expect(body).not.toContain("postgres://");
    expect(body).not.toContain("SELECT");
    expect(body).not.toContain("cursor");
  });
});
