import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({
  unstable_cache: (loader: (...args: unknown[]) => unknown) => loader,
}));

import { loadLargeTransactionsResponse } from "@/app/api/market/transactions/route";
import {
  LARGE_TRANSACTION_MIN_AREA_M2,
  type LargeTransactionsResponse,
} from "@/lib/large-transactions-contract";
import { DATA_SERVER_UNAVAILABLE_MESSAGE } from "@/lib/server/api-response";
import { LargeTransactionDetailUnavailableError } from "@/lib/server/large-transactions-cache";
import { LargeTransactionMonthUnavailableError } from "@/lib/server/large-transactions";

const request = (query = "") => new Request(`http://localhost/api/market/transactions${query}`);

const payload: LargeTransactionsResponse = {
  datasetVersion: "dataset-v1",
  generatedAt: "2026-09-09T00:00:00Z",
  month: "2026-07",
  minAreaPyeong: 5_000,
  minAreaM2: LARGE_TRANSACTION_MIN_AREA_M2,
  areaBasis: "TRANSACTED_BUILDING_AREA",
  totalCount: 0,
  baseTransactionCount: 14,
  page: 1,
  pageSize: 20,
  totalPages: 0,
  rows: [],
  coverage: { status: "COMPLETE", expectedDistrictCount: 25, completedDistrictCount: 25 },
  source: {
    code: "MOLIT_REAL_TRANSACTION",
    label: "국토교통부 실거래 공개시스템",
    geography: "서울특별시",
    completedPartitionsOnly: true,
    exactPayloadDeduplicated: true,
    currentServingOnly: true,
  },
};

describe("GET /api/market/transactions", () => {
  it("returns a private no-store result and passes the parsed month and page", async () => {
    const loader = vi.fn(async () => payload);
    const response = await loadLargeTransactionsResponse(
      request("?month=2026-07&page=1"),
      loader,
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(payload);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("server-timing")).toMatch(/^data;dur=/u);
    expect(loader).toHaveBeenCalledWith({ month: "2026-07", page: 1 });
  });

  it.each([
    "?month=2026-7",
    "?month=2026-07&page=0",
    "?month=2026-07&pageSize=20",
  ])("returns 400 before loading for invalid input: %s", async (query) => {
    const loader = vi.fn();
    const response = await loadLargeTransactionsResponse(request(query), loader);
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      error: "대형 거래 조회 조건이 올바르지 않습니다.",
      code: "INVALID_LARGE_TRANSACTION_QUERY",
    });
    expect(loader).not.toHaveBeenCalled();
  });

  it("returns a distinct 409 when the selected month is not a completed snapshot", async () => {
    const response = await loadLargeTransactionsResponse(
      request("?month=2026-09"),
      async () => { throw new LargeTransactionMonthUnavailableError(); },
    );
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({
      error: "선택한 월의 서울 25개 자치구 완료 자료가 준비되지 않았습니다.",
      code: "LARGE_TRANSACTION_MONTH_UNAVAILABLE",
    });
  });

  it("reports detail-less providers as unavailable rather than an empty success", async () => {
    const response = await loadLargeTransactionsResponse(
      request("?month=2026-07"),
      async () => { throw new LargeTransactionDetailUnavailableError(); },
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: "현재 데이터 제공 방식에는 개별 거래 자료가 포함되어 있지 않습니다.",
      code: "LARGE_TRANSACTION_DETAIL_UNAVAILABLE",
    });
  });

  it("fails closed on database timeouts or errors without logging their contents", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const response = await loadLargeTransactionsResponse(
      request("?month=2026-07"),
      async () => { throw Object.assign(new Error("secret SQL and credential"), { code: "secret-code" }); },
    );
    const body = await response.json();
    expect(response.status).toBe(503);
    expect(body).toEqual({
      error: DATA_SERVER_UNAVAILABLE_MESSAGE,
      code: "LARGE_TRANSACTIONS_UNAVAILABLE",
    });
    expect(JSON.stringify(body)).not.toMatch(/secret|SQL|credential/u);
    expect(consoleError).toHaveBeenCalledWith("large transaction request failed", {
      code: "LARGE_TRANSACTIONS_UNAVAILABLE",
    });
    consoleError.mockRestore();
  });
});
