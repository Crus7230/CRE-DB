import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MarketExplorer } from "@/components/market-explorer";

vi.mock("@/components/daily-article-workspace", () => ({
  DailyArticleWorkspace: ({ onOpenArticle }: { onOpenArticle: (id: string, title: string) => void }) => <section aria-label="최신기사 목록"><button type="button" onClick={() => onOpenArticle("doc-1", "서울 오피스 매각")}>서울 오피스 매각</button></section>,
}));

vi.mock("@/components/document-detail-drawer", () => ({
  DocumentDetailDrawer: ({ fallbackTitle, onClose }: { fallbackTitle: string; onClose: () => void }) => <section role="dialog" aria-label="기사 상세"><strong>{fallbackTitle}</strong><button type="button" onClick={onClose}>닫기</button></section>,
}));

vi.mock("@/components/quantitative-market-pulse", () => ({
  QuantitativeMarketPulse: () => <section aria-label="거래시장 시계열"><input aria-label="거래 메모"/></section>,
}));

vi.mock("@/components/macro-timeseries-workspace", () => ({
  MacroTimeseriesWorkspace: () => <section aria-label="금리 시계열"><input aria-label="금리 메모"/></section>,
}));

vi.mock("@/components/permit-timeseries-workspace", () => ({
  PermitTimeseriesWorkspace: () => <section aria-label="건축 인허가 시계열"><input aria-label="인허가 메모"/></section>,
}));

describe("MarketExplorer", () => {
  it("exposes exactly two keyboard-operable primary tabs", async () => {
    const user = userEvent.setup();
    render(<MarketExplorer/>);

    const navigation = screen.getByRole("tablist", { name: "주요 화면" });
    const tabs = within(navigation).getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[0]).toHaveAccessibleName(/최신기사/);
    expect(tabs[0]).toHaveAttribute("aria-current", "page");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAccessibleName(/시계열자료/);
    expect(screen.getByRole("region", { name: "최신기사 목록" })).toBeInTheDocument();
    expect(screen.queryByText("브리핑")).not.toBeInTheDocument();
    expect(screen.queryByText("기업·자산")).not.toBeInTheDocument();
    expect(screen.queryByText("데이터 품질")).not.toBeInTheDocument();

    tabs[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(tabs[1]).toHaveFocus();
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  });

  it("lazy-mounts each time-series mode once and preserves it across tab reentry", async () => {
    const user = userEvent.setup();
    render(<MarketExplorer/>);

    expect(document.querySelector('[aria-label="거래시장 시계열"]')).toBeNull();
    expect(document.querySelector('[aria-label="금리 시계열"]')).toBeNull();
    expect(document.querySelector('[aria-label="건축 인허가 시계열"]')).toBeNull();

    await user.click(screen.getByRole("tab", { name: /시계열자료/ }));
    const transaction = screen.getByRole("region", { name: "거래시장 시계열" });
    expect(transaction).toBeInTheDocument();
    expect(document.querySelector('[aria-label="금리 시계열"]')).toBeNull();

    await user.type(screen.getByLabelText("거래 메모"), "유지");
    await user.click(screen.getByRole("tab", { name: /금리·거시/ }));
    const rates = screen.getByRole("region", { name: "금리 시계열" });
    expect(rates).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "거래시장 시계열" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /건축 인허가/ }));
    const permits = screen.getByRole("region", { name: "건축 인허가 시계열" });
    await user.type(screen.getByLabelText("인허가 메모"), "유지");
    expect(permits).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /거래시장/ }));
    expect(screen.getByLabelText("거래 메모")).toHaveValue("유지");
    await user.click(screen.getByRole("tab", { name: /최신기사/ }));
    await user.click(screen.getByRole("tab", { name: /시계열자료/ }));
    expect(screen.getByLabelText("거래 메모")).toHaveValue("유지");
    expect(rates).toBeInTheDocument();
    expect(permits).toBeInTheDocument();
    expect(screen.getByLabelText("인허가 메모")).toHaveValue("유지");
  });

  it("opens an article detail and closes it when the workspace changes", async () => {
    const user = userEvent.setup();
    render(<MarketExplorer/>);

    await user.click(screen.getByRole("button", { name: "서울 오피스 매각" }));
    expect(screen.getByRole("dialog", { name: "기사 상세" })).toHaveTextContent("서울 오피스 매각");
    await user.click(screen.getByRole("tab", { name: /시계열자료/ }));
    expect(screen.queryByRole("dialog", { name: "기사 상세" })).not.toBeInTheDocument();
  });
});
