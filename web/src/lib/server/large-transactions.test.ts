import { createClient, type Client } from "@libsql/client";
import { describe, expect, it, vi } from "vitest";
import {
  LARGE_TRANSACTION_MIN_AREA_M2,
  LargeTransactionRequestError,
} from "@/lib/large-transactions-contract";
import {
  getLargeTransactions,
  getLargeTransactionsFromCompactSnapshot,
  largeTransactionsSql,
  LargeTransactionDetailUnavailableError,
  LargeTransactionMonthUnavailableError,
  normalizeCompactLargeTransactionsPulse,
  type LargeTransactionsSqlExecutor,
} from "@/lib/server/large-transactions";

const DISTRICT_CODES = [
  "11110", "11140", "11170", "11200", "11215", "11230", "11260",
  "11290", "11305", "11320", "11350", "11380", "11410", "11440",
  "11470", "11500", "11530", "11545", "11560", "11590", "11620",
  "11650", "11680", "11710", "11740",
];

async function createSchema(client: Client) {
  await client.batch([
    `CREATE TABLE serving_molit_current_transactions(
      api_payload_sha256 TEXT,district_code TEXT,district_name TEXT,locality TEXT,
      building_use TEXT,building_area_text TEXT,deal_amount_text TEXT,
      deal_year TEXT,deal_month_number TEXT,deal_day TEXT,api_payload_json TEXT
    )`,
    `CREATE TABLE serving_molit_completed_partitions(
      deal_month TEXT,district_code TEXT,coverage_status TEXT
    )`,
    `CREATE TABLE serving_dataset_freshness(
      dataset_code TEXT,source_status_code TEXT,generated_at TEXT
    )`,
    `INSERT INTO serving_dataset_freshness VALUES(
      'MOLIT_TRANSACTIONS','READY','2026-09-09T00:00:00Z'
    )`,
  ], "write");
}

async function addCoverage(client: Client, month: string, count = 25) {
  for (const districtCode of DISTRICT_CODES.slice(0, count)) {
    await client.execute({
      sql: "INSERT INTO serving_molit_completed_partitions VALUES(?1,?2,'COMPLETE_FULL_SNAPSHOT')",
      args: [month, districtCode],
    });
  }
}

type RowInput = {
  id: string;
  area: string;
  month?: "7" | "07" | "6" | "06";
  day?: string;
  use?: string;
  amount?: string;
  buildingType?: string | null;
  jibun?: string;
};

async function addRow(client: Client, input: RowInput) {
  const month = input.month ?? "7";
  await client.execute({
    sql: `INSERT INTO serving_molit_current_transactions VALUES(
      ?1,'11680','강남구','역삼동',?2,?3,?4,'2026',?5,?6,?7
    )`,
    args: [
      input.id,
      input.use ?? "업무시설",
      input.area,
      input.amount ?? "1,234",
      month,
      input.day ?? "3",
      JSON.stringify({ buildingType: input.buildingType ?? null, jibun: input.jibun ?? "7**-*" }),
    ],
  });
}

function executor(client: Client): LargeTransactionsSqlExecutor {
  return async (sql, values) => {
    const result = await client.execute({ sql, args: [...values] });
    return {
      rows: result.rows.map((row) => ({
        payload: typeof row.payload === "string" ? JSON.parse(row.payload) : row.payload,
      })),
    };
  };
}

