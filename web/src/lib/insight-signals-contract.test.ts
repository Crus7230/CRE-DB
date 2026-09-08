import { describe, expect, it } from "vitest";
import { normalizeInsightSignals } from "@/lib/insight-signals-contract";

const payload = { generatedAt: "2026-08-22T00:00:00Z", algorithmVersion: "KEYWORD_BURST_SIGNAL_V1", statusCounts: [{ status: "UNREVIEWED", count: 1 }], signals: [{ signalId: "sig1", signalType: "KEYWORD_BURST", signalDate: "2026-08-20", title: "데이터센터 언급 급상승", summary: "발행일 기준 고유 문서 8건", reviewStatus: "UNREVIEWED", severity: "HIGH", scores: { strength: .8, evidence: .4, sourceDiversity: .67, confidence: .65 }, syndicationDedupeStatus: "PARTIAL", evidence: [{ targetKind: "DOCUMENT", targetId: "d1", documentId: "d1", documentVersionId: "v1", title: "데이터센터 투자", sourceName: "출처", publishedAt: "2026-08-20T00:00:00Z", canonicalUrl: "https://example.com", role: "TRIGGER", rank: 1 }] }] };

describe("normalizeInsightSignals", () => {
  it("preserves review status, component scores and evidence lineage", () => expect(normalizeInsightSignals(payload)).toEqual(payload));
  it("preserves a null calculation time when no signal has been computed", () => expect(normalizeInsightSignals({ ...payload, generatedAt: null }).generatedAt).toBeNull());
  it("rejects evidence without a document target", () => {
    const broken = structuredClone(payload); broken.signals[0].evidence[0].documentId = "";
    expect(() => normalizeInsightSignals(broken)).toThrow();
  });
});
