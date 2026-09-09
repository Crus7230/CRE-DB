import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { loadAddress, searchAddresses } from "@/lib/server/smart-lookup-address";
import { LookupProviderError, type LookupContext } from "@/lib/server/smart-lookup-types";

const ORDINARY_PNU = "1168010100101230004";
const MOUNTAIN_PNU = "1111018300201970001";
const ORDINARY_IDENTITY = {
  pnu: ORDINARY_PNU,
  legalDongCode: "1168010100",
  sigunguCd: "11680",
  bjdongCd: "10100",
  platGbCd: "0",
  bun: "0123",
  ji: "0004",
  roadAddress: "서울특별시 강남구 테헤란로 152",
  parcelAddress: "서울특별시 강남구 역삼동 123-4",
};

function context(
  requestJson: LookupContext["requestJson"],
  credentials: LookupContext["credentials"] = {
    vworldKey: "vworld-test-key",
    publicDataKey: "public-test-key",
  },
): LookupContext {
  return {
    credentials,
    requestJson,
    requestBytes: vi.fn(async () => new Uint8Array()),
    now: () => new Date("2026-09-08T09:00:00.000Z"),
  };
}

function vworldPayload(items: unknown[]) {
  return {
    response: {
      status: "OK",
      result: { items },
    },
  };
}

function registerPayload(items: unknown, totalCount?: number, resultCode = "00", resultMsg = "NORMAL SERVICE.") {
  return {
    response: {
      header: { resultCode, resultMsg },
      body: {
        items: Array.isArray(items) && items.length === 0 ? "" : { item: items },
        totalCount: totalCount ?? (Array.isArray(items) ? items.length : 1),
        pageNo: 1,
        numOfRows: 100,
      },
    },
  };
}

function field(card: { fields: Array<{ label: string; value: string }> }, label: string) {
  return card.fields.find((item) => item.label === label)?.value;
}

describe("VWorld address candidates", () => {
  it("reports an unconfigured source without issuing a request when the VWorld key is absent", async () => {
    const requestJson = vi.fn<LookupContext["requestJson"]>();

    const result = await searchAddresses("서울시 중구 세종대로 110", context(requestJson, {}));

    expect(result.candidates).toEqual([]);
    expect(result.sources).toMatchObject([{ id: "vworld-address", status: "unconfigured" }]);
    expect(requestJson).not.toHaveBeenCalled();
  });

  it("searches road and parcel addresses, deduplicates by PNU, and derives official parcel parameters", async () => {
    const requestedCategories: string[] = [];
    const requestJson = vi.fn<LookupContext["requestJson"]>(async (rawUrl) => {
      const url = new URL(rawUrl);
      requestedCategories.push(url.searchParams.get("category") ?? "");
      expect(url.origin).toBe("https://api.vworld.kr");
      expect(url.pathname).toBe("/req/search");
      expect(url.searchParams.get("type")).toBe("address");
      expect(url.searchParams.get("query")).toBe("서울 강남구 테헤란로 152");
      if (url.searchParams.get("category") === "road") {
        return vworldPayload([
          {
            id: ORDINARY_PNU,
            title: "서울특별시 강남구 <b>테헤란로</b> 152",
            address: {
              road: "서울특별시 강남구 테헤란로 152",
              parcel: "서울특별시 강남구 역삼동 123-4",
            },
            point: { x: "127.036", y: "37.500" },
          },
        ]);
      }
      return vworldPayload([
        {
          id: ORDINARY_PNU,
          title: "서울특별시 강남구 역삼동 123-4",
          address: {
            road: "서울특별시 강남구 테헤란로 152",
            parcel: "서울특별시 강남구 역삼동 123-4",
          },
        },
        {
          id: MOUNTAIN_PNU,
          title: "서울특별시 종로구 산지번",
          address: { parcel: "서울특별시 종로구 구기동 산 197-1" },
        },
        { id: "not-a-pnu", title: "근거 없는 후보", address: {} },
      ]);
    });

    const result = await searchAddresses(" 서울 강남구 테헤란로 152 ", context(requestJson));

    expect(requestedCategories.sort()).toEqual(["parcel", "road"]);
    expect(result.sources[0].status).toBe("ok");
    expect(result.candidates).toHaveLength(2);
    expect(result.candidates[0]).toMatchObject({
      kind: "address",
      title: "서울특별시 강남구 테헤란로 152",
      identity: {
        pnu: ORDINARY_PNU,
        legalDongCode: "1168010100",
        sigunguCd: "11680",
        bjdongCd: "10100",
        platGbCd: "0",
        bun: "0123",
        ji: "0004",
      },
    });
    expect(result.candidates[1].identity).toMatchObject({
      pnu: MOUNTAIN_PNU,
      legalDongCode: "1111018300",
      platGbCd: "1",
      bun: "0197",
      ji: "0001",
    });
  });

  it("distinguishes an empty VWorld result from a timeout", async () => {
    const empty = await searchAddresses("없는 주소 999", context(vi.fn(async () => ({
      response: { status: "NOT_FOUND" },
    }))));
    expect(empty.sources[0].status).toBe("empty");
    expect(empty.message).toContain("일치하는");

    const timedOut = await searchAddresses("서울시청 세종대로 110", context(vi.fn(async () => {
      throw new LookupProviderError("timeout");
    })));
    expect(timedOut.sources[0].status).toBe("timeout");
    expect(timedOut.message).toContain("초과");
  });

  it("keeps confirmed address candidates while retaining a partial timeout status", async () => {
    const requestJson = vi.fn<LookupContext["requestJson"]>(async (rawUrl) => {
      const url = new URL(rawUrl);
      if (url.searchParams.get("category") === "parcel") throw new LookupProviderError("timeout");
      return vworldPayload([{
        id: ORDINARY_PNU,
        address: { road: "서울특별시 강남구 테헤란로 152", parcel: "서울특별시 강남구 역삼동 123-4" },
      }]);
    });

    const result = await searchAddresses("서울 강남구 테헤란로 152", context(requestJson));

    expect(result.candidates).toHaveLength(1);
    expect(result.sources[0].status).toBe("timeout");
    expect(result.message).toContain("일부");
  });
});

