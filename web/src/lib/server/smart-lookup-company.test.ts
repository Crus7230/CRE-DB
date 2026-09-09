import { describe, expect, it, vi } from "vitest";

import { loadCompany, searchCompanies } from "@/lib/server/smart-lookup-company";
import { LookupProviderError, type LookupContext } from "@/lib/server/smart-lookup-types";

const NOW = new Date("2026-09-08T01:00:00.000Z");

function storedZip(filename: string, contents: string): Uint8Array {
  const name = Buffer.from(filename, "utf8");
  const data = Buffer.from(contents, "utf8");
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0);
  local.writeUInt16LE(20, 4);
  local.writeUInt16LE(0, 6);
  local.writeUInt16LE(0, 8);
  local.writeUInt32LE(0, 10);
  local.writeUInt32LE(0, 14);
  local.writeUInt32LE(data.length, 18);
  local.writeUInt32LE(data.length, 22);
  local.writeUInt16LE(name.length, 26);
  local.writeUInt16LE(0, 28);

  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0);
  central.writeUInt16LE(20, 4);
  central.writeUInt16LE(20, 6);
  central.writeUInt16LE(0, 8);
  central.writeUInt16LE(0, 10);
  central.writeUInt32LE(0, 12);
  central.writeUInt32LE(0, 16);
  central.writeUInt32LE(data.length, 20);
  central.writeUInt32LE(data.length, 24);
  central.writeUInt16LE(name.length, 28);
  central.writeUInt16LE(0, 30);
  central.writeUInt16LE(0, 32);
  central.writeUInt16LE(0, 34);
  central.writeUInt16LE(0, 36);
  central.writeUInt32LE(0, 38);
  central.writeUInt32LE(0, 42);

  const centralOffset = local.length + name.length + data.length;
  const centralSize = central.length + name.length;
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(0, 4);
  eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(1, 8);
  eocd.writeUInt16LE(1, 10);
  eocd.writeUInt32LE(centralSize, 12);
  eocd.writeUInt32LE(centralOffset, 16);
  eocd.writeUInt16LE(0, 20);
  return Buffer.concat([local, name, data, central, name, eocd]);
}

function corpCodeZip(): Uint8Array {
  return storedZip("CORPCODE.xml", `<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><corp_eng_name>SAMSUNG ELECTRONICS CO., LTD</corp_eng_name><stock_code>005930</stock_code><modify_date>20260901</modify_date></list>
  <list><corp_code>00000011</corp_code><corp_name>테스트회사</corp_name><corp_eng_name>TEST COMPANY ONE</corp_eng_name><stock_code>123456</stock_code><modify_date>20260831</modify_date></list>
  <list><corp_code>00000022</corp_code><corp_name>테스트회사</corp_name><corp_eng_name>TEST COMPANY TWO</corp_eng_name><stock_code></stock_code><modify_date>20260830</modify_date></list>
</result>`);
}

function context(overrides: Partial<LookupContext> = {}): LookupContext {
  return {
    credentials: { dartKey: "dart-test-key", krxKey: "krx-test-key" },
    requestJson: vi.fn(async () => { throw new Error("unexpected JSON request"); }),
    requestBytes: vi.fn(async () => corpCodeZip()),
    now: () => NOW,
    ...overrides,
  };
}

function dartCompanyResponse(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    status: "000",
    corp_name: "삼성전자",
    corp_name_eng: "SAMSUNG ELECTRONICS CO., LTD",
    stock_name: "삼성전자",
    stock_code: "005930",
    ceo_nm: "대표이사",
    corp_cls: "Y",
    adres: "경기도 수원시",
    induty_code: "264",
    est_dt: "19690113",
    acc_mt: "12",
    ...overrides,
  };
}

function dartDisclosureResponse(): Record<string, unknown> {
  return {
    status: "000",
    list: [{
      rcept_no: "20260908000001",
      rcept_dt: "20260908",
      report_nm: "주요사항보고서",
      flr_nm: "삼성전자",
    }],
  };
}

function krxRow(stockCode = "005930"): Record<string, string> {
  return {
    ISU_CD: "KR7005930003",
    ISU_SRT_CD: stockCode,
    ISU_NM: "삼성전자보통주",
    ISU_ABBRV: "삼성전자",
    ISU_ENG_NM: "SamsungElec",
    LIST_DD: "19750611",
    MKT_TP_NM: "KOSPI",
    SECUGRP_NM: "주권",
    SECT_TP_NM: "보통주",
    KIND_STKCERT_TP_NM: "보통주",
    PARVAL: "100",
    LIST_SHRS: "5969782550",
  };
}

