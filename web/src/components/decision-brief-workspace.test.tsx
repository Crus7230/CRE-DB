import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionBriefWorkspace } from "@/components/decision-brief-workspace";

vi.mock("@/components/quantitative-market-pulse", () => ({
  QuantitativeMarketPulse: ({ variant }: { variant?: string }) => <section data-testid="market-pulse" data-variant={variant}/>,
}));

const daily = {
  selectedDate: "2026-08-29",
  latestAvailableDate: "2026-08-29",
  lastCollectedAt: "2026-08-29T01:15:00Z",
  generatedAt: "2026-08-29T01:16:00Z",
  total: 2,
  articles: [{
    id: "doc-1", title: "서울 오피스 거래 회복", publisher: "테스트경제",
    publishedAt: "2026-08-29T00:30:00Z", collectedAt: "2026-08-29T01:15:00Z",
    summary: "오피스 거래량과 주요 거래를 다룬 기사", summaryMode: "BODY_EXTRACTIVE",
    summaryGeneratedAt: "2026-08-29T01:16:00Z", href: null,
    topics: [{ key: "SALE", label: "매각", status: "CONFIRMED", provenance: "APPROVED_EVENT_MENTION" }],
    documentPurpose: { code: "MARKET_EVIDENCE", label: "시장동향 근거" },
    evidenceGrade: { code: "MEDIA_DIRECT", label: "직접 보도" },
  }],
};

const overview = {
  generatedAt: "2026-08-29T01:00:00Z", asOfAt: "2026-08-29T01:00:00Z", policyVersion: "SOURCE_HEALTH_V1",
  summary: { sourceCount: 2, onboardedSourceCount: 2, notOnboardedSourceCount: 0, distinctDocumentCount: 12000, documentVersionCount: 13000, runCount: 3000 },
  runStatusCounts: [{ status: "COMPLETED", count: 2999 }, { status: "FAILED", count: 1 }],
  classificationQuality: { currentAssignmentCount: 100, supersededAssignmentCount: 2, reviewStatusCounts: [{ status: "APPROVED", count: 80 }, { status: "PENDING", count: 20 }], evidenceStatusCounts: [{ status: "MEDIA_DIRECT", count: 100 }], schemes: [] },
  sources: [
    { sourceCode: "RSS", sourceName: "시장 뉴스", sourceKind: "RSS", onboarding: "ONBOARDED", slaMode: "SCHEDULED", freshness: "RECENT", latestExecution: "COMPLETED", dataOutcome: "NEW_DATA", activeJobCount: 1, scheduledJobCount: 1, runCount: 2999, completedRunCount: 2999, distinctDocumentCount: 11000, documentVersionCount: 12000, latestSuccessfulAt: "2026-08-29T01:00:00Z", latestRunAt: "2026-08-29T01:00:00Z", expectedIntervalSeconds: 86400, graceSeconds: 3600, latestDiscoveredCount: 10, latestInsertedCount: 2, latestUpdatedCount: 0, latestRejectedCount: 0 },
    { sourceCode: "DART", sourceName: "기업공시", sourceKind: "FILING", onboarding: "ONBOARDED", slaMode: "SCHEDULED", freshness: "OVERDUE", latestExecution: "FAILED", dataOutcome: "UNKNOWN", activeJobCount: 1, scheduledJobCount: 1, runCount: 1, completedRunCount: 0, distinctDocumentCount: 1000, documentVersionCount: 1000, latestSuccessfulAt: null, latestRunAt: "2026-08-28T01:00:00Z", expectedIntervalSeconds: 86400, graceSeconds: 3600, latestDiscoveredCount: null, latestInsertedCount: null, latestUpdatedCount: null, latestRejectedCount: null },
  ],
};

