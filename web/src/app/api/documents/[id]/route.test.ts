import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  execute: vi.fn(),
  isLocalAuthority: vi.fn(),
  getDocumentDetail: vi.fn(),
}));

vi.mock("@/lib/server/db", () => ({
  executeMarketSql: mocks.execute,
  isLocalMarketDatabaseAuthority: mocks.isLocalAuthority,
}));
vi.mock("@/lib/server/document-intelligence", () => ({
  getDocumentDetail: mocks.getDocumentDetail,
}));

import { GET } from "@/app/api/documents/[id]/route";

beforeEach(() => {
  mocks.execute.mockReset();
  mocks.isLocalAuthority.mockReset();
  mocks.getDocumentDetail.mockReset();
});

describe("document detail authority routing", () => {
  it("returns a controlled 404 without enabling raw fallback for a remote compact miss", async () => {
    mocks.isLocalAuthority.mockReturnValue(false);
    mocks.getDocumentDetail.mockResolvedValue(null);

    const response = await GET(
      new Request("https://dashboard.example/api/documents/missing"),
      { params: Promise.resolve({ id: "missing" }) },
    );

    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({ error: "문서를 찾지 못했습니다." });
    expect(mocks.getDocumentDetail).toHaveBeenCalledWith(mocks.execute, "missing", {
      allowArchiveFallback: false,
    });
  });

  it("enables legacy raw fallback only for an explicit local database authority", async () => {
    mocks.isLocalAuthority.mockReturnValue(true);
    mocks.getDocumentDetail.mockResolvedValue({ id: "legacy-local" });

    const response = await GET(
      new Request("http://localhost/api/documents/legacy-local"),
      { params: Promise.resolve({ id: "legacy-local" }) },
    );

    expect(response.status).toBe(200);
    expect(mocks.getDocumentDetail).toHaveBeenCalledWith(mocks.execute, "legacy-local", {
      allowArchiveFallback: true,
    });
  });
});
