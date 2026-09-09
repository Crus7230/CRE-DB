import { describe, expect, it } from "vitest";
import {
  EvidenceSearchRequestError,
  normalizeEvidenceSearchResponse,
  parseEvidenceSearchBody,
} from "@/lib/evidence-search-contract";

const request = {
  q: "매각",
  from: "2026-08-01",
  to: "2026-09-09",
  topic: "SALE",
  topK: 8,
};

function payload(overrides: Record<string, unknown> = {}) {
  return {
    datasetVersion: "dataset-v1",
    query: "매각",
    generatedAt: "2026-09-09T00:00:00.000Z",
    returned: 1,
    truncated: false,
    items: [{
      documentId: "doc-1",
      title: "서울 오피스 매각",
      publisher: "테스트뉴스",
      publishedAt: "2026-09-08T12:00:00+09:00",
      href: "https://example.com/article/1",
      evidenceText: "첫 문단입니다.\n\n두 번째 문단의 매각 내용입니다.\t추가 문장",
      score: 0.75,
    }],
    ...overrides,
  };
}

describe("evidence search contract", () => {
  it("normalizes a bounded two-character query and optional filters", () => {
    expect(parseEvidenceSearchBody({ q: "  매각  ", from: "", to: null, topic: "", topK: 8 })).toEqual({
      q: "매각", from: null, to: null, topic: null, topK: 8,
    });
  });

  it("rejects short queries, invalid date ranges, and unbounded result requests", () => {
    expect(() => parseEvidenceSearchBody({ q: "매" })).toThrow(EvidenceSearchRequestError);
    expect(() => parseEvidenceSearchBody({ q: "매각", from: "2026-09-10", to: "2026-09-09" })).toThrow(EvidenceSearchRequestError);
    expect(() => parseEvidenceSearchBody({ q: "매각", topK: 9 })).toThrow(EvidenceSearchRequestError);
  });

  it("accepts multiline source excerpts and normalizes display whitespace", () => {
    const normalized = normalizeEvidenceSearchResponse(payload(), request, "dataset-v1");
    expect(normalized.items[0].evidenceText).toBe("첫 문단입니다. 두 번째 문단의 매각 내용입니다. 추가 문장");
    expect(normalized.returned).toBe(1);
    expect(normalized.maxResults).toBe(8);
  });

  it("fails closed on version drift, duplicate documents, unsafe links, or excessive rows", () => {
    expect(() => normalizeEvidenceSearchResponse(payload(), request, "dataset-v2")).toThrow(/version mismatch/u);
    expect(() => normalizeEvidenceSearchResponse(payload({
      returned: 2,
      items: [payload().items[0], payload().items[0]],
    }), request, "dataset-v1")).toThrow(/Duplicate/u);
    expect(() => normalizeEvidenceSearchResponse(payload({
      items: [{ ...payload().items[0], href: "javascript:alert(1)" }],
    }), request, "dataset-v1")).toThrow(/href/u);
    expect(() => normalizeEvidenceSearchResponse(payload({
      returned: 9,
      items: Array.from({ length: 9 }, (_, index) => ({ ...payload().items[0], documentId: `doc-${index}` })),
    }), request, "dataset-v1")).toThrow(/limit/u);
  });
});
