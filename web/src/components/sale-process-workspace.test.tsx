import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { SaleProcessWorkspace } from "@/components/sale-process-workspace";
import type { SaleProcessResearchCandidate, SaleProcessResponse } from "@/lib/intelligence-contract";

const g1: SaleProcessResearchCandidate = {
  candidateId: "KR-CRE-2026-G1-SEOUL",
  processCode: "KR-CRE-2026-G1-SEOUL",
  title: "G1서울",
  assetType: "OFFICE",
  method: "COMPETITIVE",
  status: "CLOSED",
  stageCode: "CLOSED",
  evidenceGrade: "B",
  confidence: 0.78,
  roles: { buyer_or_preferred: "미래에셋자산운용" },
  rounds: [{ round_type: "FINAL_BID", date: "2026-01-23", bidders: ["미래에셋자산운용", "퍼시픽자산운용"] }],
  milestones: [{ type: "PREFERRED_BIDDER", date: "2026-02-03" }, { type: "CLOSED", date: "2026-06" }],
  amounts: [{ value_krw: "1523000000000" }],
  financing: [],
  sources: [{ date: "2026-02-03", url: "https://example.com/g1", span: "미래에셋 우협 선정" }],
};

const kTwin: SaleProcessResearchCandidate = {
  ...g1,
  candidateId: "KR-CRE-2026-K-TWIN",
  processCode: "KR-CRE-2026-K-TWIN",
  title: "더케이트윈타워",
  status: "PREFERRED_BIDDER",
  stageCode: "PREFERRED_BIDDER_SELECTED",
  roles: { preferred_bidder: "이지스자산운용" },
  amounts: [{ raw: "1조원 이상" }],
  sources: [{ date: "2026-07-31", url: "https://example.com/k-twin", span: "이지스 우협" }],
};

const response: SaleProcessResponse = {
  items: [],
  candidateProcesses: [g1, kTwin],
  coverage: {
    processes: 16,
    rounds: 4,
    bidders: 2,
    submissions: 1,
    decisions: 1,
    fundingComponents: 0,
    milestones: 3,
    signalYear: 2026,
    candidateCutoffDate: "2026-08-19",
    currentYearProcesses: 0,
    currentYearCandidateProcesses: 14,
    currentYearArticleSignals: 107,
    currentYearPriorityArticleSignals: 33,
    currentYearResolvedStageArticleSignals: 40,
  },
  generatedAt: "2026-08-25T00:00:00Z",
  database: "turso-libsql",
};

afterEach(() => vi.restoreAllMocks());

describe("SaleProcessWorkspace", () => {
  it("shows 2026 curated candidates separately from canonical and article-signal counts", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    render(<SaleProcessWorkspace />);

    const coverage = await screen.findByRole("region", { name: "매각 데이터 현황" });
    expect(within(coverage).getByText("2026 고유 후보").nextSibling).toHaveTextContent("14");
    expect(within(coverage).getByText("올해 정식 절차").nextSibling).toHaveTextContent("0");
    expect(within(coverage).getByText("검토 기사 신호").nextSibling).toHaveTextContent("107");
    expect(screen.getByText("2026.08.19 조사 기준")).toBeInTheDocument();
    expect(screen.getByText("G1서울")).toBeInTheDocument();
    expect(screen.getByText("더케이트윈타워")).toBeInTheDocument();
    expect(screen.getByText(/정식 데이터입니다/)).toHaveTextContent("2026년 정식 절차는 현재 0건입니다.");
  });

  it("filters active candidates and exposes the source-based reasoning", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    render(<SaleProcessWorkspace />);

    const g1Heading = await screen.findByRole("heading", { name: "G1서울" });
    const g1Details = g1Heading.closest("details");
    const g1Summary = g1Heading.closest("summary");
    expect(g1Details).not.toBeNull();
    fireEvent.click(g1Summary!);
    expect(g1Details).toHaveAttribute("open");
    expect(screen.getByText("미래에셋 우협 선정")).toBeInTheDocument();
    expect(within(g1Details!).getByRole("link", { name: /원문/ })).toHaveAttribute("href", "https://example.com/g1");

    fireEvent.click(screen.getByRole("button", { name: "진행 중" }));
    expect(screen.queryByRole("heading", { name: "G1서울" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "더케이트윈타워" })).toBeInTheDocument();
    expect(screen.getByText("1건 표시")).toBeInTheDocument();
  });
});