function compactPulse(transactionCount = 2) {
  const firstArea = 21_000;
  const secondArea = 20_000;
  const amount = transactionCount === 0 ? 0 : 30_000_000;
  const area = transactionCount === 0 ? 0 : firstArea + secondArea;
  const metric = (value: number) => ({
    value,
    previousValue: null,
    yearAgoValue: null,
    momPct: null,
    yoyPct: null,
    ytdValue: value,
    priorYtdValue: null,
    ytdYoyPct: null,
  });
  const point = (value: number | null) => ({
    value,
    previousValue: null,
    yearAgoValue: null,
    momPct: null,
    yoyPct: null,
  });
  const rows = transactionCount === 0 ? [] : [
    {
      id: "hash-a",
      dealDate: "2026-07-03",
      address: "강남구 역삼동 7**-*",
      buildingUse: "업무시설",
      buildingType: "일반",
      areaM2: firstArea,
      areaPyeong: 6_352.5,
      amountKrw: "10000000",
    },
    {
      id: "hash-b",
      dealDate: "2026-07-02",
      address: "영등포구 여의도동 1*-*",
      buildingUse: "업무시설",
      buildingType: null,
      areaM2: secondArea,
      areaPyeong: 6_050,
      amountKrw: "20000000",
    },
  ];
  return {
    datasetVersion: "dataset-v1",
    generatedAt: "2026-09-09T00:00:00Z",
    asOfPeriod: "2026-07",
    call: { headline: "시장 요약", detail: "시장 세부", caution: "해석 주의" },
    metrics: {
      amount: metric(amount),
      count: metric(transactionCount),
      area: metric(area),
      averageTicket: point(transactionCount === 0 ? null : amount / transactionCount),
      unitAmount: point(transactionCount === 0 ? null : amount / area),
    },
    trend: [{
      period: "2026-07",
      transactionCount,
      amountKrw: String(amount),
      areaM2: String(area),
      sourceRowCount: transactionCount,
      uniquePayloadCount: transactionCount,
    }],
    concentration: transactionCount === 0 ? { topGroups: [], districts: [] } : {
      topGroups: [
        { rank: 1, dealDate: "2026-07-02", district: "영등포구", locality: "여의도동", buildingUse: "업무시설", amountKrw: "20000000", areaM2: "20000", sharePct: 66.67 },
        { rank: 2, dealDate: "2026-07-03", district: "강남구", locality: "역삼동", buildingUse: "업무시설", amountKrw: "10000000", areaM2: "21000", sharePct: 33.33 },
      ],
      districts: [
        { district: "서울", transactionCount: 2, amountKrw: "30000000", areaM2: "41000", sharePct: 100 },
      ],
    },
    quality: {
      sourceRowCount: transactionCount,
      transactionCount,
      uniquePayloadCount: transactionCount,
      exactDuplicateRows: 0,
    },
    scope: {
      geography: "서울특별시",
      source: "국토교통부 실거래 공개시스템",
      population: "용도가 확인된 비주거용 부동산 실거래",
      areaRule: "개별 API 행 건물면적 > 3,300㎡",
      exclusions: ["취소 신고", "주거용", "동일 API payload 중복"],
      amountBasis: "신고 거래금액 · 원 단위 환산",
    },
    largeTransactions: {
      contractVersion: 1,
      minAreaPyeong: 5_000,
      minAreaM2: LARGE_TRANSACTION_MIN_AREA_M2,
      areaBasis: "TRANSACTED_BUILDING_AREA",
      pageSize: 20,
      months: [{
        month: "2026-07",
        baseTransactionCount: transactionCount,
        totalCount: transactionCount,
        coverage: { status: "COMPLETE", expectedDistrictCount: 25, completedDistrictCount: 25 },
        pages: transactionCount === 0 ? [] : [{ page: 1, rows }],
      }],
    },
  };
}

