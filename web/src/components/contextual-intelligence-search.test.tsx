import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ContextualIntelligenceSearch } from "@/components/contextual-intelligence-search";

afterEach(() => vi.restoreAllMocks());

describe("ContextualIntelligenceSearch", () => {
  it("loads approved data initially, auto-loads a selected lane, and keeps filter edits explicit", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ request: {}, total: 0, facets: {}, results: [] }),
    } as Response);
    render(<ContextualIntelligenceSearch onOpenEvent={vi.fn()} onOpenDocument={vi.fn()} />);

    expect(screen.getByRole("button", { name: /승인 정보/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("승인된 사실·사건만 기본 조회합니다.")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("mode=APPROVED");

    fireEvent.change(screen.getByLabelText("검색어"), { target: { value: "서울" } });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /검토 후보/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("mode=CANDIDATE");
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("q=%EC%84%9C%EC%9A%B8");
    expect(screen.getByText("자동 추출 후보이며 승인 정보가 아닙니다.")).toBeInTheDocument();
  });

  it("shows evidence and why-match fields", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        request: {}, total: 1, facets: {}, results: [{
          id: "result-1", mode: "APPROVED", sourceRecordKind: "CANONICAL_EVENT",
          sourceRecordId: "event-1", title: "운용사 선정", summary: "최종 선정",
          eventDomain: "MANAGER_SELECTION", eventType: "MANAGER_SELECTION",
          stageCode: "SELECTED", processType: "RFP", actionCode: "SELECT_MANAGER",
          eventDate: "2026-09-01", temporalBasis: "EVENT_DATE",
          participantRoles: ["APPOINTING_ENTITY"], participantEntityIds: ["org-1"],
          assetIds: [], regionIds: [], industryCodes: [], impactDirections: [],
          sourceGrade: "MULTI_SOURCE_CORROBORATED", confidence: 1,
          reviewStatus: "APPROVED", evidenceText: "국민연금이 운용사를 최종 선정했다.",
          ruleVersion: "contextual-rules-v1", modelVersion: "weighted-context-v1",
          metadata: { documentId: "doc-1" },
        }],
      }),
    } as Response);
    render(<ContextualIntelligenceSearch onOpenEvent={vi.fn()} onOpenDocument={vi.fn()} />);
    expect(await screen.findByText("국민연금이 운용사를 최종 선정했다.")).toBeInTheDocument();
    expect(screen.getByText(/매칭 근거/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "이벤트 열기" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "근거 문서" })).toBeInTheDocument();
  });
});