describe("Building HUB address detail", () => {
  it("does not query Building HUB without its separately approved public-data key", async () => {
    const requestJson = vi.fn<LookupContext["requestJson"]>();

    const result = await loadAddress(ORDINARY_IDENTITY, context(requestJson, { vworldKey: "vworld-test-key" }));

    expect(result.sources.map((item) => item.status)).toEqual(["ok", "unconfigured"]);
    expect(result.cards).toEqual([]);
    expect(requestJson).not.toHaveBeenCalled();
  });

  it("returns the site recap and every building title as separate compact cards", async () => {
    const requestJson = vi.fn<LookupContext["requestJson"]>(async (rawUrl) => {
      const url = new URL(rawUrl);
      expect(url.origin).toBe("https://apis.data.go.kr");
      expect(url.searchParams.get("sigunguCd")).toBe("11680");
      expect(url.searchParams.get("bjdongCd")).toBe("10100");
      expect(url.searchParams.get("platGbCd")).toBe("0");
      expect(url.searchParams.get("bun")).toBe("0123");
      expect(url.searchParams.get("ji")).toBe("0004");
      expect(url.searchParams.get("_type")).toBe("json");
      expect(url.searchParams.get("serviceKey")).toBe("encoded+test=");
      if (url.pathname.endsWith("/getBrRecapTitleInfo")) {
        return registerPayload({
          mgmBldrgstPk: "recap-pk",
          bldNm: "테헤란 업무시설",
          platPlc: "서울특별시 강남구 역삼동 123-4",
          newPlatPlc: "서울특별시 강남구 테헤란로 152",
          mainPurpsCdNm: "업무시설",
          totArea: "0",
          platArea: null,
          useAprDay: "20010102",
          bcRat: "0",
          vlRat: "250.5",
          crtnDay: "20260901",
        });
      }
      return registerPayload([
        {
          mgmBldrgstPk: "title-a",
          bldNm: "테헤란 업무시설",
          dongNm: "A동",
          newPlatPlc: "서울특별시 강남구 테헤란로 152",
          mainPurpsCdNm: "업무시설",
          totArea: 0,
          platArea: "",
          grndFlrCnt: "0",
          ugrndFlrCnt: "2",
          useAprDay: "20010102",
          bcRat: 0,
          vlRat: "0",
          crtnDay: "20260902",
        },
        {
          mgmBldrgstPk: "title-b",
          bldNm: "테헤란 업무시설",
          dongNm: "B동",
          newPlatPlc: "서울특별시 강남구 테헤란로 152",
          etcPurps: "판매시설",
          totArea: "12345.678",
          platArea: "4567.8",
          grndFlrCnt: "12",
          ugrndFlrCnt: "3",
          useAprDay: null,
          bcRat: "59.25",
          vlRat: "420.75",
          crtnDay: "20260903",
        },
      ]);
    });

    const result = await loadAddress(
      ORDINARY_IDENTITY,
      context(requestJson, { vworldKey: "vworld-test-key", publicDataKey: "encoded%2Btest%3D" }),
    );

    expect(requestJson).toHaveBeenCalledTimes(2);
    expect(result.sources[1]).toMatchObject({ status: "ok", asOf: "2026-09-03" });
    expect(result.cards).toHaveLength(3);
    expect(result.cards.map((card) => card.title)).toEqual([
      "테헤란 업무시설",
      "테헤란 업무시설 · A동",
      "테헤란 업무시설 · B동",
    ]);
    expect(field(result.cards[0], "연면적")).toBe("0㎡");
    expect(field(result.cards[0], "대지면적")).toBe("정보 없음");
    expect(field(result.cards[1], "층수")).toBe("지상 0층 · 지하 2층");
    expect(field(result.cards[2], "연면적")).toBe("12,345.68㎡");
    expect(field(result.cards[2], "사용승인일")).toBe("정보 없음");
    expect(result.cards[1].note).toContain("각 동을 별도 카드");
  });

  it("keeps a normal title result when the optional site recap is normally empty", async () => {
    const requestJson = vi.fn<LookupContext["requestJson"]>(async (rawUrl) => {
      const url = new URL(rawUrl);
      if (url.pathname.endsWith("/getBrRecapTitleInfo")) return registerPayload([], 0);
      return registerPayload({
        mgmBldrgstPk: "seoul-city-hall-annex",
        bldNm: "서울특별시청 신청사",
        mainPurpsCdNm: "업무시설",
        totArea: "83625.55",
        grndFlrCnt: "13",
        ugrndFlrCnt: "5",
        useAprDay: "20120831",
      });
    });

    const result = await loadAddress(ORDINARY_IDENTITY, context(requestJson));

    expect(result.sources[1].status).toBe("ok");
    expect(result.cards).toHaveLength(1);
    expect(field(result.cards[0], "주용도")).toBe("업무시설");
    expect(field(result.cards[0], "연면적")).toBe("83,625.55㎡");
    expect(field(result.cards[0], "층수")).toBe("지상 13층 · 지하 5층");
    expect(field(result.cards[0], "사용승인일")).toBe("2012-08-31");
  });

  it("distinguishes service approval failure, normal empty data, and timeout", async () => {
    const denied = await loadAddress(ORDINARY_IDENTITY, context(vi.fn(async () => (
      registerPayload([], 0, "30", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR")
    ))));
    expect(denied.sources[1].status).toBe("unconfigured");
    expect(denied.message).toContain("승인");

    const empty = await loadAddress(ORDINARY_IDENTITY, context(vi.fn(async () => registerPayload([], 0))));
    expect(empty.sources[1].status).toBe("empty");
    expect(empty.message).toContain("공개된 표제부");

    const timedOut = await loadAddress(ORDINARY_IDENTITY, context(vi.fn(async () => {
      throw new LookupProviderError("timeout");
    })));
    expect(timedOut.sources[1].status).toBe("timeout");
    expect(timedOut.message).toContain("초과");
  });

  it("does not mislabel an upstream HTTP failure as a missing service approval", async () => {
    const unavailable = await loadAddress(ORDINARY_IDENTITY, context(vi.fn(async () => {
      throw new LookupProviderError("http");
    })));

    expect(unavailable.sources[1].status).toBe("error");
    expect(unavailable.message).toContain("연결");
    expect(unavailable.message).not.toContain("승인");
  });

  it("fails closed before any request when signed identity fields do not match the PNU", async () => {
    const requestJson = vi.fn<LookupContext["requestJson"]>();

    const result = await loadAddress(
      { ...ORDINARY_IDENTITY, platGbCd: "1" },
      context(requestJson),
    );

    expect(result.sources[0].status).toBe("error");
    expect(result.message).toContain("다시 선택");
    expect(requestJson).not.toHaveBeenCalled();
  });

  it("keeps valid title cards when the optional recap operation is not approved", async () => {
    const requestJson = vi.fn<LookupContext["requestJson"]>(async (rawUrl) => {
      const url = new URL(rawUrl);
      if (url.pathname.endsWith("/getBrRecapTitleInfo")) {
        return registerPayload([], 0, "20", "SERVICE_ACCESS_DENIED_ERROR");
      }
      return registerPayload({
        mgmBldrgstPk: "title-only",
        dongNm: "본동",
        totArea: "100",
      });
    });

    const result = await loadAddress(ORDINARY_IDENTITY, context(requestJson));

    expect(result.sources[1].status).toBe("unconfigured");
    expect(result.cards).toHaveLength(1);
    expect(result.message).toContain("일부");
  });
});
