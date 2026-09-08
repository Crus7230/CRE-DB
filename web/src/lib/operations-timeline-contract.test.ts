import { describe, expect, it } from "vitest";
import { normalizeOperationsTimeline } from "@/lib/operations-timeline-contract";

const valid = {
  generatedAt: "2026-08-22T00:00:00Z",
  windowDays: 90,
  publicationKnownCount: 1,
  publicationUnknownCount: 2,
  archivedDocumentExcludedCount: 3,
  series: [{ date: "2026-08-21", publicationCount: 1, eventCount: 2, ingestionCount: 4 }],
};

describe("normalizeOperationsTimeline", () => {
  it("keeps publication, event and ingestion clocks separate", () => {
    const result = normalizeOperationsTimeline(valid);
    expect(result.series[0]).toEqual({ date: "2026-08-21", publicationCount: 1, eventCount: 2, ingestionCount: 4 });
    expect(result.publicationUnknownCount).toBe(2);
    expect(result.archivedDocumentExcludedCount).toBe(3);
  });

  it("rejects malformed series", () => {
    expect(() => normalizeOperationsTimeline({ ...valid, series: null })).toThrow("Invalid operations timeline payload");
    expect(() => normalizeOperationsTimeline({ ...valid, publicationKnownCount: undefined })).toThrow("Invalid operations timeline payload");
    expect(() => normalizeOperationsTimeline({ ...valid, series: [{...valid.series[0],eventCount:Number.NaN}] })).toThrow("Invalid operations timeline payload");
    expect(() => normalizeOperationsTimeline({ ...valid, windowDays:31 })).toThrow("Invalid operations timeline payload");
  });
});
