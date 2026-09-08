import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DocumentDetailDrawer } from "@/components/document-detail-drawer";
import type { DocumentDetail } from "@/lib/server/document-intelligence";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.style.overflow = "";
});

function DrawerHarness() {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" onClick={() => setOpen(true)}>기사 상세 열기</button>
    {open && <DocumentDetailDrawer documentId="doc-1" fallbackTitle="근거 문서" onClose={() => setOpen(false)}/>}
  </>;
}

const articleDetail = {
  id: "doc-1",
  title: "KCGI, 매각 추진 - 서울경제",
  publisher: "서울경제",
  documentType: "ARTICLE",
  sourceUrl: "https://example.com/article",
  author: null,
  publishedAt: "2026-08-20T09:30:00+09:00",
  collectedAt: "2026-08-20T09:31:00+09:00",
  rightsStatus: "EXCERPT_ALLOWED",
  contentMode: "SNIPPET",
  summaryMode: "EVENT_EXTRACTION",
  summaryGeneratedAt: null,
  summaryPipeline: null,
  summary: "KCGI 매각 추진!!! — 서울경제",
  eventExtraction: null,
  safeExcerpt: null,
  snippet: "KCGI, 매각 추진 - 서울경제",
  storedText: null,
  eventSignals: [
    { category: "SALE", categoryLabel: "매각", title: "KCGI, 매각 추진 - 서울경제", summary: "KCGI 매각 추진 — 서울경제", stage: null, eventDate: null, confidence: null, status: "CANDIDATE" },
    { category: "FINANCING", categoryLabel: "금융", title: "대출 조건 협의", summary: null, stage: "협의", eventDate: "2026-08-18", confidence: 0.82, status: "REVIEW_READY" },
  ],
  keywords: [],
  relatedEntities: [],
  classifications: [],
  transaction: null,
} satisfies DocumentDetail;

describe("DocumentDetailDrawer", () => {
  it("traps keyboard focus, restores the opener on Escape, and restores body scrolling", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => undefined));
    render(<DrawerHarness/>);

    const opener = screen.getByRole("button", { name: "기사 상세 열기" });
    await user.click(opener);
    const close = screen.getByRole("button", { name: "상세 닫기" });

    expect(close).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "문서 상세" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  it("suppresses title-only summaries and translates candidate, review, excerpt, and rights labels", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => articleDetail } as Response);
    render(<DocumentDetailDrawer documentId="doc-1" fallbackTitle={articleDetail.title} onClose={vi.fn()}/>);

    expect(await screen.findByRole("heading", { name: "KCGI, 매각 추진" })).toBeInTheDocument();
    expect(screen.getByText("본문 요약 없음 · 원문에서 확인")).toBeInTheDocument();
    expect(screen.queryByText(articleDetail.summary)).not.toBeInTheDocument();
    expect(screen.getByText("자동 추출·검토 전")).toBeInTheDocument();
    expect(screen.getByText("검토 대기 · 신뢰도 82%")).toBeInTheDocument();
    expect(screen.getByText("협의 · 2026-08-18")).toBeInTheDocument();
    expect(screen.getByText("출처 발췌")).toBeInTheDocument();
    expect(screen.getByText(/권리상태: 제한 발췌 허용/)).toBeInTheDocument();
    expect(screen.getAllByText(/서울경제/)).toHaveLength(1);
    expect(screen.getByText("게시 2026-08-20")).toBeInTheDocument();
  });

  it("renders timestamp fields in KST without shifting a transaction date-only value", async () => {
    const timestampDetail: DocumentDetail = {
      ...articleDetail,
      title: "자정 전 게시 기사",
      publishedAt: "2026-09-07T23:44:00Z",
      summaryMode: "MODEL",
      summary: "게시 시각 경계를 확인하는 요약입니다.",
      summaryGeneratedAt: "2026-09-07T23:50:00Z",
      summaryPipeline: "summary-v1",
      eventSignals: [],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => timestampDetail } as Response);
    const { unmount } = render(<DocumentDetailDrawer documentId="doc-kst" fallbackTitle={timestampDetail.title} onClose={vi.fn()}/>);

    expect(await screen.findByText("게시 2026-09-08")).toHaveAttribute("datetime", timestampDetail.publishedAt);
    expect(screen.getByText("생성 2026-09-08 08:50 KST · summary-v1")).toBeInTheDocument();
    unmount();

    const transactionDetail: DocumentDetail = {
      ...articleDetail,
      id: "tx-1",
      documentType: "API_RECORD",
      publishedAt: "2026-09-07T23:44:00Z",
      summaryMode: "NONE",
      summary: null,
      transaction: {
        dealDate: "2026-09-07", dealAmount: "10000", buildingAr: "3400", plottageAr: null,
        buildingUse: "업무시설", buildingType: null, buildYear: null, floor: null,
        region: "서울", address: "서울 테스트", landUse: null, dealingType: null,
        buyerType: null, sellerType: null, shareType: null, cancelDate: null,
        duplicateOccurrence: 1, screeningBand: "KEEP",
      },
    };
    vi.mocked(globalThis.fetch).mockResolvedValue({ ok: true, json: async () => transactionDetail } as Response);
    render(<DocumentDetailDrawer documentId="tx-1" fallbackTitle={transactionDetail.title} onClose={vi.fn()}/>);

    expect(await screen.findByText("2026-09-07", { selector: ".document-actions time" })).toHaveAttribute("datetime", "2026-09-07");
    expect(screen.queryByText("게시 2026-09-08")).not.toBeInTheDocument();
  });
});
