import { describe, expect, it } from "vitest";
import { getInstitutionalCapital, getSaleProcesses } from "@/lib/server/domain-workspaces";

function expectTursoCompatibleAggregates(sql: string) {
  const aggregateNames = ["json_group_array", "json_group_object", "group_concat"];
  let aggregateCount = 0;
  for (const name of aggregateNames) {
    let searchFrom = 0;
    while ((searchFrom = sql.indexOf(`${name}(`, searchFrom)) >= 0) {
      aggregateCount += 1;
      const argumentStart = searchFrom + name.length + 1;
      let depth = 1;
      let inString = false;
      let cursor = argumentStart;
      for (; cursor < sql.length && depth > 0; cursor += 1) {
        const character = sql[cursor];
        if (character === "'") {
          if (inString && sql[cursor + 1] === "'") cursor += 1;
          else inString = !inString;
        } else if (!inString && character === "(") depth += 1;
        else if (!inString && character === ")") depth -= 1;
      }
      expect(depth).toBe(0);
      expect(sql.slice(argumentStart, cursor - 1).toUpperCase()).not.toContain("ORDER BY");
      searchFrom = cursor;
    }
  }
  expect(aggregateCount).toBeGreaterThan(0);
}

const sourceDocument = {
  documentId: "doc-1",
  title: "위탁운용사 선정 보도",
  documentType: "ARTICLE",
  publishedAt: "2024-04-29",
  publisher: "테스트뉴스",
  href: "https://example.com/article",
  relationBasis: "SOURCE_CLAIM",
};

describe("getInstitutionalCapital", () => {
  it("projects official selections, reported candidates, bid links, and deployments as separate evidence layers", async () => {
    let sql = "";
    const response = await getInstitutionalCapital(async (text) => {
      sql = text;
      return { rows: [{ payload: JSON.stringify({
        items: [{
          mandateId: "mandate-1",
          mandateName: "기관 위탁운용사 선정",
          lpName: "테스트기관",
          status: "UNKNOWN",
          scope: "DOMESTIC",
          announcedAt: "2024-01-01",
          selectedAt: null,
          evidenceStatus: "SOURCE_CLAIM",
          trackCount: 1,
          selectionCount: 0,
          amountCount: 1,
          guidelineCount: 0,
          deploymentCount: 0,
          tracks: [{ code: "TRACK-1", name: "국내 부동산" }],
          amounts: [],
          selections: [],
          deployments: [],
          documents: [],
          managerSignals: [{
            signalId: "claim-1",
            selectionId: null,
            signalKind: "REPORTED_SELECTION",
            managerOrganizationId: "manager-1",
            managerName: "테스트자산운용",
            trackCode: "TRACK-1",
            trackName: "국내 부동산",
            selectionStatus: "REPORTED_SELECTED",
            selectedAt: "2024-04-29",
            valueStatus: "LIKELY_REPORTED_PENDING_PRIMARY",
            canonicalEligible: false,
            confidence: 0.72,
            independentFamilyCount: 1,
            occurrenceCount: 1,
            reportedAllocation: "50000000000",
            allocationCurrency: "KRW",
            actionLabel: "기사상 선정 보도",
            vehicleName: null,
            dealLabel: null,
            conflictNote: null,
            evidenceStatus: "SOURCE_CLAIM",
            reviewStatus: "ACCEPTED",
            certaintyCode: "REPORTED",
            verificationStatus: "PENDING",
            extractionMethod: "MANUAL",
            ruleVersion: null,
            fundingBasis: null,
            sourceDocument,
          }],
        }],
        coverage: { mandates: 1, selections: 0, amounts: 1, deployments: 0 },
      }) }] };
    });

    expect(sql).toContain("v_lp_manager_best_available");
    expect(sql).toContain("b.canonical_eligible=0");
    expect(sql).toContain("s.selection_status='SELECTED'");
    expect(sql).toContain("s.review_status='APPROVED'");
    expect(sql).toContain("LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT");
    expect(sql).toContain("LP_MANDATE_MANAGER_BID_PARTICIPANT");
    expect(sql).toContain("OFFICIAL_SELECTION_EVIDENCE");
    expect(sql).toContain("official_source_contracts");
    expect(sql).toContain("json_extract(contract.value,'$.verification_status')");
    expect(sql).toContain("cs.source_kind IN ('OFFICIAL_API','OFFICIAL_SITE','PARTY_SITE')");
    expect(sql).toContain("sd.publisher_name=lp.canonical_name");
    expect(sql).toContain("c.review_status IN ('UNREVIEWED','ACCEPTED')");
    expect(sql).toContain("claim_argument_bundles AS");
    expect(sql).toContain("sum(CASE WHEN ca.role_code='MANDATE_TRACK' THEN 1 ELSE 0 END) AS track_count");
    expect(sql).toContain("bundle.mandate_count=1");
    expect(sql).toContain("bundle.track_count=1");
    expect(sql).toContain("bundle.action_count=1");
    expect(sql).toContain("bundle.funding_count=1");
    expect(sql).toContain("bundle.rule_count=1");
    expect(sql).toContain("bundle.vehicle_count<=1");
    expect(sql).toContain("bundle.deal_count<=1");
    expect(sql).toContain("bundle.vehicle_count+bundle.deal_count>=1");
    expect(sql).toContain("bundle.vehicle_count=0 OR vehicle_org.organization_id IS NOT NULL");
    expect(sql).toContain("bundle.deal_count=0 OR deal_asset.asset_id IS NOT NULL OR deal_project.project_id IS NOT NULL");
    expect(sql).toContain("deal_asset.asset_id IS NOT NULL OR deal_project.project_id IS NOT NULL");
    expect(sql).not.toContain("LEFT JOIN claim_arguments track_arg");
    expect(sql).toContain("d.basis='LP_SOURCE_DEPLOYMENT'");
    expect(sql).toContain("d.status IN ('COMMITTED','EXECUTED','REALISED')");
    expect(sql).toContain("json(CASE WHEN s.canonical_eligible<>0 THEN 'true' ELSE 'false' END)");
    expect(sql).toContain(") ordered_mandates");
    expectTursoCompatibleAggregates(sql);
    for (const postgresOnly of [
      "market_intelligence.", "DISTINCT ON", "LATERAL", "jsonb_", "::", " FILTER (",
      "array_agg", "current_date", "->>",
    ]) {
      expect(sql.toUpperCase()).not.toContain(postgresOnly.toUpperCase());
    }
    expect(response.coverage).toMatchObject({
      officialSelections: 0,
      inferredSelections: 0,
      bidParticipations: 0,
      reviewRequired: 1,
      deployments: 0,
    });
    expect(response.items[0].assessments[0]).toMatchObject({
      managerName: "테스트자산운용",
      verdict: "REVIEW_REQUIRED",
      reportedAllocation: "50000000000",
    });
  });
});

