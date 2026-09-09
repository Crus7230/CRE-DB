import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ArticleEvidenceSearch } from "@/components/article-evidence-search";

const payload = {
  datasetVersion: "dataset-v1",
  query: "매각",
  generatedAt: "2026-09-09T00:00:00Z",
  filters: { from: null, to: null, topic: null },
  returned: 1,
  truncated: false,
  maxResults: 8,
  items: [{
    documentId: "doc-1",
    title: "서울 오피스 매각",
    publisher: "부동산뉴스",
    publishedAt: "2026-09-08T12:00:00+09:00",
    href: "https://example.com/article/1",
    evidenceText: "서울 오피스 매각 절차가 시작됐다.",
    score: 0.8,
  }],
};

afterEach(() => vi.unstubAllGlobals());

describe("ArticleEvidenceSearch", () => {
  it("stays collapsed and makes no request until the user submits a query", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ArticleEvidenceSearch onOpenArticle={vi.fn()}/>);

    expect(fetchMock).not.toHaveBeenCalled();
    const summary = screen.getByText("근거 검색").closest("summary");
    expect(summary).not.toBeNull();
    expect(summary?.parentElement).not.toHaveAttribute("open");

    await user.click(summary!);
    expect(summary?.parentElement).toHaveAttribute("open");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the submitted query, dated source excerpt, and original links without AI claims or a raw score", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const openArticle = vi.fn();
    const user = userEvent.setup();
    render(<ArticleEvidenceSearch onOpenArticle={openArticle}/>);

    await user.click(screen.getByText("근거 검색").closest("summary")!);
    await user.type(screen.getByLabelText("기사 검색어"), "매각");
    await user.click(screen.getByRole("button", { name: "근거 찾기" }));

    expect(await screen.findByText(/“매각” 관련 근거 1건 · 최대 8건/u)).toBeInTheDocument();
    expect(screen.getByText("기사 발췌")).toBeInTheDocument();
    expect(screen.getByText("서울 오피스 매각 절차가 시작됐다.")).toBeInTheDocument();
    expect(screen.getByText("부동산뉴스")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /원문 열기/u })).toHaveAttribute("href", "https://example.com/article/1");
    expect(screen.queryByText(/0\.8|80%|AI 답변|RAG/u)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "기사 상세" }));
    expect(openArticle).toHaveBeenCalledWith("doc-1", "서울 오피스 매각");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({ q: "매각", topK: 8 });
  });

  it("does not present an empty retrieval as a generated answer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      ...payload,
      returned: 0,
      items: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));
    const user = userEvent.setup();
    render(<ArticleEvidenceSearch onOpenArticle={vi.fn()}/>);
    await user.click(screen.getByText("근거 검색").closest("summary")!);
    await user.type(screen.getByLabelText("기사 검색어"), "매각");
    await user.click(screen.getByRole("button", { name: "근거 찾기" }));

    expect(await screen.findByText("일치하는 근거가 없습니다.")).toBeInTheDocument();
    expect(screen.queryByText(/답변|요약 생성/u)).not.toBeInTheDocument();
  });

  it("collapses a title-only match instead of repeating the headline as an excerpt", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      ...payload,
      items: [{
        ...payload.items[0],
        title: "일본 JDI, 오피스 매각 관심 - 지디넷코리아",
        evidenceText: "  일본 JDI,  오피스 매각 관심 지디넷코리아  ",
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));
    const user = userEvent.setup();
    render(<ArticleEvidenceSearch onOpenArticle={vi.fn()}/>);
    await user.click(screen.getByText("근거 검색").closest("summary")!);
    await user.type(screen.getByLabelText("기사 검색어"), "매각");
    await user.click(screen.getByRole("button", { name: "근거 찾기" }));

    expect(await screen.findByText("제목 일치")).toBeInTheDocument();
    expect(screen.queryByText("기사 발췌")).not.toBeInTheDocument();
    expect(screen.getAllByText("일본 JDI, 오피스 매각 관심 - 지디넷코리아")).toHaveLength(1);
  });
});
