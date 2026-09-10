import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LargeTransactionList } from "@/components/large-transaction-list";

function responseFor(page = 1, totalCount = 1, baseTransactionCount = 30) {
  const first = (page - 1) * 20;
  const rowCount = totalCount === 0 ? 0 : Math.min(20, totalCount - first);
  return {
    datasetVersion: "cre-test",
    generatedAt: "2026-09-10T03:00:00.000Z",
    month: "2026-07",
    minAreaPyeong: 5000,
    minAreaM2: 5000 * 400 / 121,
    areaBasis: "TRANSACTED_BUILDING_AREA",
    totalCount,
    baseTransactionCount,
    page,
    pageSize: 20,
    totalPages: Math.ceil(totalCount / 20),
    rows: Array.from({ length: rowCount }, (_, offset) => {
      const item = first + offset + 1;
      const areaM2 = 20_000 + item;
      return {
        id: `row-${item}`,
        dealDate: `2026-07-${String(item % 20 + 1).padStart(2, "0")}`,
        address: `서울 테스트 ${item}`,
        buildingUse: "업무",
        buildingType: item % 2 === 0 ? null : "일반",
        areaM2,
        areaPyeong: Math.round(areaM2 * 121 / 400 * 100) / 100,
        amountKrw: String(100_000_000 + item),
      };
    }),
    coverage: { status: "COMPLETE", expectedDistrictCount: 25, completedDistrictCount: 25 },
    source: { code: "MOLIT_REAL_TRANSACTION", label: "국토교통부 실거래 공개시스템", geography: "서울특별시", completedPartitionsOnly: true, exactPayloadDeduplicated: true, currentServingOnly: true },
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("LargeTransactionList", () => {
  it.each([
    [503, "LARGE_TRANSACTION_DETAIL_UNAVAILABLE", "5천평 이상 상세 데이터 연결 전입니다.", "월별 차트 집계는 유지"],
    [409, "LARGE_TRANSACTION_MONTH_UNAVAILABLE", "이 월은 상세 목록 조회 범위에 아직 포함되지 않습니다.", "수집 완료 범위만 조회"],
  ])("keeps HTTP %s failures distinct from a valid empty result", async (status, code, title, detail) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code }), { status })));
    render(<LargeTransactionList month="2026-07" baseTransactionCount={30} cacheScope="pulse-a" onClear={vi.fn()}/>);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(title);
    expect(alert).toHaveTextContent(detail);
    expect(screen.queryByText(/5천평 미만 거래가 포함/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /다시 조회/ })).toBeInTheDocument();
  });

  it("stops retrying when the pulse and detail snapshot counts differ", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(responseFor(1, 1, 31)), { status: 200 })));
    render(<LargeTransactionList month="2026-07" baseTransactionCount={30} cacheScope="pulse-a" onClear={vi.fn()}/>);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("집계 기준이 갱신되었습니다.");
    expect(alert).toHaveTextContent("화면을 새로고침해 주세요.");
    expect(screen.queryByRole("button", { name: /다시 조회/ })).not.toBeInTheDocument();
  });

  it("times out independently from a completed zero-row response", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    render(<LargeTransactionList month="2026-07" baseTransactionCount={30} cacheScope="pulse-a" onClear={vi.fn()}/>);

    await act(async () => { await vi.advanceTimersByTimeAsync(10_001); });
    expect(screen.getByRole("alert")).toHaveTextContent("5천평 이상 거래 목록 조회 시간이 초과되었습니다.");
    expect(screen.queryByText(/5천평 이상 신고행은 없습니다/)).not.toBeInTheDocument();
  });

  it("paginates through the same endpoint and reuses a bounded fresh page", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const page = Number(new URL(String(input), "http://localhost").searchParams.get("page"));
      return new Response(JSON.stringify(responseFor(page, 21)), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<LargeTransactionList month="2026-07" baseTransactionCount={30} cacheScope="pulse-a" onClear={vi.fn()}/>);

    expect(await screen.findByText("서울 테스트 1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "다음" }));
    expect(await screen.findByText("서울 테스트 21")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "/api/market/transactions?month=2026-07&page=1",
      "/api/market/transactions?month=2026-07&page=2",
    ]);
    await user.click(screen.getByRole("button", { name: "이전" }));
    expect(await screen.findByText("서울 테스트 1")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