describe("large transactions server query", () => {
  it("uses the pulse eligibility once, includes the 5,000-pyeong boundary, and paginates exact payloads", async () => {
    const client = createClient({ url: "file::memory:" });
    try {
      await createSchema(client);
      await addCoverage(client, "2026-07");
      await addRow(client, {
        id: "threshold",
        area: String(LARGE_TRANSACTION_MIN_AREA_M2),
        month: "07",
        buildingType: null,
      });
      for (let index = 1; index <= 21; index += 1) {
        await addRow(client, {
          id: `large-${index}`,
          area: String(LARGE_TRANSACTION_MIN_AREA_M2 + index * 100),
          month: index % 2 === 0 ? "07" : "7",
          buildingType: index === 1 ? "집합" : "일반",
        });
      }
      await addRow(client, {
        id: "large-1",
        area: String(LARGE_TRANSACTION_MIN_AREA_M2 + 100),
        buildingType: "집합",
      });
      await addRow(client, { id: "below-large", area: String(LARGE_TRANSACTION_MIN_AREA_M2 - 0.01) });
      await addRow(client, { id: "base-only", area: "3300.01" });
      await addRow(client, { id: "bad-area", area: "20000m2" });
      await addRow(client, { id: "residential", area: "22000", use: "공동주택" });

      const first = await getLargeTransactions(
        executor(client),
        { month: "2026-07", page: 1 },
        "dataset-v1",
        new Date("2026-09-10T00:00:00Z"),
      );
      const second = await getLargeTransactions(
        executor(client),
        { month: "2026-07", page: 2 },
        "dataset-v1",
        new Date("2026-09-10T00:00:00Z"),
      );

      expect(first).toMatchObject({
        month: "2026-07",
        totalCount: 22,
        baseTransactionCount: 24,
        page: 1,
        pageSize: 20,
        totalPages: 2,
        coverage: { status: "COMPLETE", completedDistrictCount: 25 },
      });
      expect(first.rows).toHaveLength(20);
      expect(second.rows).toHaveLength(2);
      expect([...first.rows, ...second.rows].map((row) => row.id)).toHaveLength(22);
      expect(new Set([...first.rows, ...second.rows].map((row) => row.id)).size).toBe(22);
      expect(second.rows.at(-1)).toMatchObject({
        id: "threshold",
        address: "강남구 역삼동 7**-*",
        buildingType: null,
        areaPyeong: 5_000,
        amountKrw: "12340000",
      });
      expect(second.rows[0]).toMatchObject({ id: "large-1", buildingType: "집합" });
      expect(first.rows[0].areaM2).toBeGreaterThan(first.rows.at(-1)!.areaM2);
    } finally {
      client.close();
    }
  });

  it("treats partial 25-district coverage as unavailable instead of a valid empty result", async () => {
    const client = createClient({ url: "file::memory:" });
    try {
      await createSchema(client);
      await addCoverage(client, "2026-06", 24);
      await addRow(client, { id: "partial-row", area: "20000", month: "6" });
      await expect(getLargeTransactions(
        executor(client),
        { month: "2026-06", page: 1 },
        "dataset-v1",
        new Date("2026-09-10T00:00:00Z"),
      )).rejects.toBeInstanceOf(LargeTransactionMonthUnavailableError);
    } finally {
      client.close();
    }
  });

  it("rejects the current or future KST month before issuing a database query", async () => {
    const execute = vi.fn<LargeTransactionsSqlExecutor>();
    await expect(getLargeTransactions(
      execute,
      { month: "2026-09", page: 1 },
      "dataset-v1",
      new Date("2026-08-31T15:00:00Z"),
    )).rejects.toBeInstanceOf(LargeTransactionMonthUnavailableError);
    expect(execute).not.toHaveBeenCalled();
  });

  it("rejects a page past the actual result set", async () => {
    const execute = vi.fn<LargeTransactionsSqlExecutor>(async () => ({
      rows: [{
        payload: {
          generatedAt: "2026-09-09T00:00:00Z",
          expectedDistrictCount: 25,
          presentDistrictCount: 25,
          completedDistrictCount: 25,
          baseTransactionCount: 1,
          totalCount: 1,
          rows: [],
        },
      }],
    }));
    await expect(getLargeTransactions(
      execute,
      { month: "2026-07", page: 2 },
      "dataset-v1",
      new Date("2026-09-10T00:00:00Z"),
    )).rejects.toBeInstanceOf(LargeTransactionRequestError);
  });

  it("reads only current-serving rows and keeps the bounded indexed month query", () => {
    expect(largeTransactionsSql).toContain("FROM serving_molit_current_transactions");
    expect(largeTransactionsSql).toContain("serving_molit_completed_partitions");
    expect(largeTransactionsSql).toContain("deal_month_number IN (");
    expect(largeTransactionsSql).toContain("LIMIT ?2 OFFSET ?3");
    expect(largeTransactionsSql).toContain("SELECT DISTINCT api_payload_sha256");
    expect(largeTransactionsSql).not.toMatch(/record_versions|transaction_history|cdealType/u);
  });
});

