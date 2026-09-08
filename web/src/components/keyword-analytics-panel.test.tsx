import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { KeywordAnalyticsPanel } from "@/components/keyword-analytics-panel";

const payload = { generatedAt: "2026-08-22T00:00:00Z", algorithmVersion: "KO_TITLE_PHRASE_DF_V1", computedAt: "2026-08-22T00:00:00Z", windowStart: "2026-07-01", windowEnd: "2026-08-22", latestDate: "2026-08-22", summary: { keywordCount: 100, observationCount: 200, qualifiedKeywordCount: 1, excludedMissingPublicationCount: 60 }, keywords: [{ keywordId: "kw1", term: "데이터센터", termKind: "TOKEN", isCollectionBias: false, documentFrequency: 8, baselineDocumentFrequency: 2, burstScore: 3.46, trend: [{ date: "2026-08-22", documentFrequency: 8 }], cooccurrences: [{ term: "전력", documentFrequency: 3 }] }, { keywordId: "kw2", term: "매각", termKind: "TOKEN", isCollectionBias: true, documentFrequency: 20, baselineDocumentFrequency: 10, burstScore: 2.1, trend: [], cooccurrences: [] }] };

afterEach(() => vi.unstubAllGlobals());
describe("KeywordAnalyticsPanel", () => {
  it("shows burst semantics and collection bias separately", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => payload }));
    render(<KeywordAnalyticsPanel/>);
    expect(await screen.findByText("데이터센터")).toBeInTheDocument();
    expect(screen.getByText("수집 query 영향")).toBeInTheDocument();
    expect(screen.getByText(/distinct document/)).toBeInTheDocument();
    expect(screen.getByText("전력")).toBeInTheDocument();
  });
});
