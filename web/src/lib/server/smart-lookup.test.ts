// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("@/lib/server/smart-lookup-address", () => ({ searchAddresses: vi.fn(), loadAddress: vi.fn() }));
vi.mock("@/lib/server/smart-lookup-company", () => ({ searchCompanies: vi.fn(), loadCompany: vi.fn() }));
import { detectLookupKind } from "@/lib/smart-lookup-contract";
import { signSelection, verifySelection, validateLookupRequest, runSmartLookup } from "./smart-lookup";
import { searchAddresses, loadAddress } from "./smart-lookup-address";
import { searchCompanies } from "./smart-lookup-company";
import type { LookupContext, ProviderCandidate } from "./smart-lookup-types";

const item: ProviderCandidate = { kind: "address", title: "서울특별시 중구 세종대로 110", subtitle: "서울시청", sourceLabel: "VWorld", identity: { pnu: "1114010300100310000" } };
const secret = "a-local-test-secret-of-at-least-32-characters";
const now = Date.parse("2026-09-08T12:00:00Z");
const context: LookupContext = { credentials: {}, now: () => new Date(now), requestJson: vi.fn(), requestBytes: vi.fn() };

describe("smart lookup input and signed selection", () => {
  it("keeps ambiguous company and building names undecided", () => {
    expect(detectLookupKind("삼성전자")).toBe("auto");
    expect(detectLookupKind("파르나스타워")).toBe("auto");
    expect(detectLookupKind("세종대로 110")).toBe("address");
    expect(detectLookupKind("005930")).toBe("company");
  });
  it("rejects malformed, giant and control-character queries", () => {
    for (const value of [null, [], { query: "a" }, { query: "ab\ncd" }, { query: "가".repeat(101) }, { query: "서울", kind: "url" }]) {
      expect(() => validateLookupRequest(value)).toThrow();
    }
    expect(validateLookupRequest({ query: " 서울  시청 " })).toEqual({ query: "서울 시청", kind: "auto", selection: undefined });
  });
  it("binds selection to query, subject, expiry and signing secret", () => {
    const token = signSelection(item, "서울시청", "user-a", secret, now);
    expect(verifySelection(token, "서울시청", "user-a", secret, now)).toEqual(item);
    for (const args of [[token, "다른검색", "user-a", secret, now], [token, "서울시청", "user-b", secret, now], [token, "서울시청", "user-a", "bad", now], [token, "서울시청", "user-a", secret, now + 901000], [`${token}x`, "서울시청", "user-a", secret, now]] as const) {
      expect(() => verifySelection(args[0], args[1], args[2], args[3], args[4])).toThrow(/다시 검색/);
    }
  });
  it("returns both domains as candidates without choosing the first match", async () => {
    vi.mocked(searchAddresses).mockResolvedValue({ candidates: [item], cards: [], sources: [{ id: "vworld", label: "주소", status: "ok" }] });
    vi.mocked(searchCompanies).mockResolvedValue({ candidates: [{ ...item, kind: "company", title: "시청회사", identity: { corpCode: "12345678" } }], cards: [], sources: [{ id: "dart", label: "기업", status: "ok" }] });
    const result = await runSmartLookup({ query: "통합후보검증", kind: "auto" }, context, "user-a", secret);
    expect(result.stage).toBe("candidates");
    expect(result.candidates).toHaveLength(2);
    expect(result.cards).toEqual([]);
    expect(result.candidates[0]).not.toHaveProperty("identity");
    expect(loadAddress).not.toHaveBeenCalled();
  });
  it("does not disguise provider failure as no matching result", async () => {
    vi.mocked(searchCompanies).mockRejectedValue(new Error("secret-key-bearing-native-error"));
    const result = await runSmartLookup({ query: "오류검증회사", kind: "company" }, context, "user-a", secret);
    expect(result.stage).toBe("unavailable");
    expect(JSON.stringify(result)).not.toContain("secret-key");
  });
  it("keeps partial detail cards but does not cache a failed source", async () => {
    vi.mocked(loadAddress).mockClear();
    vi.mocked(loadAddress).mockResolvedValue({
      candidates: [],
      cards: [{
        id: "building-title:1",
        title: "확인된 표제부",
        sourceLabel: "건축물대장",
        fields: [{ label: "주용도", value: "업무시설" }],
      }],
      sources: [
        { id: "vworld", label: "주소", status: "ok" },
        { id: "building", label: "건축물대장", status: "timeout" },
      ],
    });
    const query = "부분상세캐시검증";
    const selection = signSelection(item, query, "user-a", secret, now);

    const first = await runSmartLookup({ query, kind: "address", selection }, context, "user-a", secret);
    const second = await runSmartLookup({ query, kind: "address", selection }, context, "user-a", secret);

    expect(first.stage).toBe("detail");
    expect(first.cards).toHaveLength(1);
    expect(second.cacheHit).toBe(false);
    expect(loadAddress).toHaveBeenCalledTimes(2);
  });
});
