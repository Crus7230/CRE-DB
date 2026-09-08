import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CompanyWorkspace } from "@/components/company-workspace";

const listResponse = {
  request: { view: "OVERALL", industry: "", q: "", limit: 50 },
  snapshotDate: "2026-07-31",
  industries: [],
  coverage: { verifiedOccupancies: 0, companiesWithLocationEvidence: 0, managedLocationDocuments: 5, signalNote: "" },
  items: [],
};

const hmmEvidence = {
  documentId: "doc-hmm",
  evidenceType: "RELOCATION",
  wordingStage: "IN_PROGRESS_WORDING",
  evidenceLabel: "이전 관련 문구",
  title: "HMM, 부산 본사 이전이 우선",
  matchedPhrase: "본사 이전",
  evidenceExcerpt: "HMM은 부산 본사 이전을 우선 추진한다고 밝혔습니다.",
  evidenceReason: "과거 자동분류 문서에서 회사명과 ‘본사 이전’ 표현이 같은 문맥에 등장 · 행위주체 검토 전",
  sourceCategory: "LEASE",
  classificationBasis: "LEGACY_DISCOVERY",
  classificationReviewStatus: null,
  publishedAt: "2026-06-08T07:00:00Z",
  publisher: "테스트뉴스",
  href: "https://example.com/hmm",
  mentionStatus: "EXTRACTED",
  confidence: 0.4,
};

const tenantListResponse = {
  ...listResponse,
  request: { view: "TENANT_SIGNALS", industry: "", q: "", limit: 100 },
  coverage: { verifiedOccupancies: 0, companiesWithLocationEvidence: 1, managedLocationDocuments: 5, signalNote: "" },
  items: [{
    organizationId: "org-1",
    name: "HMM",
    stockCode: "011200",
    industry: "해상 운송업",
    marketCap: "19000000000000",
    overallRank: 35,
    industryRank: 1,
    confirmedOccupancyCount: 0,
    canonicalEventCount: 0,
    relatedAssetCount: 0,
    locationEvidenceDocumentCount: 15,
    locationEvidencePublisherCount: 14,
    primaryLocationEvidence: hmmEvidence,
  }],
};

const hmmDetailResponse = {
  organization: {
    organizationId: "org-1", name: "HMM", organizationType: "COMPANY", stockCode: "011200",
    industry: "해상 운송업", marketCap: "19000000000000", overallRank: 35,
  },
  counts: { events: 0, assets: 0, documents: 15, occupancies: 0, locationEvidence: 1 },
  events: [], assets: [], documents: [], occupancies: [], locationEvidence: [hmmEvidence],
  generatedAt: "2026-08-25T00:00:00Z",
  database: "turso-libsql",
};

afterEach(() => vi.restoreAllMocks());

describe("CompanyWorkspace", () => {
  it("debounces company typing into one request", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(listResponse), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    render(<CompanyWorkspace />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const input = screen.getByPlaceholderText("회사명 또는 종목코드");
    fireEvent.change(input, { target: { value: "삼" } });
    fireEvent.change(input, { target: { value: "삼성" } });
    fireEvent.change(input, { target: { value: "삼성전자" } });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("q=%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90"),
      expect.anything(),
    ), { timeout: 1_000 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([inputValue]) => String(inputValue).includes("q=%EC%82%BC&"))).toBe(false);
  });

  it("explains location evidence instead of presenting document count as relocation signals", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const body = url.includes("/api/companies/org-1")
        ? hmmDetailResponse
        : url.includes("view=TENANT_SIGNALS") ? tenantListResponse : listResponse;
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    render(<CompanyWorkspace />);
    await waitFor(() => expect(screen.getByText("입지 관련 근거")).toBeInTheDocument());

    fireEvent.click(screen.getByText("입지 관련 근거"));
    await waitFor(() => expect(screen.getByText("HMM")).toBeInTheDocument());

    expect(screen.getByText("이전 관련 문구")).toBeInTheDocument();
    expect(screen.getByText("추진 표현")).toBeInTheDocument();
    expect(screen.getByText("자동 추출·검토 전")).toBeInTheDocument();
    expect(screen.getByText("감지 표현 ‘본사 이전’")).toBeInTheDocument();
    expect(screen.getByText("15건 보기")).toBeInTheDocument();
    expect(screen.getByText("14개 매체")).toBeInTheDocument();
    expect(screen.queryByText("이전 신호")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("15건 보기"));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "회사 360 상세" })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("왜 입지 관련 근거로 잡혔나")).toBeInTheDocument());
    expect(screen.getByText("승인 점유와 별도")).toBeInTheDocument();
    expect(screen.getByText("관련 문서 시계열")).toBeInTheDocument();
    expect(screen.getByText("최근 근거순 · 동일 사건의 반복 보도 포함")).toBeInTheDocument();
    expect(screen.getByText("HMM은 부산 본사 이전을 우선 추진한다고 밝혔습니다.")).toBeInTheDocument();
    expect(screen.getAllByText(/행위주체 검토 전/).length).toBeGreaterThan(0);
  });
});
