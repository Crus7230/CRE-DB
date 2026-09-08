import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { InstitutionalCapitalWorkspace } from "@/components/institutional-capital-workspace";
import type { InstitutionalCapitalResponse, InstitutionalSelectionAssessment } from "@/lib/intelligence-contract";

const assessment: InstitutionalSelectionAssessment = {
  assessmentId: "claim-cw-2024-capstone",
  managerOrganizationId: "org-capstone",
  managerName: "캡스톤자산운용",
  trackCode: "DOMESTIC_SENIOR_REAL_ESTATE_DEBT",
  trackName: "국내 부동산 선순위 대출",
  verdict: "REVIEW_REQUIRED",
  verdictLabel: "검토 필요",
  confidence: 0.72,
  confidenceBand: "MEDIUM",
  rationale: "캡스톤자산운용이 선정사로 보도됐지만 공식 결과나 동일 자금의 후속 집행 연결이 필요합니다.",
  actionLabel: "기사상 선정 보도",
  reportedAllocation: "50000000000",
  allocationCurrency: "KRW",
  steps: [
    { code: "LP_SOURCE", label: "기관·자금 출처", status: "CONFIRMED", detail: "건설근로자공제회 공고 확인", evidenceDocumentIds: ["doc-notice"] },
    { code: "TRACK_MATCH", label: "동일 프로그램·track", status: "CONFIRMED", detail: "국내 부동산 선순위 대출 track", evidenceDocumentIds: ["doc-notice"] },
    { code: "FOLLOW_UP_ACTION", label: "후속 입찰·집행", status: "SUPPORTED", detail: "기사상 선정 보도", evidenceDocumentIds: ["doc-news"] },
    { code: "DEPLOYMENT_MATCH", label: "vehicle·deal 연결", status: "MISSING", detail: "실제 집행 연결 미확인", evidenceDocumentIds: [] },
    { code: "MANAGER_MATCH", label: "집행 운용사", status: "SUPPORTED", detail: "캡스톤자산운용 식별", evidenceDocumentIds: ["doc-news"] },
    { code: "DECISION", label: "선정 판단", status: "MISSING", detail: "공식 결과 또는 집행 근거 필요", evidenceDocumentIds: ["doc-news"] },
  ],
  evidence: [
    { documentId: "doc-notice", title: "국내 부동산 선순위 대출펀드 위탁운용사 선정 공고", documentType: "BID_NOTICE", publishedAt: "2024-02-13", publisher: "건설근로자공제회", href: "https://example.com/notice", relationBasis: "CANONICAL_EVENT", role: "MANDATE_SOURCE", roleLabel: "기관 공고·프로그램" },
    { documentId: "doc-news", title: "국내 부동산 선순위 대출펀드 위탁운용사 선정", documentType: "ARTICLE", publishedAt: "2024-04-29", publisher: "테스트뉴스", href: "https://example.com/news", relationBasis: "SOURCE_CLAIM", role: "REPORTED_SELECTION", roleLabel: "기사상 선정 보도" },
  ],
  missingChecks: ["기관자금→vehicle·deal 집행 연결", "기관 공식 선정 결과"],
};

const response: InstitutionalCapitalResponse = {
  items: [{
    mandateId: "mandate-cw-2024",
    mandateName: "2024 국내 부동산 선순위 대출펀드 위탁운용사 선정",
    lpName: "건설근로자공제회",
    status: "UNKNOWN",
    scope: "DOMESTIC",
    announcedAt: "2024-02-13",
    selectedAt: null,
    evidenceStatus: "SOURCE_CLAIM",
    trackCount: 1,
    selectionCount: 0,
    amountCount: 2,
    guidelineCount: 3,
    deploymentCount: 0,
    officialSelectionCount: 0,
    inferredSelectionCount: 0,
    bidParticipationCount: 0,
    reviewRequiredCount: 1,
    tracks: [{ trackId: "track-1", code: "DOMESTIC_SENIOR_REAL_ESTATE_DEBT", name: "국내 부동산 선순위 대출", evidenceStatus: "SOURCE_CLAIM", guidelines: [] }],
    amounts: [],
    selections: [],
    deployments: [],
    assessments: [assessment],
    documents: [assessment.evidence[0]],
  }],
  coverage: {
    mandates: 19,
    selections: 5,
    amounts: 24,
    deployments: 0,
    officialSelections: 5,
    inferredSelections: 0,
    bidParticipations: 0,
    reviewRequired: 6,
  },
  generatedAt: "2026-08-25T00:00:00Z",
  database: "turso-libsql",
};

