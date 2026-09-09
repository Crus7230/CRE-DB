import { beforeEach, describe, expect, it, vi } from "vitest";
import { DATA_SERVER_UNAVAILABLE_MESSAGE } from "@/lib/server/api-response";

const mocks = vi.hoisted(() => ({
  getCachedArticleDetail: vi.fn(),
  executeNewsSql: vi.fn(),
  canUseNewsArchiveFallback: vi.fn(),
  getDocumentDetail: vi.fn(),
}));

vi.mock("@/lib/server/market-data-cache", () => ({
  getCachedArticleDetail: mocks.getCachedArticleDetail,
}));
vi.mock("@/lib/server/db", () => ({
  executeNewsSql: mocks.executeNewsSql,
  canUseNewsArchiveFallback: mocks.canUseNewsArchiveFallback,
}));
vi.mock("@/lib/server/document-intelligence", () => ({
  getDocumentDetail: mocks.getDocumentDetail,
}));

import { GET } from "@/app/api/documents/[id]/route";

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

describe("document detail cache-adapter routing", () => {
  it("returns a controlled no-store 404 for a cached compact miss without raw fallback", async () => {
    mocks.getCachedArticleDetail.mockResolvedValue(null);

    const response = await GET(
      new Request("https://dashboard.example/api/documents/missing"),
      { params: Promise.resolve({ id: "missing" }) },
    );

    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    await expect(response.json()).resolves.toEqual({ error: "문서를 찾지 못했습니다." });
    expect(mocks.getCachedArticleDetail).toHaveBeenCalledOnce();
    expect(mocks.getCachedArticleDetail).toHaveBeenCalledWith("missing");
    expect(mocks.executeNewsSql).not.toHaveBeenCalled();
    expect(mocks.canUseNewsArchiveFallback).not.toHaveBeenCalled();
    expect(mocks.getDocumentDetail).not.toHaveBeenCalled();
  });

  it("serves the cache-adapter detail without reintroducing route-level raw fallback", async () => {
    const detail = { id: "supabase-article", title: "Article" };
    mocks.getCachedArticleDetail.mockResolvedValue(detail);

    const response = await GET(
      new Request("https://dashboard.example/api/documents/supabase-article"),
      { params: Promise.resolve({ id: "supabase-article" }) },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    await expect(response.json()).resolves.toEqual(detail);
    expect(mocks.getCachedArticleDetail).toHaveBeenCalledWith("supabase-article");
    expect(mocks.executeNewsSql).not.toHaveBeenCalled();
    expect(mocks.canUseNewsArchiveFallback).not.toHaveBeenCalled();
    expect(mocks.getDocumentDetail).not.toHaveBeenCalled();
  });

  it("returns a controlled no-store 503 when the cache adapter is unavailable", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.getCachedArticleDetail.mockRejectedValueOnce(new Error("upstream unavailable"));

    const response = await GET(
      new Request("https://dashboard.example/api/documents/article"),
      { params: Promise.resolve({ id: "article" }) },
    );

    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    await expect(response.json()).resolves.toEqual({
      error: DATA_SERVER_UNAVAILABLE_MESSAGE,
      code: "DOCUMENT_DETAIL_UNAVAILABLE",
    });
  });
});
