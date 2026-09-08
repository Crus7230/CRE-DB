import { describe, expect, it } from "vitest";
import { parseContextualSearchParams } from "@/lib/contextual-search-contract";

describe("contextual search contract", () => {
  it("defaults to approved-only results and parses relationship filters", () => {
    const params = new URLSearchParams({
      q: "우협 선정",
      role: "BUYER",
      assetId: "asset-1",
      region: "SEOUL_CBD",
      industry: "AI",
      impact: "INCREASE",
      from: "2026-01-01",
      to: "2026-09-03",
    });

    expect(parseContextualSearchParams(params)).toEqual({
      q: "우협 선정",
      mode: "APPROVED",
      domain: "",
      eventType: "",
      stage: "",
      processType: "",
      role: "BUYER",
      participantEntityId: "",
      assetId: "asset-1",
      region: "SEOUL_CBD",
      industry: "AI",
      impact: "INCREASE",
      sourceGrade: "",
      from: "2026-01-01",
      to: "2026-09-03",
      page: 1,
      pageSize: 50,
    });
  });

  it("requires explicit valid modes and validates dates and pagination", () => {
    expect(parseContextualSearchParams(new URLSearchParams("mode=CANDIDATE&pageSize=100"))).toMatchObject({
      mode: "CANDIDATE",
      pageSize: 100,
    });
    expect(parseContextualSearchParams(new URLSearchParams("mode=LEGACY"))).toMatchObject({ mode: "LEGACY" });
    expect(() => parseContextualSearchParams(new URLSearchParams("mode=ALL"))).toThrow("mode");
    expect(() => parseContextualSearchParams(new URLSearchParams("from=2026-09-04&to=2026-09-03"))).toThrow("date");
    expect(() => parseContextualSearchParams(new URLSearchParams("from=2026-99-99"))).toThrow("date");
    expect(() => parseContextualSearchParams(new URLSearchParams("page=0"))).toThrow("page");
    expect(() => parseContextualSearchParams(new URLSearchParams("pageSize=101"))).toThrow("pageSize");
    expect(() => parseContextualSearchParams(new URLSearchParams({ q: "x".repeat(201) }))).toThrow("q");
  });
});
