import { describe, expect, it } from "vitest";
import { normalizeOperationsOverview } from "@/lib/operations-insights-contract";

describe("normalizeOperationsOverview", () => {
  it("preserves independent onboarding, freshness, execution and data-outcome axes", () => {
    const result = normalizeOperationsOverview({
      generatedAt: "2026-08-22T06:00:00Z",
      asOfAt: "2026-08-22T06:00:00Z",
      policyVersion: "SOURCE_HEALTH_V1",
      summary: { sourceCount: 2, onboardedSourceCount: 1, notOnboardedSourceCount: 1, distinctDocumentCount: 4, documentVersionCount: 5, runCount: 2 },
      runStatusCounts: [{ status: "COMPLETED", count: 2 }],
      classificationQuality: { schemes: [], reviewStatusCounts: [], evidenceStatusCounts: [], currentAssignmentCount: 0, supersededAssignmentCount: 0 },
      sources: [{
        sourceCode: "GOOGLE_NEWS_RSS", sourceName: "Google News RSS", sourceKind: "RSS",
        onboarding: "ONBOARDED", slaMode: "SCHEDULED", freshness: "NO_SLA",
        latestExecution: "COMPLETED", dataOutcome: "NEW_DATA", activeJobCount: 1,
        scheduledJobCount: 1, runCount: 2, completedRunCount: 2, distinctDocumentCount: 4,
        documentVersionCount: 5, latestSuccessfulAt: "2026-08-22T05:00:00Z",
        latestRunAt: "2026-08-22T05:00:00Z", expectedIntervalSeconds: null,
        graceSeconds: null, latestDiscoveredCount: 4, latestInsertedCount: 1,
        latestUpdatedCount: 0, latestRejectedCount: 0,
      }, {
        sourceCode: "KOSIS", sourceName: "국가통계포털", sourceKind: "STATISTICS",
        onboarding: "NOT_ONBOARDED", slaMode: "NOT_ONBOARDED", freshness: "NO_SLA",
        latestExecution: "NONE", dataOutcome: "UNKNOWN", activeJobCount: 0,
        scheduledJobCount: 0, runCount: 0, completedRunCount: 0, distinctDocumentCount: 0,
        documentVersionCount: 0, latestSuccessfulAt: null, latestRunAt: null,
        expectedIntervalSeconds: null, graceSeconds: null, latestDiscoveredCount: null,
        latestInsertedCount: null, latestUpdatedCount: null, latestRejectedCount: null,
      }],
    });

    expect(result.sources).toHaveLength(2);
    expect(result.sources[0]).toMatchObject({ onboarding: "ONBOARDED", freshness: "NO_SLA", latestExecution: "COMPLETED", dataOutcome: "NEW_DATA" });
    expect(result.sources[1]).toMatchObject({ onboarding: "NOT_ONBOARDED", latestExecution: "NONE", distinctDocumentCount: 0 });
    expect(()=>normalizeOperationsOverview({...result,sources:[{...result.sources[0],onboarding:"INVALID"}]})).toThrow("Invalid source health");
    expect(()=>normalizeOperationsOverview({...result,runStatusCounts:[{status:"INVALID",count:1}]})).toThrow("Invalid operations overview payload");
    expect(()=>normalizeOperationsOverview({...result,classificationQuality:{...result.classificationQuality,reviewStatusCounts:[{status:"INVALID",count:1}]}})).toThrow("Invalid classification quality");
    expect(()=>normalizeOperationsOverview({...result,classificationQuality:{...result.classificationQuality,evidenceStatusCounts:[{status:"INVALID",count:1}]}})).toThrow("Invalid classification quality");
  });

  it("rejects malformed payloads instead of fabricating operational status", () => {
    expect(() => normalizeOperationsOverview({ sources: "not-an-array" })).toThrow("Invalid operations overview payload");
  });
});
