import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DailyArticleWorkspace } from "@/components/daily-article-workspace";

const article = (index: number, topics: unknown[] = []) => ({
  id: `doc-${String(index).padStart(2, "0")}`,
  title: `시장 기사 ${index}`,
  publisher: "테스트경제",
  publishedAt: "2026-08-24T12:00:00Z",
  collectedAt: "2026-08-24T23:30:00Z",
  summary: null,
  summaryMode: "NONE",
  summaryGeneratedAt: null,
  href: null,
  topics,
});

const dailyResponse = {
  selectedDate: "2026-08-24",
  latestAvailableDate: "2026-08-24",
  lastCollectedAt: "2026-08-24T23:30:00Z",
  generatedAt: "2026-08-24T23:31:00Z",
  total: 35,
  returned: 35,
  articles: Array.from({ length: 35 }, (_, index) => article(index + 1)),
};

const jsonResponse = (value: unknown) => new Response(JSON.stringify(value), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

afterEach(() => vi.restoreAllMocks());

describe("DailyArticleWorkspace", () => {
  it("opens on the latest available CRE article date and then requests explicit dates", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(dailyResponse));
    render(<DailyArticleWorkspace onOpenArticle={vi.fn()}/>);

    await screen.findByText("시장 기사 1");
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/articles/daily", expect.anything());
    expect(screen.getByLabelText("기사 게시일", { selector: "input" })).toHaveValue("2026-08-24");

    await user.click(screen.getByRole("button", { name: "1일 전으로 이동" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/articles/daily?date=2026-08-23", expect.anything()));
  });

  it("renders articles in small batches and expands on demand", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(dailyResponse));
    render(<DailyArticleWorkspace onOpenArticle={vi.fn()}/>);

    expect(await screen.findByText("시장 기사 30")).toBeInTheDocument();
    expect(screen.queryByText("시장 기사 31")).not.toBeInTheDocument();
    expect(screen.getByText("30 / 35건")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "기사 5건 더 보기" }));
    expect(await screen.findByText("시장 기사 35")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /기사 .* 더 보기/ })).not.toBeInTheDocument();
  });

  it("groups only governed article classifications and keeps articles time-ordered", async () => {
    const user = userEvent.setup();
    const categorized = {
      ...dailyResponse,
      total: 3,
      returned: 3,
      articles: [
        { ...article(1, [{ key: "SALE", label: "broken-label", status: "CANDIDATE", provenance: "PENDING_CLASSIFICATION" }]), title: "가장 최신 매각 기사", publishedAt: "2026-08-24T12:00:00Z" },
        { ...article(2, [{ key: "PERMIT", label: "broken-label", status: "CONFIRMED", provenance: "APPROVED_CLASSIFICATION" }]), title: "인허가 기사", publishedAt: "2026-08-24T11:00:00Z" },
        { ...article(3), title: "분류 전 기사", publishedAt: "2026-08-24T10:00:00Z" },
      ],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(categorized));
    render(<DailyArticleWorkspace onOpenArticle={vi.fn()}/>);

    const filters = await screen.findByRole("navigation", { name: "기사 대표 주제" });
    expect(within(filters).getByRole("button", { name: /전체.*3/ })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: /거래.*1/ })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: /개발·공급.*1/ })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: /분류 대기.*1/ })).toBeInTheDocument();
    expect(screen.getByText("매각")).toBeInTheDocument();
    expect(screen.getByText("인허가")).toBeInTheDocument();
    expect(screen.queryByText("broken-label")).not.toBeInTheDocument();

    const headings = screen.getAllByRole("heading", { level: 2 }).map((item) => item.textContent);
    expect(headings.slice(-3)).toEqual(["가장 최신 매각 기사", "인허가 기사", "분류 전 기사"]);

    await user.click(within(filters).getByRole("button", { name: /거래.*1/ }));
    expect(screen.getByText("가장 최신 매각 기사")).toBeInTheDocument();
    expect(screen.queryByText("인허가 기사")).not.toBeInTheDocument();
    expect(screen.getByText("자동분류")).toBeInTheDocument();
  });

  it("uses one primary topic per article and never promotes a collection query", async () => {
    const governed = {
      ...dailyResponse,
      total: 2,
      returned: 2,
      articles: [
        {
          ...article(1, [
            { key: "SALE", label: "매각", status: "CONFIRMED", provenance: "APPROVED_CLASSIFICATION" },
            { key: "PF", label: "PF", status: "CANDIDATE", provenance: "PENDING_CLASSIFICATION" },
          ]),
          title: "서울 오피스 매각",
        },
        {
          ...article(2, [
            { key: "DATA_CENTER", label: "데이터센터", status: "CANDIDATE", provenance: "COLLECTION_QUERY" },
          ]),
          title: "검색어로 수집된 기사",
        },
      ],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(governed));
    render(<DailyArticleWorkspace onOpenArticle={vi.fn()}/>);

    const filters = await screen.findByRole("navigation", { name: "기사 대표 주제" });
    expect(within(filters).getByRole("button", { name: /전체.*2/ })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: /거래.*1/ })).toBeInTheDocument();
    expect(within(filters).queryByRole("button", { name: /자본·금융/ })).not.toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: /분류 대기.*1/ })).toBeInTheDocument();
    expect(screen.getByText("검토완료")).toBeInTheDocument();
    expect(screen.queryByText("데이터센터")).not.toBeInTheDocument();
  });

  it("filters within loaded rows, reveals summaries, and trims only an exact publisher suffix", async () => {
    const user = userEvent.setup();
    const onOpenArticle = vi.fn();
    const searchable = {
      ...dailyResponse,
      total: 2,
      returned: 2,
      articles: [
        { ...article(1), title: "서울 오피스 거래 - 테스트경제", summary: "도심 거래 요약" },
        { ...article(2), title: "물류센터 공급", summary: "수도권 공급 요약" },
      ],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(searchable));
    render(<DailyArticleWorkspace onOpenArticle={onOpenArticle}/>);

    expect(await screen.findByRole("heading", { name: "서울 오피스 거래" })).toBeInTheDocument();
    expect(screen.queryByText("도심 거래 요약")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /요약/ }));
    expect(screen.getByText("도심 거래 요약")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "불러온 기사 검색" }), "물류");
    expect(screen.queryByRole("heading", { name: "서울 오피스 거래" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "물류센터 공급" })).toBeInTheDocument();

    await user.clear(screen.getByRole("searchbox", { name: "불러온 기사 검색" }));
    await user.click(screen.getByRole("heading", { name: "서울 오피스 거래" }).closest("button")!);
    expect(onOpenArticle).toHaveBeenCalledWith("doc-01", "서울 오피스 거래 - 테스트경제");
  });
});
