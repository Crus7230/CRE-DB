import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PermitTimeseriesWorkspace } from "@/components/permit-timeseries-workspace";

const payload = {
  generatedAt: "2026-09-08T06:30:00.000Z",
  sourceAsOfDate: "2026-09-07",
  availableFrom: "2021-09",
  availableThrough: "2026-08",
  selectedFrom: "2021-09",
  selectedThrough: "2026-08",
  groupBy: "ASSET_TYPE",
  filters: { eventType: null, assetType: null, district: null, constructionAction: null },
  source: { code: "src_seoul_building_permit", label: "서울 열린데이터광장" },
  scope: {
    status: "IN_SCOPE",
    completedSnapshotsOnly: true,
    dateRule: "ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT",
  },
  series: [
    {
      key: "OFFICE",
      label: "오피스",
      points: [
        { month: "2026-07", permitCount: 2, totalFloorAreaM2: 10_000, missingAreaCount: 0, invalidAreaCount: 0 },
        { month: "2026-08", permitCount: 1, totalFloorAreaM2: 0, missingAreaCount: 1, invalidAreaCount: 0 },
      ],
    },
    {
      key: "LOGISTICS",
      label: "물류센터",
      points: [
        { month: "2026-07", permitCount: 1, totalFloorAreaM2: 2_000, missingAreaCount: 0, invalidAreaCount: 0 },
        { month: "2026-08", permitCount: 1, totalFloorAreaM2: 0, missingAreaCount: 0, invalidAreaCount: 1 },
      ],
    },
  ],
  quality: {
    aggregateRowCount: 4,
    permitCount: 5,
    totalFloorAreaM2: 12_000,
    missingAreaCount: 1,
    invalidAreaCount: 1,
  },
};

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("PermitTimeseriesWorkspace", () => {
  it("shows the bounded Seoul provenance, actual metrics, and a compact filter set", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const filtered = url.includes("eventType=PERMIT");
      return new Response(JSON.stringify(filtered ? {
        ...payload,
        selectedFrom: "2026-07",
        selectedThrough: "2026-08",
        filters: { ...payload.filters, eventType: "PERMIT" },
      } : payload), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { container } = render(<PermitTimeseriesWorkspace/>);

    expect(await screen.findByRole("heading", { name: "서울 건축 인허가 흐름" })).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0]?.[0])).toMatch(/groupBy=ASSET_TYPE&eventType=PERMIT$/);
    expect(screen.getByText("최근월은 수집 진행에 따라 변동될 수 있습니다.")).toBeInTheDocument();
    expect(screen.getByText(/분석 범위 포함\(IN_SCOPE\) · 검토 후보 제외/)).toBeInTheDocument();
    expect(screen.getAllByText("1.2만㎡").length).toBeGreaterThan(0);
    expect(screen.getByText("서울 열린데이터광장 · 원천 기준일 2026-09-07")).toBeInTheDocument();
    expect(container.querySelectorAll(".permit-area-line")).toHaveLength(1);
    expect(container.querySelectorAll(".permit-area-point")).toHaveLength(1);
    expect(screen.getByRole("table")).toHaveTextContent("오피스");
    expect(screen.queryByRole("combobox", { name: "자산" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "자치구" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("인허가 시작월"), { target: { value: "2026-07" } });
    fireEvent.change(screen.getByLabelText("인허가 종료월"), { target: { value: "2026-08" } });
    await user.selectOptions(screen.getByRole("combobox", { name: "기준 단계" }), "PERMIT");
    await user.click(screen.getByRole("button", { name: "적용" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const secondUrl = String(fetchMock.mock.calls[1]?.[0]);
    expect(secondUrl).toContain("from=2026-07");
    expect(secondUrl).toContain("to=2026-08");
    expect(secondUrl).toContain("eventType=PERMIT");
    expect(secondUrl).not.toContain("assetType");
    expect(within(screen.getByLabelText("현재 인허가 조회 조건")).getByText("건축허가")).toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "기준 단계" }), "");
    await user.click(screen.getByRole("button", { name: "적용" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(await screen.findByText("단계 간 중복 가능한 누적면적")).toBeInTheDocument();
  });

  it("opens with an asset breakdown while keeping stage grouping available", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const params = new URL(String(input), "http://localhost").searchParams;
      const groupBy = params.get("groupBy") ?? "EVENT_TYPE";
      const eventType = params.get("eventType");
      return new Response(JSON.stringify({
        ...payload,
        groupBy,
        filters: { ...payload.filters, eventType },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<PermitTimeseriesWorkspace/>);

    expect(await screen.findByRole("heading", { name: "서울 건축 인허가 흐름" })).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("groupBy=ASSET_TYPE");
    expect(screen.getByRole("button", { name: "자산 유형" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("table")).toHaveTextContent("오피스");
    expect(screen.getByRole("table")).toHaveTextContent("물류센터");
    expect(screen.getByRole("table")).toHaveTextContent("60.0%");
    expect(screen.getByRole("table")).toHaveTextContent("40.0%");

    await user.click(screen.getByRole("button", { name: "진행 단계" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("groupBy=EVENT_TYPE");
    expect(screen.getByRole("button", { name: "진행 단계" })).toHaveAttribute("aria-pressed", "true");
  });

  it("previews full month columns instantly and pins an exact monthly group aggregate", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<PermitTimeseriesWorkspace/>);

    const july = await screen.findByRole("button", { name: /2026-07, 기록 3건, 연면적 12,000㎡/ });
    const august = screen.getByRole("button", { name: /2026-08, 기록 2건, 연면적 확인 불가, 면적 누락 1건, 면적 오류 1건/ });
    expect(july).toHaveAttribute("tabindex", "-1");
    expect(august).toHaveAttribute("tabindex", "0");
    expect(july).toHaveAttribute("aria-pressed", "false");

    fireEvent.pointerEnter(july);
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-07");
    expect(screen.getByRole("tooltip")).toHaveTextContent("연면적12,000㎡");
    expect(screen.getByRole("tooltip")).toHaveTextContent("단계 간 중복 가능한 누적면적");
    fireEvent.pointerLeave(july);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.click(july);
    expect(july).toHaveAttribute("aria-pressed", "true");
    const panel = screen.getByRole("region", { name: "2026-07 선택 월 집계" });
    expect(panel).toHaveTextContent("현재 필터(기준 단계: 전체 단계, 묶어보기: 자산 유형)");
    expect(panel).toHaveTextContent("선택 월 × 자산 유형 집계");
    expect(panel).toHaveTextContent("개별 건축물·사업 기록이 아닙니다.");
    expect(panel).toHaveTextContent("전체 단계 연면적은 단계 간 중복 가능한 누적면적입니다.");
    expect(within(panel).getByLabelText("2026-07 선택 월 품질 합계")).toHaveTextContent("기록3건연면적12,000㎡면적 유효3건누락0건오류0건");

    const table = within(panel).getByRole("table", { name: "2026-07 선택 월 자산 유형별 집계" });
    const officeRow = within(table).getByRole("row", { name: /오피스/ });
    const logisticsRow = within(table).getByRole("row", { name: /물류센터/ });
    expect(officeRow).toHaveTextContent("오피스266.7%10,000㎡83.3%00");
    expect(logisticsRow).toHaveTextContent("물류센터133.3%2,000㎡16.7%00");
    expect(within(table).queryByText("60.0%")).not.toBeInTheDocument();
    expect(within(table).queryByText("40.0%")).not.toBeInTheDocument();

    fireEvent.pointerEnter(august);
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08");
    expect(screen.getByRole("tooltip")).toHaveTextContent("연면적확인 불가");
    expect(screen.getByRole("tooltip")).toHaveTextContent("면적 누락1건");
    expect(screen.getByRole("tooltip")).toHaveTextContent("면적 오류1건");
    fireEvent.pointerLeave(august);
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-07");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "2026-07 선택 해제" }));
    expect(screen.queryByRole("region", { name: "2026-07 선택 월 집계" })).not.toBeInTheDocument();
    expect(july).toHaveAttribute("aria-pressed", "false");
    expect(july).toHaveFocus();
  });

  it("supports focus, Enter, Space, and Escape without another request", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<PermitTimeseriesWorkspace/>);

    const july = await screen.findByRole("button", { name: /2026-07, 기록 3건/ });
    const august = screen.getByRole("button", { name: /2026-08, 기록 2건/ });
    act(() => { august.focus(); });
    expect(august).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08");
    fireEvent.keyDown(august, { key: "ArrowLeft" });
    expect(july).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-07");

    fireEvent.keyDown(july, { key: "Enter" });
    expect(screen.getByRole("region", { name: "2026-07 선택 월 집계" })).toBeInTheDocument();
    fireEvent.keyDown(july, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "2026-07 선택 월 집계" })).not.toBeInTheDocument();
    expect(july).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-07");

    fireEvent.keyDown(july, { key: " " });
    expect(screen.getByRole("region", { name: "2026-07 선택 월 집계" })).toBeInTheDocument();
    expect(july).toHaveAttribute("aria-pressed", "true");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rounds aggregated square metres to the source's two-decimal precision", async () => {
    const fractional = {
      ...payload,
      series: payload.series.map((series, index) => ({
        ...series,
        points: [{
          month: "2026-07",
          permitCount: 1,
          totalFloorAreaM2: index === 0 ? 0.1 : 0.2,
          missingAreaCount: 0,
          invalidAreaCount: 0,
        }],
      })),
      quality: { aggregateRowCount: 2, permitCount: 2, totalFloorAreaM2: 0.3, missingAreaCount: 0, invalidAreaCount: 0 },
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(fractional), { status: 200 })));
    render(<PermitTimeseriesWorkspace/>);

    const july = await screen.findByRole("button", { name: /2026-07, 기록 2건, 연면적 0.3㎡/ });
    fireEvent.pointerEnter(july);
    expect(screen.getByRole("tooltip")).toHaveTextContent("0.3㎡");
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("0.30000000000000004㎡");
  });

  it("renders missing area as unavailable instead of a fabricated zero", async () => {
    const missingOnly = {
      ...payload,
      series: [{
        ...payload.series[0],
        points: [{ month: "2026-08", permitCount: 1, totalFloorAreaM2: 0, missingAreaCount: 1, invalidAreaCount: 0 }],
      }],
      quality: {
        aggregateRowCount: 1,
        permitCount: 1,
        totalFloorAreaM2: 0,
        missingAreaCount: 1,
        invalidAreaCount: 0,
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(missingOnly), { status: 200 })));
    const { container } = render(<PermitTimeseriesWorkspace/>);

    expect(await screen.findByText("유효 면적 기록 없음")).toBeInTheDocument();
    expect(container.querySelectorAll(".permit-area-line")).toHaveLength(0);
    expect(container.querySelectorAll(".permit-area-point")).toHaveLength(0);
    fireEvent.pointerEnter(screen.getByRole("button", { name: /2026-08, 기록 1건, 연면적 확인 불가, 면적 누락 1건/ }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("연면적확인 불가");
    expect(container).not.toHaveTextContent("0㎡");
  });

  it("keeps a valid zero-area observation distinct from missing area", async () => {
    const validZero = {
      ...payload,
      filters: { ...payload.filters, eventType: "PERMIT" },
      series: [{
        ...payload.series[0],
        points: [{ month: "2026-08", permitCount: 1, totalFloorAreaM2: 0, missingAreaCount: 0, invalidAreaCount: 0 }],
      }],
      quality: {
        aggregateRowCount: 1,
        permitCount: 1,
        totalFloorAreaM2: 0,
        missingAreaCount: 0,
        invalidAreaCount: 0,
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(validZero), { status: 200 })));
    const { container } = render(<PermitTimeseriesWorkspace/>);

    expect(await screen.findByText("건축허가 유효 면적 합계")).toBeInTheDocument();
    expect(screen.getAllByText("0㎡").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".permit-area-line")).toHaveLength(1);
    expect(container.querySelectorAll(".permit-area-point")).toHaveLength(1);
    expect(container).not.toHaveTextContent("연면적 확인 불가");
  });

  it("formats very large areas in hundred-million square metres", async () => {
    const largeArea = {
      ...payload,
      filters: { ...payload.filters, eventType: "PERMIT" },
      quality: { ...payload.quality, totalFloorAreaM2: 413_742_498.64 },
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(largeArea), { status: 200 })));
    render(<PermitTimeseriesWorkspace/>);

    expect(await screen.findByText("4.1억㎡")).toBeInTheDocument();
    expect(screen.queryByText("41,374.2만㎡")).not.toBeInTheDocument();
  });

  it("separates a 10-second timeout from valid zero data and offers retry", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    render(<PermitTimeseriesWorkspace/>);

    await act(async () => { await vi.advanceTimersByTimeAsync(10_001); });
    expect(screen.getByRole("alert")).toHaveTextContent("인허가 조회 시간이 초과되었습니다.");
    expect(screen.getByRole("button", { name: /다시 조회/ })).toBeInTheDocument();
    expect(screen.queryByText("인허가 기록")).not.toBeInTheDocument();
  });
});
