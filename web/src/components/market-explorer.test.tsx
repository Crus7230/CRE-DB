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
  groups: [{ group: "EVENT_CATEGORY", label: "이벤트 카테고리", kind: "EVENT", items: [{ key: "PF", label: "PF", itemCount: 645, canonicalCount: 0 }] }],
  generatedAt: "2026-08-18T03:00:00Z", elapsedMs: 12, database: "supabase-postgresql",
};

const detailResponse = { kind: "EVENT", id: "evt-1", title: "용인 데이터센터 본PF 약정", subtitle: "PF · MAIN_PF_COMMITTED", status: "ACTIVE", overview: [{ label: "검증 수준", value: "VERIFIED" }], assets: [], events: [], organizations: [], documents: [] };

afterEach(() => vi.restoreAllMocks());

describe("MarketExplorer", () => {
  it("keeps category navigation separate from filters and opens an inspection drawer", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const payload = url.startsWith("/api/index") ? indexResponse : url.startsWith("/api/entities") ? detailResponse : response;
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    });

    render(<MarketExplorer />);
    expect(await screen.findByRole("heading", { name: "시장 카테고리로 찾고, 근거문서로 검증" })).toBeInTheDocument();
    expect(screen.getByRole("complementary")).toHaveTextContent("CATEGORY");
    expect(screen.getByRole("region", { name: "상세 필터" })).toHaveTextContent("FILTER");
    expect(await screen.findByText("용인 데이터센터 본PF 약정")).toBeInTheDocument();

    const input = screen.getByRole("textbox", { name: "통합 검색" });
    await user.type(input, "데이터센터");
    await user.click(screen.getByRole("button", { name: "검색" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("q=%EB%8D%B0%EC%9D%B4%ED%84%B0%EC%84%BC%ED%84%B0"), expect.anything()));

    await user.click(screen.getByRole("button", { name: /시장 이벤트/ }));
    await user.click(await screen.findByRole("button", { name: /PF.*645/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("category=PF"), expect.anything()));

    await user.click(screen.getByRole("button", { name: /용인 데이터센터 본PF 약정/ }));
    expect(await screen.findByRole("dialog", { name: "이벤트 상세" })).toBeInTheDocument();
    expect(await screen.findByText("VERIFIED")).toBeInTheDocument();
  });
});
