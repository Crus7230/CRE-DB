import { describe, expect, it } from "vitest";
import {
  normalizePermitTimeseries,
  parsePermitTimeseriesRequest,
  PermitRequestError,
} from "@/lib/permit-timeseries-contract";

const payload = {
  generatedAt: "2026-09-08T05:00:00Z",
  sourceAsOfDate: "2026-09-07",
  availableFrom: "2000-01",
  availableThrough: "2026-08",
  selectedFrom: "2021-09",
  selectedThrough: "2026-08",
  groupBy: "EVENT_TYPE",
  filters: { eventType: null, assetType: null, district: null, constructionAction: null },
  source: { code: "src_seoul_building_permit", label: "서울 열린데이터광장" },
  scope: {
    status: "IN_SCOPE",
    completedSnapshotsOnly: true,
    dateRule: "ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT",
  },
  series: [{
    key: "PERMIT",
    label: "건축허가",
    points: [{
      month: "2026-08",
      permitCount: 12,
      totalFloorAreaM2: 1234.5,
      missingAreaCount: 1,
      invalidAreaCount: 0,
    }],
  }],
  quality: {
    aggregateRowCount: 3,
    permitCount: 12,
    totalFloorAreaM2: 1234.5,
    missingAreaCount: 1,
    invalidAreaCount: 0,
  },
};

describe("permit timeseries contract", () => {
  it("defaults to a server-selected 60-month event view", () => {
    expect(parsePermitTimeseriesRequest(new URLSearchParams())).toEqual({
      groupBy: "EVENT_TYPE",
      from: null,
      to: null,
      eventType: null,
      assetType: null,
      district: null,
      constructionAction: null,
    });
  });

  it("parses explicit governed dimensions without accepting unknown enums", () => {
    expect(parsePermitTimeseriesRequest(new URLSearchParams({
      groupBy: "DISTRICT",
      from: "2025-01",
      to: "2026-08",
      eventType: "ACTUAL_START",
      assetType: "OFFICE",
      district: " 강남구 ",
      constructionAction: "NEW_SUPPLY",
    }))).toMatchObject({ groupBy: "DISTRICT", district: "강남구", eventType: "ACTUAL_START" });
    expect(() => parsePermitTimeseriesRequest(new URLSearchParams({ assetType: "OFFICE_OR_RETAIL" })))
      .toThrow(PermitRequestError);
    expect(() => parsePermitTimeseriesRequest(new URLSearchParams({ from: "2026-12", to: "2026-01" })))
      .toThrow("from must not follow to");
    expect(() => parsePermitTimeseriesRequest(new URLSearchParams({ from: "2026-13" })))
      .toThrow("Invalid from");
  });

  it("normalizes quantitative points and fails closed on invalid provenance", () => {
    expect(normalizePermitTimeseries(payload)).toEqual(payload);
    expect(() => normalizePermitTimeseries({
      ...payload,
      scope: { ...payload.scope, status: "REVIEW_OTHER" },
    })).toThrow("Invalid permit scope");
    expect(() => normalizePermitTimeseries({
      ...payload,
      series: [{ ...payload.series[0], points: [{ ...payload.series[0].points[0], permitCount: -1 }] }],
    })).toThrow("Invalid permitCount");
  });
});
