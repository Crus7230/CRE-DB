import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MacroTimeseriesWorkspace } from "@/components/macro-timeseries-workspace";

const points = (offset = 0) => [
  { month: "2026-06", value: 3 + offset, observationCount: 20, partial: false },
  { month: "2026-07", value: 3.2 + offset, observationCount: 22, partial: false },
  { month: "2026-08", value: 3.1 + offset, observationCount: 21, partial: false },
  { month: "2026-09", value: 3.3 + offset, observationCount: 1, partial: true },
];
const response = {
  generatedAt: "2026-09-02T06:00:00.000Z", availableFrom: "2026-06", availableThrough: "2026-09", completeThrough: "2026-08",
  series: [
    { code: "BOK_BASE_RATE_MONTHLY", name: "한국은행 기준금리", group: "KOREA", source: "한국은행 ECOS", unit: "PERCENT", validFrom: "2000-01-01", sourceVintageAt: "2026-09-02T05:00:00Z", points: points() },
    { code: "US_EFFR", name: "미국 유효 연방기금금리", group: "US_POLICY", source: "뉴욕연방준비은행", unit: "PERCENT", validFrom: "2000-07-03", sourceVintageAt: "2026-09-02T05:00:00Z", points: points(1) },
    { code: "US_TREASURY_10Y", name: "미국 국채 10년 금리", group: "US_TREASURY", source: "미국 재무부", unit: "PERCENT", validFrom: "1990-01-02", sourceVintageAt: "2026-09-02T05:00:00Z", points: points(2) },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("MacroTimeseriesWorkspace", () => {
  it("links every relative-height chart to one shared month control", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify(response), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MacroTimeseriesWorkspace/>);
    expect(await screen.findByRole("heading", { name: "금리의 방향을 한 화면에서" })).toBeInTheDocument();
    expect(screen.getAllByTestId("macro-strip")).toHaveLength(3);
    expect(screen.getAllByText("2026-08").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole("slider", { name: "공통 조회 월" }), { target: { value: "0" } });
    await waitFor(() => expect(screen.getAllByText("2026-06").length).toBeGreaterThan(0));
    expect(screen.getAllByTestId("macro-strip").every((item) => item.getAttribute("data-selected-month") === "2026-06")).toBe(true);
    expect(screen.getAllByText("전월 관측 없음")).toHaveLength(3);
    expect(screen.getAllByText(/최근 1개 관측 평균/).length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText(/12개월 평균/)).not.toBeInTheDocument();
    expect(screen.queryByText("해당 월 관측 없음")).not.toBeInTheDocument();
    const rateTrigger = screen.getByText("3.00%").closest("[data-context-info]") as HTMLElement;
    expect(document.getElementById(rateTrigger.getAttribute("aria-describedby")!)).toHaveTextContent("완료월 관측 · 원천 관측 20개");
    const sourceTrigger = screen.getByText("한국은행 ECOS").closest("[data-context-info]") as HTMLElement;
    const sourceTooltip = document.getElementById(sourceTrigger.getAttribute("aria-describedby")!);
    expect(within(sourceTooltip as HTMLElement).getByRole("link", { name: /공식 출처 열기/ })).toHaveAttribute("href", "https://ecos.bok.or.kr/");
    expect(fetchMock.mock.calls[0]?.[1]?.cache).toBeUndefined();
  });

  it("renders isolated observations without interpolating across a gap", async () => {
    const isolated = { ...response, series: [{ ...response.series[0], points: [response.series[0].points[0], response.series[0].points[2]] }] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(isolated), { status: 200 })));
    const { container } = render(<MacroTimeseriesWorkspace/>);
    expect(await screen.findByRole("heading", { name: "금리의 방향을 한 화면에서" })).toBeInTheDocument();
    expect(container.querySelectorAll(".macro-isolated-point")).toHaveLength(2);
    expect(container.querySelectorAll(".macro-line")).toHaveLength(0);
    expect(screen.getByText("전월 관측 없음")).toBeInTheDocument();
    expect(screen.getAllByText(/최근 2개 관측 평균/).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/2개월 평균/)).not.toBeInTheDocument();
    const stripControl = screen.getByRole("slider", { name: "한국은행 기준금리 공통 조회 월" });
    expect(stripControl).toHaveAttribute("aria-valuetext", "2026-08 · 3.10%");
  });

  it("distinguishes a rating minus sign from an actual percentage-point spread", async () => {
    const unitResponse = {
      ...response,
      series: [
        { ...response.series[0], code: "KR_CORP_BOND_AA_MINUS_3Y", name: "회사채 AA- 3년 금리" },
        { ...response.series[2], code: "US_TREASURY_10Y_MINUS_2Y", name: "미국 국채 10년-2년 금리차" },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(unitResponse), { status: 200 })));
    render(<MacroTimeseriesWorkspace/>);
    const corporate = (await screen.findByText("회사채 AA- 3년 금리")).closest("article") as HTMLElement;
    const spread = screen.getByText("미국 국채 10년-2년 금리차").closest("article") as HTMLElement;
    expect(within(corporate).getByText("3.10%")).toBeInTheDocument();
    expect(corporate).not.toHaveTextContent("3.10%p");
    expect(within(spread).getByText("5.10%p")).toBeInTheDocument();
    expect(spread.querySelectorAll(".macro-zero-line")).toHaveLength(1);
    expect(document.querySelectorAll(".macro-point.partial")).toHaveLength(0);
  });

  it("shows an honest unavailable state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    render(<MacroTimeseriesWorkspace/>);
    expect(await screen.findByRole("alert")).toHaveTextContent("금리 시계열을 불러오지 못했습니다");
  });
});