describe("compact Supabase large transactions adapter", () => {
  it("validates the whole versioned pulse envelope and selects one bounded page", () => {
    const snapshot = normalizeCompactLargeTransactionsPulse(compactPulse(), "dataset-v1");
    expect(getLargeTransactionsFromCompactSnapshot(snapshot, { month: "2026-07", page: 1 }))
      .toMatchObject({
        datasetVersion: "dataset-v1",
        month: "2026-07",
        baseTransactionCount: 2,
        totalCount: 2,
        rows: [{ id: "hash-a" }, { id: "hash-b" }],
      });
  });

  it("keeps a published zero distinct from missing detail or a missing month", () => {
    const zero = normalizeCompactLargeTransactionsPulse(compactPulse(0), "dataset-v1");
    expect(getLargeTransactionsFromCompactSnapshot(zero, { month: "2026-07", page: 1 }))
      .toMatchObject({ totalCount: 0, totalPages: 0, rows: [] });

    const missing = compactPulse();
    delete (missing as { largeTransactions?: unknown }).largeTransactions;
    expect(() => normalizeCompactLargeTransactionsPulse(missing, "dataset-v1"))
      .toThrow(LargeTransactionDetailUnavailableError);
    expect(() => getLargeTransactionsFromCompactSnapshot(zero, { month: "2026-06", page: 1 }))
      .toThrow(LargeTransactionMonthUnavailableError);
    expect(() => getLargeTransactionsFromCompactSnapshot(
      zero,
      { month: "2026-09", page: 1 },
      new Date("2026-08-31T15:00:00Z"),
    )).toThrow(LargeTransactionMonthUnavailableError);
  });

  it("fails closed on version, base-count, ordering, and compact bounds mismatches", () => {
    expect(() => normalizeCompactLargeTransactionsPulse(compactPulse(), "dataset-v2"))
      .toThrow(/version mismatch/u);

    const badCount = compactPulse();
    badCount.largeTransactions.months[0].baseTransactionCount = 1;
    expect(() => normalizeCompactLargeTransactionsPulse(badCount, "dataset-v1"))
      .toThrow(/count lineage/u);

    const badOrder = compactPulse();
    badOrder.largeTransactions.months[0].pages[0].rows.reverse();
    expect(() => normalizeCompactLargeTransactionsPulse(badOrder, "dataset-v1"))
      .toThrow(/rows/u);

    const badFacts = compactPulse();
    badFacts.largeTransactions.months[0].pages[0].rows[0].amountKrw = "30000001";
    expect(() => normalizeCompactLargeTransactionsPulse(badFacts, "dataset-v1"))
      .toThrow(/rows/u);

    const oversizedPage = compactPulse();
    oversizedPage.largeTransactions.months[0].pages[0].rows = Array.from(
      { length: 21 },
      (_, index) => ({ ...oversizedPage.largeTransactions.months[0].pages[0].rows[0], id: `hash-${index}` }),
    );
    expect(() => normalizeCompactLargeTransactionsPulse(oversizedPage, "dataset-v1"))
      .toThrow(/page rows/u);

    const oversizedBytes = compactPulse() as ReturnType<typeof compactPulse> & {
      largeTransactions: ReturnType<typeof compactPulse>["largeTransactions"] & { padding?: string };
    };
    oversizedBytes.largeTransactions.padding = "x".repeat(1024 * 1024);
    expect(() => normalizeCompactLargeTransactionsPulse(oversizedBytes, "dataset-v1"))
      .toThrow(/size/u);
  });
});