describe("official company smart lookup", () => {
  it("reports an unconfigured OpenDART source without making a request", async () => {
    const requestBytes = vi.fn(async () => corpCodeZip());
    const result = await searchCompanies("삼성전자", context({
      credentials: {},
      requestBytes,
    }));

    expect(requestBytes).not.toHaveBeenCalled();
    expect(result.candidates).toEqual([]);
    expect(result.sources).toEqual([expect.objectContaining({ id: "dart-corp-codes", status: "unconfigured" })]);
  });

  it("finds a stock code and exposes enough identity to distinguish same-name companies", async () => {
    const lookupContext = context({ credentials: { dartKey: "candidate-key" } });

    const stockResult = await searchCompanies("005930", lookupContext);
    const duplicateResult = await searchCompanies("테스트회사", lookupContext);

    expect(stockResult.candidates).toEqual([
      expect.objectContaining({
        kind: "company",
        title: "삼성전자",
        identity: expect.objectContaining({ corpCode: "00126380", stockCode: "005930" }),
      }),
    ]);
    expect(stockResult.sources[0].asOf).toBeUndefined();
    expect(duplicateResult.candidates).toHaveLength(2);
    expect(duplicateResult.candidates.map((candidate) => candidate.identity.corpCode)).toEqual(["00000011", "00000022"]);
    expect(duplicateResult.candidates[0].subtitle).toContain("종목 123456");
    expect(duplicateResult.candidates[1].subtitle).toContain("비상장");
    expect(lookupContext.requestBytes).toHaveBeenCalledOnce();
  });

  it("single-flights the first corp-code download and reuses the bounded TTL cache", async () => {
    let resolveBytes: ((bytes: Uint8Array) => void) | undefined;
    const requestBytes = vi.fn(() => new Promise<Uint8Array>((resolve) => { resolveBytes = resolve; }));
    const lookupContext = context({
      credentials: { dartKey: "singleflight-key" },
      requestBytes,
    });

    const first = searchCompanies("005930", lookupContext);
    const second = searchCompanies("삼성전자", lookupContext);
    expect(requestBytes).toHaveBeenCalledOnce();
    resolveBytes?.(corpCodeZip());

    await expect(Promise.all([first, second])).resolves.toEqual([
      expect.objectContaining({ candidates: [expect.objectContaining({ title: "삼성전자" })] }),
      expect.objectContaining({ candidates: [expect.objectContaining({ title: "삼성전자" })] }),
    ]);
    await searchCompanies("005930", lookupContext);
    expect(requestBytes).toHaveBeenCalledOnce();
  });

  it("keeps a known-good corp-code snapshot when a refresh fails inside the stale bound", async () => {
    let now = NOW;
    const requestBytes = vi.fn()
      .mockResolvedValueOnce(corpCodeZip())
      .mockRejectedValueOnce(new LookupProviderError("timeout"));
    const lookupContext = context({
      credentials: { dartKey: "stale-key" },
      requestBytes,
      now: () => now,
    });

    await searchCompanies("005930", lookupContext);
    now = new Date(NOW.getTime() + 7 * 60 * 60 * 1_000);
    const stale = await searchCompanies("005930", lookupContext);

    expect(stale.candidates[0].title).toBe("삼성전자");
    expect(stale.sources[0]).toMatchObject({ status: "error" });
    expect(stale.sources[0].message).toContain("이전 수신 목록");
    expect(requestBytes).toHaveBeenCalledTimes(2);
  });

  it("loads company overview, recent disclosures, and a prior KRX business-day snapshot", async () => {
    const requestedUrls: string[] = [];
    const requestJson = vi.fn(async (input: string, init?: RequestInit): Promise<unknown> => {
      requestedUrls.push(input);
      const url = new URL(input);
      if (url.pathname.endsWith("/company.json")) return dartCompanyResponse();
      if (url.pathname.endsWith("/list.json")) return dartDisclosureResponse();
      expect(init?.headers).toMatchObject({ AUTH_KEY: "krx-detail-key" });
      if (url.searchParams.get("basDd") === "20260907") return { OutBlock_1: [] };
      if (url.searchParams.get("basDd") === "20260904") return { OutBlock_1: [krxRow()] };
      throw new Error("unexpected KRX date");
    });
    const result = await loadCompany({ corpCode: "00126380", stockCode: "005930" }, context({
      credentials: { dartKey: "dart-detail-key", krxKey: "krx-detail-key" },
      requestJson,
    }));

    expect(result.cards.map((card) => card.id)).toEqual([
      "dart-company-00126380",
      "dart-disclosures-00126380",
      "krx-security-005930",
    ]);
    expect(result.sources).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "dart-company", status: "ok" }),
      expect.objectContaining({ id: "dart-disclosures", status: "ok" }),
      expect.objectContaining({ id: "krx-security", status: "ok", asOf: "2026-09-04" }),
    ]));
    const krxCard = result.cards.find((card) => card.id === "krx-security-005930");
    expect(krxCard).toMatchObject({
      sourceLabel: "KRX 종목 기본정보",
      asOf: "2026-09-04",
      note: "실시간 주가가 아닌 기준일 종목 기본정보입니다.",
    });
    expect(result.sources.find((item) => item.id === "krx-security")?.message).toContain("최근 기준일 자료가 없어");
    expect(result.sources.find((item) => item.id === "krx-security")?.message).not.toContain("휴장일");
    expect(result.cards[1].links?.[0].label).toBe("2026-09-08 · 주요사항보고서");
    expect(result.cards[1].links?.[0].url).toBe("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260908000001");
    expect(JSON.stringify(result)).not.toContain("dart-detail-key");
    expect(JSON.stringify(result)).not.toContain("krx-detail-key");
    expect(requestedUrls.filter((url) => url.includes("data-dbg.krx.co.kr"))).toHaveLength(2);
  });

  it("distinguishes a valid KRX market response that does not contain the selected security", async () => {
    const requestJson = vi.fn(async (input: string): Promise<unknown> => {
      const url = new URL(input);
      if (url.pathname.endsWith("/company.json")) return dartCompanyResponse();
      if (url.pathname.endsWith("/list.json")) return dartDisclosureResponse();
      return { OutBlock_1: [krxRow("000001")] };
    });
    const result = await loadCompany({ corpCode: "00126380", stockCode: "005930" }, context({
      credentials: { dartKey: "dart-missing-security", krxKey: "krx-missing-security" },
      requestJson,
    }));

    expect(result.sources.find((item) => item.id === "krx-security")).toMatchObject({ status: "empty" });
    expect(result.sources.find((item) => item.id === "krx-security")?.message).toContain("시장 자료는 수신됐지만");
    expect(result.cards.some((card) => card.id.startsWith("krx-security"))).toBe(false);
    expect(requestJson.mock.calls.filter(([url]) => String(url).includes("data-dbg.krx.co.kr"))).toHaveLength(1);
  });

  it("distinguishes a missing KRX key from an upstream approval or connection failure", async () => {
    const baseJson = async (input: string): Promise<unknown> => {
      const url = new URL(input);
      if (url.pathname.endsWith("/company.json")) return dartCompanyResponse();
      if (url.pathname.endsWith("/list.json")) return dartDisclosureResponse();
      throw new Error("upstream payload must not leak");
    };
    const unconfigured = await loadCompany({ corpCode: "00126380", stockCode: "005930" }, context({
      credentials: { dartKey: "dart-only-key" },
      requestJson: vi.fn(baseJson),
    }));
    const failed = await loadCompany({ corpCode: "00126380", stockCode: "005930" }, context({
      credentials: { dartKey: "dart-failure-key", krxKey: "krx-failure-key" },
      requestJson: vi.fn(baseJson),
    }));

    expect(unconfigured.sources.find((item) => item.id === "krx-security")).toMatchObject({ status: "unconfigured" });
    expect(failed.sources.find((item) => item.id === "krx-security")).toMatchObject({ status: "error" });
    expect(failed.sources.find((item) => item.id === "krx-security")?.message).toContain("승인 또는 연결 상태");
    expect(JSON.stringify(failed)).not.toContain("upstream payload");
  });

  it("preserves completed official cards when the remaining source reaches the shared request deadline", async () => {
    const requestJson = vi.fn(async (input: string): Promise<unknown> => {
      const url = new URL(input);
      if (url.pathname.endsWith("/company.json")) return dartCompanyResponse();
      if (url.pathname.endsWith("/list.json")) return dartDisclosureResponse();
      throw new LookupProviderError("timeout");
    });
    const result = await loadCompany({ corpCode: "00126380", stockCode: "005930" }, context({
      credentials: { dartKey: "dart-deadline-key", krxKey: "krx-deadline-key" },
      requestJson,
    }));

    expect(result.cards.map((card) => card.id)).toEqual([
      "dart-company-00126380",
      "dart-disclosures-00126380",
    ]);
    expect(result.sources.find((item) => item.id === "dart-company")).toMatchObject({ status: "ok" });
    expect(result.sources.find((item) => item.id === "dart-disclosures")).toMatchObject({ status: "ok" });
    expect(result.sources.find((item) => item.id === "krx-security")).toMatchObject({ status: "timeout" });
    expect(result.message).toBeUndefined();
  });

  it("preserves recent disclosures when the company overview times out", async () => {
    const requestJson = vi.fn(async (input: string): Promise<unknown> => {
      const url = new URL(input);
      if (url.pathname.endsWith("/company.json")) throw new LookupProviderError("timeout");
      if (url.pathname.endsWith("/list.json")) return dartDisclosureResponse();
      throw new Error("KRX must not run without a verified market class");
    });
    const result = await loadCompany({ corpCode: "00126380", stockCode: "005930" }, context({
      credentials: { dartKey: "dart-partial-key" },
      requestJson,
    }));

    expect(result.cards.map((card) => card.id)).toEqual(["dart-disclosures-00126380"]);
    expect(result.sources.find((item) => item.id === "dart-company")).toMatchObject({ status: "timeout" });
    expect(result.sources.find((item) => item.id === "dart-disclosures")).toMatchObject({ status: "ok" });
  });

  it("maps a DART no-data response to empty without presenting it as a connection error", async () => {
    const requestJson = vi.fn(async () => ({ status: "013", message: "upstream text" }));
    const result = await loadCompany({ corpCode: "00126380" }, context({
      credentials: { dartKey: "dart-empty-key" },
      requestJson,
    }));

    expect(result.sources.find((item) => item.id === "dart-company")).toMatchObject({ status: "empty" });
    expect(result.sources.find((item) => item.id === "dart-disclosures")).toMatchObject({ status: "empty" });
    expect(JSON.stringify(result)).not.toContain("upstream text");
  });
});
