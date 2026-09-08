import { describe, expect, it, vi } from "vitest";
import { getOperationsOverview, type OperationsSqlExecutor } from "@/lib/server/operations-insights";

const payload = {
  generatedAt: "2026-08-22T06:00:00Z",
  asOfAt: "2026-08-22T06:00:00Z",
  policyVersion: "SOURCE_HEALTH_V1",
  summary: { sourceCount: 1, onboardedSourceCount: 0, notOnboardedSourceCount: 1, distinctDocumentCount: 0, documentVersionCount: 0, runCount: 0 },
  runStatusCounts: [],
  classificationQuality: {
    schemes: [], reviewStatusCounts: [], evidenceStatusCounts: [],
    currentAssignmentCount: 0, supersededAssignmentCount: 0,
  },
  sources: [{
    sourceCode: "KOSIS", sourceName: "국가통계포털", sourceKind: "STATISTICS",
    onboarding: "NOT_ONBOARDED", slaMode: "NOT_ONBOARDED", freshness: "NO_SLA",
    latestExecution: "NONE", dataOutcome: "UNKNOWN", activeJobCount: 0,
    scheduledJobCount: 0, runCount: 0, completedRunCount: 0, distinctDocumentCount: 0,
    documentVersionCount: 0, latestSuccessfulAt: null, latestRunAt: null,
    expectedIntervalSeconds: null, graceSeconds: null, latestDiscoveredCount: null,
    latestInsertedCount: null, latestUpdatedCount: null, latestRejectedCount: null,
  }],
};

describe("getOperationsOverview", () => {
  it("returns every active source and counts distinct documents without exposing run secrets", async () => {
    const execute: OperationsSqlExecutor = vi.fn().mockResolvedValue({ rows: [{ payload }] });

    const result = await getOperationsOverview(execute);

    expect(result.sources).toHaveLength(1);
    expect(result.sources[0].sourceCode).toBe("KOSIS");
    const [sql, values] = vi.mocked(execute).mock.calls[0];
    expect(values).toEqual([]);
    expect(sql).toContain("FROM collection_sources");
    expect(sql).toContain("FROM collection_jobs");
    expect(sql).toContain("FROM collection_runs");
    expect(sql).toContain("FROM source_documents");
    expect(sql).toContain("document_versions");
    expect(sql).toContain("count(DISTINCT sd.document_id)");
    expect(sql).toContain("LEFT JOIN");
    expect(sql).not.toContain("error_message");
    expect(sql).not.toContain("query_rendered");
    expect(sql).not.toContain("cursor_in");
    expect(sql).not.toContain("cursor_out");
    expect(sql).toContain("FROM record_classifications");
    expect(sql).toContain("FROM classification_schemes");
    expect(sql).toContain("JOIN classification_terms");
    expect(sql).toContain("JOIN archive_snapshots");
    expect(sql).toContain("integrity_status='VALIDATED'");
    expect(sql).toContain("is_current=1");
    expect(sql).toContain("count(DISTINCT st.target_id)");
    expect(sql).toContain("review_status='APPROVED'");
    expect(sql).toContain("review_status NOT IN ('REJECTED','SUPERSEDED')");
    expect(sql).toContain("FROM json_each(gs.target_kinds_json)");
    expect(sql).toContain("row_number() OVER (");
    expect(sql).toContain("json_group_array(json_object(");
    expect(sql).toContain("strftime('%Y-%m-%dT%H:%M:%fZ','now')");
    expect(sql).not.toMatch(/market_intelligence\.|::|jsonb_|DISTINCT ON|clock_timestamp|AT TIME ZONE|date_trunc|generate_series|\bLATERAL\b|FILTER\s*\(/i);
    expect(sql).not.toMatch(/->>|!~|\s~\s|\s\?\s/);
  });
});
