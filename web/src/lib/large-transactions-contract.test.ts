import { describe, expect, it } from "vitest";
import {
  LARGE_TRANSACTION_MIN_AREA_M2,
  LARGE_TRANSACTION_PAGE_SIZE,
  LargeTransactionRequestError,
  normalizeLargeTransactions,
  parseLargeTransactionsRequest,
  type LargeTransactionsResponse,
} from "@/lib/large-transactions-contract";

const payload = (): LargeTransactionsResponse => ({
  datasetVersion: "dataset-v1",
  generatedAt: "2026-09-09T00:00:00Z",
  month: "2026-07",
  minAreaPyeong: 5_000,
  minAreaM2: LARGE_TRANSACTION_MIN_AREA_M2,
  areaBasis: "TRANSACTED_BUILDING_AREA",
  totalCount: 1,
  baseTransactionCount: 14,
  page: 1,
  pageSize: LARGE_TRANSACTION_PAGE_SIZE,
  totalPages: 1,
  rows: [{
    id: "payload-hash-1",
    dealDate: "2026-07-03",
    address: "강남구 역삼동 7**-*",
    buildingUse: "업무시설",
    buildingType: null,
    areaM2: LARGE_TRANSACTION_MIN_AREA_M2,
    areaPyeong: 5_000,
    amountKrw: "12340000",
  }],
  coverage: { status: "COMPLETE", expectedDistrictCount: 25, completedDistrictCount: 25 },
  source: {
    code: "MOLIT_REAL_TRANSACTION",
    label: "국토교통부 실거래 공개시스템",
    geography: "서울특별시",
    completedPartitionsOnly: true,
    exactPayloadDeduplicated: true,
    currentServingOnly: true,
  },
});

describe("large transactions contract", () => {
  it("parses only a completed-month-shaped query and applies page one", () => {
    expect(parseLargeTransactionsRequest(new URLSearchParams("month=2026-07"))).toEqual({
      month: "2026-07",
      page: 1,
    });
    expect(parseLargeTransactionsRequest(new URLSearchParams("month=2026-07&page=2"))).toEqual({
      month: "2026-07",
      page: 2,
    });
  });

  it.each([
    "",
    "month=2026-7",
    "month=2026-13",
    "month=2026-07&month=2026-08",
    "month=2026-07&page=0",
    "month=2026-07&page=1.5",
    "month=2026-07&page=501",
    "month=2026-07&page=1&page=2",
    "month=2026-07&pageSize=20",
  ])("rejects malformed, duplicate, or unknown input: %s", (query) => {
    expect(() => parseLargeTransactionsRequest(new URLSearchParams(query)))
      .toThrow(LargeTransactionRequestError);
  });

  it("normalizes the inclusive 5,000-pyeong boundary without changing masked addresses", () => {
    expect(normalizeLargeTransactions(payload())).toEqual(payload());
  });

  it("accepts an honestly empty completed month only on page one", () => {
    const empty = payload();
    empty.totalCount = 0;
    empty.totalPages = 0;
    empty.rows = [];
    expect(normalizeLargeTransactions(empty)).toMatchObject({
      totalCount: 0,
      totalPages: 0,
      page: 1,
      rows: [],
    });

    const impossiblePage = { ...empty, page: 2 };
    expect(() => normalizeLargeTransactions(impossiblePage)).toThrow(/invariants/u);
  });

  it("rejects page/count mismatches, duplicate ids, malformed amounts, and below-threshold rows", () => {
    const outOfRange = payload();
    outOfRange.totalCount = 20;
    outOfRange.totalPages = 1;
    outOfRange.page = 2;
    outOfRange.rows = [];
    expect(() => normalizeLargeTransactions(outOfRange)).toThrow(/invariants/u);

    const duplicate = payload();
    duplicate.totalCount = 2;
    duplicate.totalPages = 1;
    duplicate.rows = [duplicate.rows[0], { ...duplicate.rows[0] }];
    expect(() => normalizeLargeTransactions(duplicate)).toThrow(/duplicate/u);

    const malformedAmount = payload();
    malformedAmount.rows[0].amountKrw = "12,340,000";
    expect(() => normalizeLargeTransactions(malformedAmount)).toThrow(/facts/u);

    const belowThreshold = payload();
    belowThreshold.rows[0].areaM2 = LARGE_TRANSACTION_MIN_AREA_M2 - 0.01;
    belowThreshold.rows[0].areaPyeong = 5_000;
    expect(() => normalizeLargeTransactions(belowThreshold)).toThrow(/facts/u);
  });
});