const keywords = {
  generatedAt: "2026-08-29T01:00:00Z", algorithmVersion: "KO_TITLE_PHRASE_DF_V1", computedAt: "2026-08-29T01:00:00Z",
  windowStart: "2026-08-01", windowEnd: "2026-08-29", latestDate: "2026-08-29",
  summary: { keywordCount: 2, observationCount: 20, qualifiedKeywordCount: 1, excludedMissingPublicationCount: 3 },
  keywords: [
    { keywordId: "kw-1", term: "데이터센터", termKind: "TOKEN", isCollectionBias: false, documentFrequency: 8, baselineDocumentFrequency: 2, burstScore: 3.5, trend: [{ date: "2026-08-28", documentFrequency: 2 }, { date: "2026-08-29", documentFrequency: 8 }], cooccurrences: [{ term: "전력", documentFrequency: 5 }] },
    { keywordId: "kw-2", term: "수집검색어", termKind: "TOKEN", isCollectionBias: true, documentFrequency: 10, baselineDocumentFrequency: 1, burstScore: 9, trend: [], cooccurrences: [] },
  ],
};

const insights = {
  generatedAt: "2026-08-29T01:00:00Z", algorithmVersion: "KEYWORD_BURST_SIGNAL_V1",
  statusCounts: [{ status: "UNREVIEWED", count: 1 }],
  signals: [{ signalId: "sig-1", signalType: "KEYWORD_BURST", signalDate: "2026-08-29", title: "데이터센터 언급 급상승", summary: "서로 다른 출처에서 관련 기사가 증가", reviewStatus: "UNREVIEWED", severity: "HIGH", scores: { strength: .8, evidence: .6, sourceDiversity: .7, confidence: .68 }, syndicationDedupeStatus: "PARTIAL", evidence: [{ targetKind: "DOCUMENT", targetId: "doc-1", documentId: "doc-1", documentVersionId: "ver-1", title: "서울 오피스 거래 회복", sourceName: "테스트경제", publishedAt: "2026-08-29T00:30:00Z", canonicalUrl: null, role: "TRIGGER", rank: 1 }] }],
};

afterEach(() => vi.restoreAllMocks());

function response(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }));
}

