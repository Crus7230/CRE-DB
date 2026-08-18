import { describe, expect, it } from "vitest";
import { parseCompanyParams } from "@/lib/intelligence-contract";

describe("parseCompanyParams", () => {
  it("parses a tenant-signal industry request", () => {
    expect(parseCompanyParams(new URLSearchParams({
      view: "TENANT_SIGNALS", industry: "반도체 제조업", q: "삼성", limit: "30",
    }))).toEqual({ view: "TENANT_SIGNALS", industry: "반도체 제조업", q: "삼성", limit: 30 });
  });

  it("falls back to the safe overall view and caps limit", () => {
    expect(parseCompanyParams(new URLSearchParams({ view: "RAW_SQL", limit: "999" }))).toEqual({
      view: "OVERALL", industry: "", q: "", limit: 100,
    });
  });
});
