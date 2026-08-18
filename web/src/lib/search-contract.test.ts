import { describe, expect, it } from "vitest";
import { parseSearchParams } from "@/lib/search-contract";

describe("parseSearchParams", () => {
  it("normalizes a valid market search request", () => {
    const params = new URLSearchParams({
      q: "  데이터센터 PF  ",
      kind: "EVENT",
      category: "PF",
      from: "2025-01-01",
      to: "2026-08-18",
      page: "2",
      pageSize: "25",
    });

    expect(parseSearchParams(params)).toEqual({
      q: "데이터센터 PF",
      kind: "EVENT",
      category: "PF",
      from: "2025-01-01",
      to: "2026-08-18",
      page: 2,
      pageSize: 25,
      includeTransactionsUnder1000Eok: false,
    });
  });

  it("falls back safely for invalid filters and caps page size", () => {
    const params = new URLSearchParams({
      kind: "DROP TABLE",
      from: "2025-99-99",
      page: "-5",
      pageSize: "5000",
    });

    expect(parseSearchParams(params)).toEqual({
      q: "",
      kind: "ALL",
      category: "",
      from: null,
      to: null,
      page: 1,
      pageSize: 50,
      includeTransactionsUnder1000Eok: false,
    });
  });

  it("only includes sub-1000억원 transactions when explicitly requested", () => {
    expect(parseSearchParams(new URLSearchParams({ includeTransactionsUnder1000Eok: "true" })).includeTransactionsUnder1000Eok).toBe(true);
  });
});
