import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperationsInsightsWorkspace } from "@/components/operations-insights-workspace";

const overview = {
  generatedAt: "2026-08-22T06:00:00Z", asOfAt: "2026-08-22T06:00:00Z", policyVersion: "SOURCE_HEALTH_V1",
  summary: { sourceCount: 2, onboardedSourceCount: 1, notOnboardedSourceCount: 1, distinctDocumentCount: 12554, documentVersionCount: 14427, runCount: 3056 },
  runStatusCounts: [{ status: "COMPLETED", count: 3056 }],
  classificationQuality: {
    currentAssignmentCount: 28079, supersededAssignmentCount: 735,
    reviewStatusCounts: [{ status: "APPROVED", count: 28079 }],
    evidenceStatusCounts: [{ status: "DIRECT_STRUCTURED", count: 15525 }, { status: "MEDIA_DIRECT", count: 8542 }],
    schemes: [{ schemeCode: "DOCUMENT_PURPOSE", schemeName: "문서 활용 목적", cardinality: "SINGLE", vocabularyVersion: "1.0.0", eligibleTargetCount: 12554, assignedTargetCount: 12554, approvedTargetCount: 12554, pendingTargetCount: 0, primaryTargetCount: 12554, primaryMissingCount: 0, primaryConflictCount: 0, deprecatedAssignmentCount: 0 }],
  },
  sources: [{
    sourceCode: "GOOGLE_NEWS_RSS", sourceName: "Google News RSS", sourceKind: "RSS", onboarding: "ONBOARDED", slaMode: "SCHEDULED", freshness: "NO_SLA", latestExecution: "COMPLETED", dataOutcome: "NEW_DATA", activeJobCount: 118, scheduledJobCount: 14, runCount: 2783, completedRunCount: 2783, distinctDocumentCount: 8444, documentVersionCount: 8664, latestSuccessfulAt: "2026-08-21T00:15:59Z", latestRunAt: "2026-08-21T00:15:59Z", expectedIntervalSeconds: null, graceSeconds: null, latestDiscoveredCount: 10, latestInsertedCount: 2, latestUpdatedCount: 0, latestRejectedCount: 0,
  }, {
    sourceCode: "KOSIS", sourceName: "국가통계포털", sourceKind: "STATISTICS", onboarding: "NOT_ONBOARDED", slaMode: "NOT_ONBOARDED", freshness: "NO_SLA", latestExecution: "NONE", dataOutcome: "UNKNOWN", activeJobCount: 0, scheduledJobCount: 0, runCount: 0, completedRunCount: 0, distinctDocumentCount: 0, documentVersionCount: 0, latestSuccessfulAt: null, latestRunAt: null, expectedIntervalSeconds: null, graceSeconds: null, latestDiscoveredCount: null, latestInsertedCount: null, latestUpdatedCount: null, latestRejectedCount: null,
  }],
};

afterEach(() => vi.restoreAllMocks());

describe("OperationsInsightsWorkspace", () => {
  it("shows source health axes separately and retains sources with zero data", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(overview), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<OperationsInsightsWorkspace />);

    expect(await screen.findByRole("heading", { name: "적재 상태부터 시장 신호까지 한 화면에서 점검" })).toBeInTheDocument();
    expect(screen.getByText("12,554")).toBeInTheDocument();
    expect(screen.getByText("Google News RSS")).toBeInTheDocument();
    expect(screen.getByText("국가통계포털")).toBeInTheDocument();
    expect(screen.getAllByText("SLA 미정").length).toBeGreaterThan(0);
    expect(screen.getByText("미온보딩")).toBeInTheDocument();
    expect(screen.getByText("최근 실행 없음")).toBeInTheDocument();
    expect(screen.queryByText("지연")).not.toBeInTheDocument();
  });

  it("shows classification coverage and review/evidence axes without treating system approval as human review", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(overview), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<OperationsInsightsWorkspace />);
    await user.click(await screen.findByRole("button", { name: /분류·검토/ }));
    expect(screen.getByText("문서 활용 목적")).toBeInTheDocument();
    expect(screen.getByText("12,554 / 12,554")).toBeInTheDocument();
    expect(screen.getByText("MEDIA_DIRECT")).toBeInTheDocument();
    expect(screen.getByText(/자동 승인 포함/)).toBeInTheDocument();
    expect(screen.queryByText("사람 검토 완료")).not.toBeInTheDocument();
  });

  it("loads the selected analysis panel without waiting for the overview request", async () => {
    const user = userEvent.setup();
    const keywords = {
      generatedAt: "2026-08-22T00:00:00Z", algorithmVersion: "KO_TITLE_PHRASE_DF_V1",
      computedAt: "2026-08-22T00:00:00Z", windowStart: "2026-07-01", windowEnd: "2026-08-22", latestDate: "2026-08-22",
      summary: { keywordCount: 1, observationCount: 1, qualifiedKeywordCount: 1, excludedMissingPublicationCount: 0 },
      keywords: [{ keywordId: "kw1", term: "데이터센터", termKind: "TOKEN", isCollectionBias: false, documentFrequency: 8, baselineDocumentFrequency: 2, burstScore: 3.46, trend: [], cooccurrences: [] }],
    };
    const overviewPending = new Promise<Response>(() => undefined);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/keywords")) return new Response(JSON.stringify(keywords), { status: 200, headers: { "Content-Type": "application/json" } });
      return overviewPending;
    });

    render(<OperationsInsightsWorkspace />);
    await user.click(screen.getByRole("button", { name: /키워드/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/operations/keywords?limit=30", { credentials: "same-origin" }));
    expect(await screen.findByText("데이터센터")).toBeInTheDocument();
    expect(screen.queryByText("운영 현황 조회 중")).not.toBeInTheDocument();
  });

  it("opens a signal evidence document through the workspace callback", async () => {
    const user = userEvent.setup(); const open = vi.fn();
    const insights = { generatedAt: "2026-08-22T00:00:00Z", algorithmVersion: "KEYWORD_BURST_SIGNAL_V1", statusCounts: [{ status: "UNREVIEWED", count: 1 }], signals: [{ signalId: "sig1", signalType: "KEYWORD_BURST", signalDate: "2026-08-20", title: "데이터센터 언급 급상승", summary: "고유 문서 8건", reviewStatus: "UNREVIEWED", severity: "HIGH", scores: { strength: .8, evidence: .4, sourceDiversity: .67, confidence: .65 }, syndicationDedupeStatus: "PARTIAL", evidence: [{ targetKind: "DOCUMENT", targetId: "doc1", documentId: "doc1", documentVersionId: "ver1", title: "데이터센터 근거", sourceName: "공식 출처", publishedAt: "2026-08-20T00:00:00Z", canonicalUrl: null, role: "TRIGGER", rank: 1 }] }] };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/insights") ? insights : overview), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<OperationsInsightsWorkspace onOpenDocument={open}/>);
    await user.click(await screen.findByRole("button", { name: /인사이트 신호/ }));
    await user.click(await screen.findByRole("button", { name: /데이터센터 근거/ }));
    expect(open).toHaveBeenCalledWith("doc1", "데이터센터 근거");
  });
});
