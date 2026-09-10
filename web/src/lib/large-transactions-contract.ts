export const LARGE_TRANSACTION_PAGE_SIZE = 20 as const;
export const MAX_LARGE_TRANSACTION_PAGE = 500;
export const LARGE_TRANSACTION_MIN_AREA_PYEONG = 5_000 as const;
export const LARGE_TRANSACTION_MIN_AREA_M2 = LARGE_TRANSACTION_MIN_AREA_PYEONG * 400 / 121;

export type LargeTransactionsRequest = {
  month: string;
  page: number;
};

export type LargeTransactionRow = {
  id: string;
  dealDate: string;
  address: string;
  buildingUse: string;
  buildingType: string | null;
  areaM2: number;
  areaPyeong: number;
  amountKrw: string;
};

export type LargeTransactionsResponse = {
  datasetVersion: string;
  generatedAt: string;
  month: string;
  minAreaPyeong: typeof LARGE_TRANSACTION_MIN_AREA_PYEONG;
  minAreaM2: number;
  areaBasis: "TRANSACTED_BUILDING_AREA";
  totalCount: number;
  baseTransactionCount: number;
  page: number;
  pageSize: typeof LARGE_TRANSACTION_PAGE_SIZE;
  totalPages: number;
  rows: LargeTransactionRow[];
  coverage: {
    status: "COMPLETE";
    expectedDistrictCount: 25;
    completedDistrictCount: 25;
  };
  source: {
    code: "MOLIT_REAL_TRANSACTION";
    label: "국토교통부 실거래 공개시스템";
    geography: "서울특별시";
    completedPartitionsOnly: true;
    exactPayloadDeduplicated: true;
    currentServingOnly: true;
  };
};

export class LargeTransactionRequestError extends Error {
  readonly code = "INVALID_LARGE_TRANSACTION_QUERY";
}

const ISO_MONTH = /^\d{4}-(?:0[1-9]|1[0-2])$/u;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/u;
const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u;
const DECIMAL_INTEGER = /^(?:0|[1-9]\d*)$/u;

export function parseLargeTransactionsRequest(params: URLSearchParams): LargeTransactionsRequest {
  for (const name of params.keys()) {
    if (name !== "month" && name !== "page") {
      throw new LargeTransactionRequestError(`Unknown parameter: ${name}`);
    }
  }
  const months = params.getAll("month");
  const pages = params.getAll("page");
  if (months.length !== 1 || !ISO_MONTH.test(months[0] ?? "") || pages.length > 1) {
    throw new LargeTransactionRequestError("Invalid month or duplicate parameter");
  }
  const rawPage = pages.length === 0 ? "1" : pages[0];
  if (!/^[1-9]\d*$/u.test(rawPage) || rawPage.length > 6) {
    throw new LargeTransactionRequestError("Invalid page");
  }
  const page = Number(rawPage);
  if (!Number.isSafeInteger(page) || page > MAX_LARGE_TRANSACTION_PAGE) {
    throw new LargeTransactionRequestError("Invalid page");
  }
  return { month: months[0], page };
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown, label: string, maximumLength = 256) {
  if (
    typeof value !== "string"
    || value.trim() === ""
    || value.length > maximumLength
    || /[\u0000-\u001f\u007f]/u.test(value)
  ) throw new Error(`Invalid ${label}`);
  return value;
}

function integer(value: unknown, label: string) {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`Invalid ${label}`);
  }
  return value;
}

function finite(value: unknown, label: string) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new Error(`Invalid ${label}`);
  }
  return value;
}

function timestamp(value: unknown, label: string) {
  const result = text(value, label, 64);
  if (!ISO_TIMESTAMP.test(result) || Number.isNaN(Date.parse(result))) {
    throw new Error(`Invalid ${label}`);
  }
  return result;
}

function date(value: unknown, label: string) {
  const result = text(value, label, 10);
  if (
    !ISO_DATE.test(result)
    || new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result
  ) throw new Error(`Invalid ${label}`);
  return result;
}

