import { describe, expect, it } from "vitest";
import { normalizeKeywordAnalytics } from "@/lib/keyword-analytics-contract";

const payload = {
  generatedAt: "2026-08-22T00:00:00Z", algorithmVersion: "KO_TITLE_PHRASE_DF_V1",
  computedAt: "2026-08-22T00:00:00Z", windowStart: "2026-07-01", windowEnd: "2026-08-22", latestDate: "2026-08-22",
  summary: { keywordCount: 100, observationCount: 200, qualifiedKeywordCount: 1, excludedMissingPublicationCount: 60 },
  keywords: [{ keywordId: "kw1", term: "데이터센터", termKind: "TOKEN", isCollectionBias: false, documentFrequency: 8, baselineDocumentFrequency: 2, burstScore: 3.46, trend: [{ date: "2026-08-22", documentFrequency: 8 }], cooccurrences: [{ term: "전력", documentFrequency: 3 }] }],
};

describe("normalizeKeywordAnalytics", () => {
  it("accepts versioned aggregate payloads", () => expect(normalizeKeywordAnalytics(payload)).toEqual(payload));
  it("rejects an unversioned payload", () => expect(() => normalizeKeywordAnalytics({ ...payload, algorithmVersion: "" })).toThrow());
  it("rejects a payload without the limit-independent qualified count", () => expect(() => normalizeKeywordAnalytics({ ...payload, summary: { keywordCount: 100, observationCount: 200, excludedMissingPublicationCount: 60 } })).toThrow());
});
