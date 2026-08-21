import { afterEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { MarketExplorer } from "@/components/market-explorer";

const response = {
  request: { q: "", kind: "EVENT", category: "", from: "2026-01-01", to: "2026-07-31", page: 1, pageSize: 50 },
  results: [{
    kind: "EVENT", id: "evt-1", title: "용인 데이터센터 본PF 약정",
    subtitle: "PF · MAIN_PF_COMMITTED", summary: "6,200억원 대주단 약정",
    date: "2026-07-13", status: "ACTIVE", confidence: 0.91,
    source: "canonical event", href: null, category: "PF", categoryLabel: "PF",
    metadata: { assets: "용인 남사 데이터센터", participants: "대주단" },
  }],
  facets: { EVENT: 28, ASSET: 16, ORGANIZATION: 70, DOCUMENT: 54985, LP_MANDATE: 12, SALE_PROCESS: 16 },
  total: 28, elapsedMs: 184, generatedAt: "2026-08-18T03:00:00Z", database: "supabase-postgresql",
};

const indexResponse = {
  groups: [
    { group: "EVENT_CATEGORY", label: "이벤트 카테고리", kind: "EVENT", items: [{ key: "PF", label: "PF", itemCount: 645, canonicalCount: 0 }] },
    { group: "DOCUMENT_TYPE", label: "근거 목적", kind: "DOCUMENT", items: [
      { key: "TRANSACTION_EVIDENCE", label: "거래·가격 근거", itemCount: 47264 },
      { key: "CORPORATE_EVIDENCE", label: "기업·사업 근거", itemCount: 40 },
      { key: "MARKET_EVIDENCE", label: "시장동향 근거", itemCount: 10329 },
      { key: "PROCESS_EVIDENCE", label: "절차·공고 근거", itemCount: 16 },
    ] },
  ],
  generatedAt: "2026-08-18T03:00:00Z", elapsedMs: 12, database: "supabase-postgresql",
};

const detailResponse = { kind: "EVENT", id: "evt-1", title: "용인 데이터센터 본PF 약정", subtitle: "PF · MAIN_PF_COMMITTED", status: "ACTIVE", overview: [{ label: "검증 수준", value: "VERIFIED" }], assets: [], events: [], organizations: [], documents: [] };

const dailyResponse = {
  selectedDate: "2026-08-19",
  latestAvailableDate: "2026-08-19",
  lastCollectedAt: "2026-08-19T07:30:00Z",
  generatedAt: "2026-08-19T08:00:00Z",
  total: 1,
  articles: [{
    id: "doc-news-1",
    title: "서울 오피스 거래시장 회복 신호",
    publisher: "테스트경제",
    publishedAt: "2026-08-19T01:20:00Z",
    collectedAt: "2026-08-19T07:30:00Z",
    summary: "서울 오피스 거래시장 관련 기사 요약",
    summaryMode: "BODY_EXTRACTIVE",
    summaryGeneratedAt: "2026-08-19T07:31:00Z",
    href: "https://example.com/news-1",
  }],
};

const documentResponse = {
  ...response,
  request: { ...response.request, kind: "DOCUMENT", category: "MARKET_EVIDENCE" },
  results: [{
    kind: "DOCUMENT", id: "doc-news-1", title: "서울 오피스 거래시장 회복 신호",
    subtitle: "테스트경제 · RSS_ITEM", summary: "시장 동향 요약", date: "2026-08-19",
    status: "ACCESSIBLE", confidence: null, source: "테스트경제", href: "https://example.com/news-1",
    category: "RSS_ITEM", categoryLabel: "RSS_ITEM", metadata: { documentType: "RSS_ITEM" },
  }],
  total: 1,
};

afterEach(() => vi.restoreAllMocks());

describe("MarketExplorer", () => {
  it("keeps category navigation separate from filters and opens an inspection drawer", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const payload = url.startsWith("/api/index") ? indexResponse : url.startsWith("/api/articles/daily") ? dailyResponse : url.startsWith("/api/entities") ? detailResponse : response;
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    });

    render(<MarketExplorer />);
    expect(await screen.findByRole("heading", { name: "시장 변화부터 근거까지 한 흐름으로 탐색" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "업무 화면" })).toHaveTextContent("무엇을 할까요?");
    expect(screen.getByRole("complementary")).toHaveTextContent("탐색 기준");
    expect(screen.getByRole("region", { name: "조회 조건" })).toHaveTextContent("조회 조건");
    expect(screen.queryByText("DOCUMENT TYPES")).not.toBeInTheDocument();
    expect(await screen.findByText("용인 데이터센터 본PF 약정")).toBeInTheDocument();

    const input = screen.getByRole("textbox", { name: "통합 검색" });
    await user.type(input, "데이터센터");
    await user.click(screen.getByRole("button", { name: "검색" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("q=%EB%8D%B0%EC%9D%B4%ED%84%B0%EC%84%BC%ED%84%B0"), expect.anything()));

    await user.click(await screen.findByRole("button", { name: /PF.*645/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("category=PF"), expect.anything()));

    await user.click(screen.getByRole("button", { name: /용인 데이터센터 본PF 약정/ }));
    expect(await screen.findByRole("dialog", { name: "이벤트 상세" })).toBeInTheDocument();
    expect(await screen.findByText("VERIFIED")).toBeInTheDocument();
  });

  it("groups documents by evidence purpose instead of exposing source-format codes", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const payload = url.startsWith("/api/index") ? indexResponse : url.includes("kind=DOCUMENT") ? documentResponse : response;
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    });

    render(<MarketExplorer />);
    await user.click(screen.getByRole("button", { name: /근거자료/ }));

    expect(await screen.findByRole("button", { name: /거래·가격 근거/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /기업·사업 근거/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /시장동향 근거/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /절차·공고 근거/ })).toBeInTheDocument();
    expect(screen.queryByText("RSS_ITEM")).not.toBeInTheDocument();
    expect(screen.queryByText("API_RECORD")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /시장동향 근거/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("category=MARKET_EVIDENCE"), expect.anything()));
    expect(await screen.findByText("서울 오피스 거래시장 회복 신호")).toBeInTheDocument();
    expect(screen.getAllByText("시장기사·RSS").length).toBeGreaterThan(0);
    expect(screen.queryByText("RSS_ITEM")).not.toBeInTheDocument();
  });

  it("opens archived compact metadata without requesting retired live detail", async () => {
    const user = userEvent.setup();
    const archivedResponse = {
      ...documentResponse,
      results: [{
        ...documentResponse.results[0],
        id: "doc-archived-1",
        status: "ARCHIVED_LOCAL",
        metadata: {
          archived: true,
          originalStatus: "CRE_CONFIRMED",
          archiveLocator: "sqlite://archive-abc#table=source_documents&pk=doc-archived-1",
          archiveSnapshotSha256: "a".repeat(64),
        },
      }],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const payload = url.startsWith("/api/index") ? indexResponse : url.includes("kind=DOCUMENT") ? archivedResponse : response;
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    });

    render(<MarketExplorer />);
    await user.click(screen.getByRole("button", { name: /근거자료/ }));
    await user.click(await screen.findByRole("button", { name: /서울 오피스 거래시장 회복 신호/ }));

    expect(await screen.findByRole("dialog", { name: "로컬 보관 상세" })).toHaveTextContent("CRE_CONFIRMED");
    expect(screen.getByRole("dialog", { name: "로컬 보관 상세" })).toHaveTextContent("archive-abc");
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith("/api/documents/"))).toBe(false);
  });

  it("opens a separate daily article workspace with publication and collection freshness", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const payload = url.startsWith("/api/articles/daily") ? dailyResponse : url.startsWith("/api/index") ? indexResponse : response;
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    });

    render(<MarketExplorer />);
    await user.click(screen.getByRole("button", { name: /뉴스 모니터/ }));

    expect(await screen.findByRole("heading", { name: "매일 확인하는 부동산 시장기사" })).toBeInTheDocument();
    expect(await screen.findByText("서울 오피스 거래시장 회복 신호")).toBeInTheDocument();
    expect(screen.getByText("최근 수집").parentElement).toHaveTextContent("2026");
    expect(screen.getByText("테스트경제")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/articles/daily?date="), expect.anything()));
  });
});