export function normalizeLargeTransactions(value: unknown): LargeTransactionsResponse {
  if (!record(value) || !Array.isArray(value.rows) || !record(value.coverage) || !record(value.source)) {
    throw new Error("Invalid large transactions payload");
  }
  const month = text(value.month, "month", 7);
  if (!ISO_MONTH.test(month)) throw new Error("Invalid month");
  const minAreaPyeong = finite(value.minAreaPyeong, "minAreaPyeong");
  const minAreaM2 = finite(value.minAreaM2, "minAreaM2");
  const totalCount = integer(value.totalCount, "totalCount");
  const baseTransactionCount = integer(value.baseTransactionCount, "baseTransactionCount");
  const page = integer(value.page, "page");
  const pageSize = integer(value.pageSize, "pageSize");
  const totalPages = integer(value.totalPages, "totalPages");
  if (
    minAreaPyeong !== LARGE_TRANSACTION_MIN_AREA_PYEONG
    || Math.abs(minAreaM2 - LARGE_TRANSACTION_MIN_AREA_M2) > 1e-9
    || value.areaBasis !== "TRANSACTED_BUILDING_AREA"
    || baseTransactionCount < totalCount
    || page < 1
    || page > MAX_LARGE_TRANSACTION_PAGE
    || page > Math.max(1, totalPages)
    || pageSize !== LARGE_TRANSACTION_PAGE_SIZE
    || totalPages !== Math.ceil(totalCount / LARGE_TRANSACTION_PAGE_SIZE)
  ) throw new Error("Invalid large transactions invariants");
  const expectedRows = totalCount === 0
    ? 0
    : Math.min(LARGE_TRANSACTION_PAGE_SIZE, totalCount - (page - 1) * LARGE_TRANSACTION_PAGE_SIZE);
  if (expectedRows < 0 || value.rows.length !== expectedRows) {
    throw new Error("Invalid large transactions pagination");
  }
  if (
    value.coverage.status !== "COMPLETE"
    || value.coverage.expectedDistrictCount !== 25
    || value.coverage.completedDistrictCount !== 25
  ) throw new Error("Invalid large transactions coverage");
  if (
    value.source.code !== "MOLIT_REAL_TRANSACTION"
    || value.source.label !== "국토교통부 실거래 공개시스템"
    || value.source.geography !== "서울특별시"
    || value.source.completedPartitionsOnly !== true
    || value.source.exactPayloadDeduplicated !== true
    || value.source.currentServingOnly !== true
  ) throw new Error("Invalid large transactions source");

  const rows = value.rows.map((raw, index): LargeTransactionRow => {
    if (!record(raw)) throw new Error(`Invalid row ${index}`);
    const dealDate = date(raw.dealDate, `rows.${index}.dealDate`);
    const areaM2 = finite(raw.areaM2, `rows.${index}.areaM2`);
    const areaPyeong = finite(raw.areaPyeong, `rows.${index}.areaPyeong`);
    const amountKrw = text(raw.amountKrw, `rows.${index}.amountKrw`, 32);
    const buildingType = raw.buildingType === null
      ? null
      : text(raw.buildingType, `rows.${index}.buildingType`, 100);
    const expectedPyeong = Math.round(areaM2 * 121 / 400 * 100) / 100;
    if (
      !dealDate.startsWith(`${month}-`)
      || areaM2 + 1e-9 < LARGE_TRANSACTION_MIN_AREA_M2
      || Math.abs(areaPyeong - expectedPyeong) > 1e-9
      || !DECIMAL_INTEGER.test(amountKrw)
    ) throw new Error(`Invalid row ${index} facts`);
    return {
      id: text(raw.id, `rows.${index}.id`, 128),
      dealDate,
      address: text(raw.address, `rows.${index}.address`, 200),
      buildingUse: text(raw.buildingUse, `rows.${index}.buildingUse`, 100),
      buildingType,
      areaM2,
      areaPyeong,
      amountKrw,
    };
  });
  if (new Set(rows.map((row) => row.id)).size !== rows.length) {
    throw new Error("Invalid duplicate row ids");
  }

  return {
    datasetVersion: text(value.datasetVersion, "datasetVersion", 128),
    generatedAt: timestamp(value.generatedAt, "generatedAt"),
    month,
    minAreaPyeong: LARGE_TRANSACTION_MIN_AREA_PYEONG,
    minAreaM2: LARGE_TRANSACTION_MIN_AREA_M2,
    areaBasis: "TRANSACTED_BUILDING_AREA",
    totalCount,
    baseTransactionCount,
    page,
    pageSize: LARGE_TRANSACTION_PAGE_SIZE,
    totalPages,
    rows,
    coverage: {
      status: "COMPLETE",
      expectedDistrictCount: 25,
      completedDistrictCount: 25,
    },
    source: {
      code: "MOLIT_REAL_TRANSACTION",
      label: "국토교통부 실거래 공개시스템",
      geography: "서울특별시",
      completedPartitionsOnly: true,
      exactPayloadDeduplicated: true,
      currentServingOnly: true,
    },
  };
}