afterEach(() => vi.restoreAllMocks());

describe("InstitutionalCapitalWorkspace", () => {
  it("separates official, inferred, bid, review, and deployment counts", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    render(<InstitutionalCapitalWorkspace />);

    const coverage = await screen.findByRole("region", { name: "기관자금 근거 현황" });
    expect(within(coverage).getByText("Mandate").nextSibling).toHaveTextContent("19");
    expect(within(coverage).getByText("공식 선정").nextSibling).toHaveTextContent("5");
    expect(within(coverage).getByText("집행 기반 유추").nextSibling).toHaveTextContent("0");
    expect(within(coverage).getByText("입찰 참여").nextSibling).toHaveTextContent("0");
    expect(within(coverage).getByText("검토 필요").nextSibling).toHaveTextContent("6");
    expect(within(coverage).getByText("확인된 집행").nextSibling).toHaveTextContent("0");
    expect(screen.getByText("입찰 참여만으로는 선정이 아닙니다.")).toBeInTheDocument();
  });

  it("shows the six-step reasoning chain and source roles for a reported manager", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    render(<InstitutionalCapitalWorkspace />);
    const mandateHeading = await screen.findByRole("heading", { name: response.items[0].mandateName });
    const mandateDetails = mandateHeading.closest("details");
    const mandateSummary = mandateHeading.closest("summary");
    expect(mandateDetails).not.toBeNull();
    expect(mandateSummary).not.toBeNull();
    expect(within(mandateSummary!).getByText("캡스톤자산운용")).toBeInTheDocument();
    expect(within(mandateSummary!).getByText(assessment.rationale)).toBeInTheDocument();

    fireEvent.click(mandateSummary!);
    expect(mandateDetails).toHaveAttribute("open");
    const managerName = within(mandateDetails!).getByText("캡스톤자산운용", { selector: ".assessment-title strong" });
    const assessmentDetails = managerName.closest("details");
    const assessmentSummary = managerName.closest("summary");
    expect(assessmentDetails).not.toBeNull();
    expect(assessmentSummary).not.toBeNull();

    fireEvent.click(assessmentSummary!);
    expect(assessmentDetails).toHaveAttribute("open");
    await waitFor(() => expect(screen.getByRole("list", { name: "캡스톤자산운용 선정 판단 과정" })).toBeInTheDocument());
    expect(screen.getByText("기관·자금 출처")).toBeInTheDocument();
    expect(screen.getByText("동일 프로그램·track")).toBeInTheDocument();
    expect(screen.getByText("후속 입찰·집행")).toBeInTheDocument();
    expect(screen.getByText("vehicle·deal 연결")).toBeInTheDocument();
    expect(screen.getByText("집행 운용사")).toBeInTheDocument();
    expect(screen.getByText("선정 판단")).toBeInTheDocument();
    expect(screen.getByText("보도 금액").nextSibling).toHaveTextContent("500억원");
    expect(screen.getByText("판단 근거").nextSibling).toHaveTextContent("충족 4/6");
    const evidenceLink = screen.getAllByRole("link", { name: "기관 공고·프로그램" })[0];
    expect(evidenceLink).toHaveAttribute("href", "#assessment-evidence-claim-cw-2024-capstone-doc-notice");
    expect(document.getElementById("assessment-evidence-claim-cw-2024-capstone-doc-notice")).toBeInTheDocument();
    expect(screen.getAllByText("기사상 선정 보도").length).toBeGreaterThan(0);
    expect(screen.getByText(/기관자금→vehicle·deal 집행 연결/)).toBeInTheDocument();
  });
});