describe("DecisionBriefWorkspace", () => {
  it("turns current CRE data into a review-first briefing with evidence actions", async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    const openDocument = vi.fn();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/articles/daily")) return response(daily);
      if (url.includes("/operations/overview")) return response(overview);
      if (url.includes("/operations/keywords")) return response(keywords);
      return response(insights);
    });

    render(<DecisionBriefWorkspace onNavigate={navigate} onOpenDocument={openDocument}/>);

    expect(await screen.findByRole("heading", { name: "오늘 확인할 변화와 근거" })).toBeInTheDocument();
    expect(screen.getByTestId("market-pulse")).toHaveAttribute("data-variant", "summary");
    expect(await screen.findByText("데이터센터 언급 급상승")).toBeInTheDocument();
    expect(screen.getByText("검토 대기 신호").parentElement).toHaveTextContent("1");
    expect(screen.getByText("급상승 주제", { selector: "span" }).closest("article")).toHaveTextContent("1");
    expect(screen.getByText("우선 확인").parentElement).toHaveTextContent("1");
    expect(screen.getByText("데이터센터")).toBeInTheDocument();
    expect(screen.queryByText("수집검색어")).not.toBeInTheDocument();
    expect(screen.getByText("부분 중복제거")).toBeInTheDocument();
    expect(screen.getByText("직접 보도")).toBeInTheDocument();
    expect(screen.getByText("판단")).toBeInTheDocument();
    expect(screen.getByText("이유")).toBeInTheDocument();
    expect(screen.getByText("기사 최신일")).toBeInTheDocument();
    expect(screen.getByText("키워드 계산")).toBeInTheDocument();
    expect(screen.getByText("신호 계산")).toBeInTheDocument();
    expect(screen.getByText(/자료별 최신 기준/)).toBeInTheDocument();
    expect(screen.queryByText("활용 전 확인사항")).not.toBeInTheDocument();

    const evidenceTrigger = screen.getByRole("button", { name: /근거 1건/ });
    await user.click(evidenceTrigger);
    expect(screen.getByRole("dialog", { name: "데이터센터 언급 급상승 근거 1건" })).toBeInTheDocument();
    expect(screen.getByText("TRIGGER")).toBeInTheDocument();
    const closeEvidence = screen.getByRole("button", { name: "근거 닫기" });
    const openEvidenceDocument = screen.getByRole("button", { name: "문서 원문 보기" });
    expect(closeEvidence).toHaveFocus();
    await user.tab({ shift: true });
    expect(openEvidenceDocument).toHaveFocus();
    await user.click(openEvidenceDocument);
    expect(openDocument).toHaveBeenCalledWith("doc-1", "서울 오피스 거래 회복");
    expect(evidenceTrigger).not.toHaveFocus();
    await user.click(screen.getByRole("button", { name: "신호 전체 검토" }));
    expect(navigate).toHaveBeenCalledWith("OPERATIONS");
  });

  it("keeps successful slices visible when one briefing API fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/operations/insights")) return response({ error: "unavailable" }, 503);
      if (url.includes("/articles/daily")) return response(daily);
      if (url.includes("/operations/overview")) return response(overview);
      return response(keywords);
    });

    render(<DecisionBriefWorkspace onNavigate={vi.fn()} onOpenDocument={vi.fn()}/>);

    expect(await screen.findByText("서울 오피스 거래 회복")).toBeInTheDocument();
    expect(screen.getByText("데이터센터")).toBeInTheDocument();
    expect(screen.getByText("신호 데이터를 불러오지 못했습니다.")).toBeInTheDocument();
  });

  it("does not promote a one-document term to a rising theme", async () => {
    const lowSample = { ...keywords, summary: { ...keywords.summary, qualifiedKeywordCount: 0 }, keywords: [{ ...keywords.keywords[0], documentFrequency: 1 }] };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/articles/daily")) return response(daily);
      if (url.includes("/operations/overview")) return response(overview);
      if (url.includes("/operations/keywords")) return response(lowSample);
      return response(insights);
    });

    render(<DecisionBriefWorkspace onNavigate={vi.fn()} onOpenDocument={vi.fn()}/>);

    expect(await screen.findByRole("heading", { name: "저표본 관찰어" })).toBeInTheDocument();
    expect(screen.getByText("급상승 주제", { selector: "span" }).closest("article")).toHaveTextContent("0");
    expect(screen.getByText(/모든 후보가 문서빈도 1건으로 상승 확정에서 제외/)).toBeInTheDocument();
  });

  it("filters for qualified momentum before limiting the displayed list", async () => {
    const lowTerms = Array.from({ length: 5 }, (_, index) => ({ ...keywords.keywords[0], keywordId: `low-${index}`, term: `저표본-${index}`, documentFrequency: 1, burstScore: 10 - index }));
    const qualified = { ...keywords.keywords[0], keywordId: "qualified", term: "유효 상승어", documentFrequency: 2, burstScore: 0.1 };
    const payload = { ...keywords, keywords: [...lowTerms, qualified] };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/articles/daily")) return response(daily);
      if (url.includes("/operations/overview")) return response(overview);
      if (url.includes("/operations/keywords")) return response(payload);
      return response(insights);
    });

    render(<DecisionBriefWorkspace onNavigate={vi.fn()} onOpenDocument={vi.fn()}/>);

    expect(await screen.findByRole("heading", { name: "급상승 주제" })).toBeInTheDocument();
    expect(screen.getByText("급상승 주제", { selector: "span" }).closest("article")).toHaveTextContent("1");
    expect(screen.getByText("유효 상승어")).toBeInTheDocument();
    expect(screen.queryByText("저표본-0")).not.toBeInTheDocument();
  });
});
