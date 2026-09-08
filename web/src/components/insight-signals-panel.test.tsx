import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { InsightSignalsPanel } from "@/components/insight-signals-panel";

const signal = (status: "APPROVED" | "UNREVIEWED", id: string) => ({ signalId: id, signalType: "KEYWORD_BURST", signalDate: "2026-08-20", title: `${id} 언급 급상승`, summary: "발행일 기준 고유 문서 8건", reviewStatus: status, severity: "HIGH", scores: { strength: .8, evidence: .4, sourceDiversity: .67, confidence: .65 }, syndicationDedupeStatus: "PARTIAL", evidence: [{ targetKind: "DOCUMENT", targetId: `doc-${id}`, documentId: `doc-${id}`, documentVersionId: `ver-${id}`, title: `${id} 근거 문서`, sourceName: "공식 출처", publishedAt: "2026-08-20T00:00:00Z", canonicalUrl: "https://example.com", role: "TRIGGER", rank: 1 }] });
const payload = { generatedAt: "2026-08-22T00:00:00Z", algorithmVersion: "KEYWORD_BURST_SIGNAL_V1", statusCounts: [{ status: "APPROVED", count: 1 }, { status: "UNREVIEWED", count: 1 }], signals: [signal("APPROVED", "승인"), signal("UNREVIEWED", "미검토")] };

afterEach(() => vi.unstubAllGlobals());
describe("InsightSignalsPanel", () => {
  it("separates approved and review-needed signals and opens evidence", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => payload }));
    const open = vi.fn(); render(<InsightSignalsPanel onOpenDocument={open}/>);
    expect(await screen.findByText("검토 완료 신호")).toBeInTheDocument();
    expect(screen.getByText("검토 필요 신호")).toBeInTheDocument();
    expect(screen.getAllByText(/부분 중복제거/)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: /승인 근거 문서/ }));
    expect(open).toHaveBeenCalledWith("doc-승인", "승인 근거 문서");
  });
});
