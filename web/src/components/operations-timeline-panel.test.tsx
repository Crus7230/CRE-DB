import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { OperationsTimelinePanel } from "@/components/operations-timeline-panel";

const timeline = {
  generatedAt: "2026-08-22T00:00:00Z",
  windowDays: 90,
  publicationKnownCount: 1,
  publicationUnknownCount: 2,
  archivedDocumentExcludedCount: 3,
  series: [
    { date: "2026-08-20", publicationCount: 1, eventCount: 0, ingestionCount: 5 },
    { date: "2026-08-21", publicationCount: 2, eventCount: 1, ingestionCount: 20 },
  ],
};

afterEach(() => vi.restoreAllMocks());

describe("OperationsTimelinePanel", () => {
  it("labels three clocks and warns that ingestion spikes are not market spikes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(timeline), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<OperationsTimelinePanel />);
    expect(await screen.findByText("발행일 기준")).toBeInTheDocument();
    expect(screen.getByText("사건일 기준")).toBeInTheDocument();
    expect(screen.getByText("적재일 기준")).toBeInTheDocument();
    expect(screen.getByText(/적재 급증은 시장 급증이 아닙니다/)).toBeInTheDocument();
    expect(screen.getByText("발행일 미상 2건")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "90일 시계열 차트" })).toBeInTheDocument();
  });
});