describe("getSaleProcesses", () => {
  it("keeps curated 2026 candidates, article signals, and canonical processes as separate layers", async () => {
    let sql = "";
    const response = await getSaleProcesses(async (text) => {
      sql = text;
      return { rows: [{ payload: JSON.stringify({
        items: [],
        candidateProcesses: [{
          candidateId: "KR-CRE-2026-G1-SEOUL",
          processCode: "KR-CRE-2026-G1-SEOUL",
          title: "G1서울",
          assetType: "OFFICE",
          method: "COMPETITIVE",
          status: "CLOSED",
          stageCode: "CLOSED",
          evidenceGrade: "B",
          confidence: 0.78,
          roles: { buyer_or_preferred: "미래에셋자산운용" },
          rounds: [{ round_type: "FINAL_BID", date: "2026-01-23" }],
          milestones: [{ type: "CLOSED", date: "2026-06" }],
          amounts: [{ value_krw: "1523000000000" }],
          financing: [],
          sources: [{ date: "2026-02-03", url: "https://example.com/g1", span: "우협 선정" }],
        }],
        coverage: {
          processes: 16,
          rounds: 4,
          bidders: 2,
          submissions: 1,
          decisions: 1,
          fundingComponents: 0,
          milestones: 3,
          signalYear: 2026,
          candidateCutoffDate: "2026-08-19",
          currentYearProcesses: 0,
          currentYearCandidateProcesses: 14,
          currentYearArticleSignals: 107,
          currentYearPriorityArticleSignals: 33,
          currentYearResolvedStageArticleSignals: 40,
        },
      }) }] };
    });

    expect(sql).toContain("cutoff-research-ledger-20260819-v1");
    expect(sql).toContain("PARTITION BY extraction_key");
    expect(sql).toContain("SALE_PROCESS_EVIDENCE_REVIEW");
    expect(sql).toContain("BID_PROCESS_TITLE_SNIPPET_V%");
    expect(sql).toContain("substr(coalesce(dv.published_at,dv.collected_at,''),1,4)");
    expect(sql).toContain("currentYearCandidateProcesses");
    expect(sql).toContain("currentYearArticleSignals");
    expect(sql).toContain("json_extract(details,'$.roles')");
    expect(sql).toContain(") ordered_rounds");
    expect(sql).toContain(") ordered_candidates");
    expectTursoCompatibleAggregates(sql);
    for (const postgresOnly of [
      "market_intelligence.", "DISTINCT ON", "LATERAL", "jsonb_", "::", "array_agg",
      "current_date", "->>",
    ]) {
      expect(sql.toUpperCase()).not.toContain(postgresOnly.toUpperCase());
    }
    expect(response.coverage).toMatchObject({
      processes: 16,
      currentYearProcesses: 0,
      currentYearCandidateProcesses: 14,
      currentYearArticleSignals: 107,
      candidateCutoffDate: "2026-08-19",
    });
    expect(response.candidateProcesses[0]).toMatchObject({ title: "G1서울", evidenceGrade: "B" });
  });
});
