import { describe, expect, it } from "vitest";
import type { RelatedDocument } from "@/lib/intelligence-contract";
import {
  buildInstitutionalSelectionAssessments,
  type InstitutionalAssessmentInput,
  type RawInstitutionalDeployment,
  type RawInstitutionalManagerSignal,
} from "@/lib/server/institutional-capital-assessment";

const mandateDocument: RelatedDocument = {
  documentId: "doc-mandate",
  title: "2026년 기관 위탁운용사 모집 공고",
  documentType: "BID_NOTICE",
  publishedAt: "2026-01-10",
  publisher: "테스트기관",
  href: "https://example.com/mandate",
  relationBasis: "CANONICAL_EVENT",
};

const followUpDocument: RelatedDocument = {
  documentId: "doc-follow-up",
  title: "기관자금 후속 운용·집행 확인",
  documentType: "ARTICLE",
  publishedAt: "2026-05-20",
  publisher: "테스트뉴스",
  href: "https://example.com/follow-up",
  relationBasis: "SOURCE_CLAIM",
};

const officialResultDocument: RelatedDocument = {
  documentId: "doc-official-result",
  title: "2026년 기관 위탁운용사 선정 결과",
  documentType: "PRESS_RELEASE",
  publishedAt: "2026-03-20",
  publisher: "테스트기관",
  href: "https://example.com/official-result",
  relationBasis: "OFFICIAL_SELECTION_EVIDENCE",
};

function signal(overrides: Partial<RawInstitutionalManagerSignal>): RawInstitutionalManagerSignal {
  return {
    signalId: "signal-1",
    selectionId: null,
    signalKind: "REVIEW_REQUIRED",
    managerOrganizationId: "manager-1",
    managerName: "테스트자산운용",
    trackCode: "DOMESTIC_RE",
    trackName: "국내 부동산",
    selectionStatus: null,
    selectedAt: null,
    valueStatus: null,
    canonicalEligible: false,
    confidence: 0.72,
    independentFamilyCount: 1,
    occurrenceCount: 1,
    reportedAllocation: null,
    allocationCurrency: null,
    actionLabel: null,
    vehicleName: null,
    dealLabel: null,
    conflictNote: null,
    evidenceStatus: "SOURCE_CLAIM",
    reviewStatus: "PENDING",
    certaintyCode: null,
    verificationStatus: null,
    extractionMethod: null,
    ruleVersion: null,
    fundingBasis: null,
    sourceDocument: followUpDocument,
    ...overrides,
  };
}

function input(
  managerSignals: RawInstitutionalManagerSignal[],
  deployments: RawInstitutionalDeployment[] = [],
): InstitutionalAssessmentInput {
  return {
    mandateId: "mandate-1",
    mandateName: "2026년 기관 위탁운용사 선정",
    lpName: "테스트기관",
    tracks: [{ code: "DOMESTIC_RE", name: "국내 부동산" }],
    documents: [mandateDocument],
    managerSignals,
    deployments,
  };
}

describe("buildInstitutionalSelectionAssessments", () => {
  it("keeps official, deployment inference, bid, and reported candidates in separate verdicts", () => {
    const assessments = buildInstitutionalSelectionAssessments(input([
      signal({
        signalId: "official",
        signalKind: "OFFICIAL_SELECTION",
        managerOrganizationId: "official-manager",
        managerName: "공식운용사",
        selectionStatus: "SELECTED",
        canonicalEligible: true,
        confidence: 1,
        evidenceStatus: "MANUAL_VERIFIED",
        reviewStatus: "APPROVED",
        sourceDocument: officialResultDocument,
      }),
      signal({
        signalId: "inferred",
        signalKind: "DEPLOYMENT_INFERENCE",
        managerOrganizationId: "inferred-manager",
        managerName: "집행운용사",
        actionLabel: "EXECUTED",
        vehicleName: "테스트 블라인드펀드",
        dealLabel: "테스트 오피스 취득",
        confidence: 0.88,
        certaintyCode: "INFERRED",
        verificationStatus: "VERIFIED",
        extractionMethod: "CALCULATED",
        reviewStatus: "ACCEPTED",
        ruleVersion: "lp-manager-deployment-v1",
        fundingBasis: "LP_SOURCE_DEPLOYMENT",
      }),
      signal({
        signalId: "bid",
        signalKind: "BID_PARTICIPATION",
        managerOrganizationId: "bid-manager",
        managerName: "입찰참여사",
        selectionStatus: "APPLIED",
        actionLabel: "APPLIED",
        verificationStatus: "VERIFIED",
        reviewStatus: "ACCEPTED",
      }),
      signal({
        signalId: "reported",
        signalKind: "REPORTED_SELECTION",
        managerOrganizationId: "reported-manager",
        managerName: "기사보도사",
        selectionStatus: "REPORTED_SELECTED",
        valueStatus: "LIKELY_REPORTED_PENDING_PRIMARY",
      }),
    ]));

    expect(assessments.map((assessment) => assessment.verdict)).toEqual([
      "OFFICIAL_SELECTION",
      "INFERRED_SELECTION",
      "BID_PARTICIPATION",
      "REVIEW_REQUIRED",
    ]);
    expect(assessments.find((assessment) => assessment.assessmentId === "bid")?.rationale).toContain("선정 또는 집행 사실은 확인되지 않았습니다");
    expect(assessments.find((assessment) => assessment.assessmentId === "inferred")?.steps).toHaveLength(6);
    expect(assessments.find((assessment) => assessment.assessmentId === "official")?.steps.find((item) => item.code === "DEPLOYMENT_MATCH")?.detail).toContain("선정은 공식 확인");
  });

  it("promotes a bid candidate only when an approved, sourced deployment links LP track, target, and manager", () => {
    const bidSignal = signal({
      signalId: "bid-with-follow-up",
      selectionId: "selection-1",
      signalKind: "BID_PARTICIPATION",
      selectionStatus: "APPLIED",
      actionLabel: "본입찰 참여",
    });
    const deployment: RawInstitutionalDeployment = {
      deploymentId: "deployment-1",
      selectionId: "selection-1",
      managerOrganizationId: "manager-1",
      managerName: "테스트자산운용",
      trackCode: "DOMESTIC_RE",
      trackName: "국내 부동산",
      vehicleName: "테스트 블라인드펀드",
      linkedTargetLabel: "테스트 오피스",
      basis: "LP_SOURCE_DEPLOYMENT",
      status: "EXECUTED",
      deployedAt: "2026-05-20",
      amount: "50000000000",
      currency: "KRW",
      evidenceStatus: "SOURCE_CLAIM",
      reviewStatus: "APPROVED",
      confidence: 0.9,
      sourceClaimId: "claim-1",
      sourceDocument: followUpDocument,
    };

    const [assessment] = buildInstitutionalSelectionAssessments(input([bidSignal], [deployment]));
    expect(assessment.verdict).toBe("INFERRED_SELECTION");
    expect(assessment.verdictLabel).toBe("집행 기반 선정 유추");
    expect(assessment.steps.find((item) => item.code === "DEPLOYMENT_MATCH")?.status).toBe("CONFIRMED");
  });

  it("never converts bid-only evidence into a selection inference", () => {
    const [assessment] = buildInstitutionalSelectionAssessments(input([
      signal({
        signalKind: "BID_PARTICIPATION",
        selectionStatus: "APPLIED",
        actionLabel: "FINAL_BID_SUBMITTED",
        verificationStatus: "VERIFIED",
        reviewStatus: "ACCEPTED",
      }),
    ]));
    expect(assessment.verdict).toBe("BID_PARTICIPATION");
    expect(assessment.steps.find((item) => item.code === "DECISION")?.detail).toContain("선정 판단을 보류");
  });

  it("holds conflicting evidence for review even when a manager is named", () => {
    const [assessment] = buildInstitutionalSelectionAssessments(input([
      signal({
        signalKind: "DEPLOYMENT_INFERENCE",
        vehicleName: "테스트펀드",
        conflictNote: "동일 기관의 다른 vintage 가능성",
        confidence: 0.9,
      }),
    ]));
    expect(assessment.verdict).toBe("REVIEW_REQUIRED");
    expect(assessment.missingChecks).toContain("상충 근거 해소: 동일 기관의 다른 vintage 가능성");
  });

  it("does not call an approved selection official when its direct source is only an article", () => {
    const [assessment] = buildInstitutionalSelectionAssessments(input([
      signal({
        signalKind: "OFFICIAL_SELECTION",
        selectionId: "selection-article-only",
        selectionStatus: "SELECTED",
        canonicalEligible: true,
        evidenceStatus: "SOURCE_CLAIM",
        reviewStatus: "APPROVED",
        sourceDocument: followUpDocument,
      }),
    ]));
    expect(assessment.verdict).toBe("REVIEW_REQUIRED");
  });

  it("holds contradicted or corrected inference claims for review", () => {
    const [assessment] = buildInstitutionalSelectionAssessments(input([
      signal({
        signalKind: "DEPLOYMENT_INFERENCE",
        actionLabel: "EXECUTED",
        vehicleName: "테스트펀드",
        fundingBasis: "LP_SOURCE_DEPLOYMENT",
        certaintyCode: "INFERRED",
        extractionMethod: "CALCULATED",
        verificationStatus: "CONTRADICTED",
        reviewStatus: "CORRECTED",
        ruleVersion: "lp-manager-deployment-v1",
      }),
    ]));
    expect(assessment.verdict).toBe("REVIEW_REQUIRED");
  });

  it("keeps unreviewed or incomplete deployment claims in review", () => {
    const [assessment] = buildInstitutionalSelectionAssessments(input([
      signal({
        signalKind: "DEPLOYMENT_INFERENCE",
        actionLabel: "EXECUTED",
        vehicleName: "테스트펀드",
        dealLabel: "테스트 오피스",
        certaintyCode: "INFERRED",
        extractionMethod: "CALCULATED",
        verificationStatus: "PENDING",
        reviewStatus: "UNREVIEWED",
        ruleVersion: "lp-manager-deployment-v1",
        fundingBasis: "LP_SOURCE_DEPLOYMENT",
      }),
    ]));
    expect(assessment.verdict).toBe("REVIEW_REQUIRED");
    expect(assessment.missingChecks).toContain("추론 검증·검토 승인");
  });

  it("infers from one canonical vehicle or deal link when every other gate is satisfied", () => {
    for (const links of [
      { vehicleName: "테스트펀드", dealLabel: null },
      { vehicleName: null, dealLabel: "테스트센터" },
    ]) {
      const [assessment] = buildInstitutionalSelectionAssessments(input([
        signal({
          signalKind: "DEPLOYMENT_INFERENCE",
          actionLabel: "EXECUTED",
          ...links,
          certaintyCode: "INFERRED",
          extractionMethod: "CALCULATED",
          verificationStatus: "VERIFIED",
          reviewStatus: "ACCEPTED",
          ruleVersion: "lp-manager-deployment-v1",
          fundingBasis: "LP_SOURCE_DEPLOYMENT",
        }),
      ]));
      expect(assessment.verdict).toBe("INFERRED_SELECTION");
    }
  });

  it("also infers from a canonical deal-only link", () => {
    const [assessment] = buildInstitutionalSelectionAssessments(input([
      signal({
        signalKind: "DEPLOYMENT_INFERENCE",
        actionLabel: "EXECUTED",
        vehicleName: null,
        dealLabel: "테스트 오피스",
        certaintyCode: "INFERRED",
        extractionMethod: "CALCULATED",
        verificationStatus: "VERIFIED",
        reviewStatus: "ACCEPTED",
        ruleVersion: "lp-manager-deployment-v1",
        fundingBasis: "LP_SOURCE_DEPLOYMENT",
      }),
    ]));
    expect(assessment.verdict).toBe("INFERRED_SELECTION");
  });

  it("keeps an otherwise accepted inference without a canonical vehicle or deal in review", () => {
    const [assessment] = buildInstitutionalSelectionAssessments(input([
      signal({
        signalKind: "DEPLOYMENT_INFERENCE",
        actionLabel: "EXECUTED",
        vehicleName: null,
        dealLabel: null,
        certaintyCode: "INFERRED",
        extractionMethod: "CALCULATED",
        verificationStatus: "VERIFIED",
        reviewStatus: "ACCEPTED",
        ruleVersion: "lp-manager-deployment-v1",
        fundingBasis: "LP_SOURCE_DEPLOYMENT",
      }),
    ]));
    expect(assessment.verdict).toBe("REVIEW_REQUIRED");
  });

  it("requires LP source basis and an exact track match for deployment inference", () => {
    const bidSignal = signal({
      signalId: "bid-other-basis",
      signalKind: "BID_PARTICIPATION",
      selectionStatus: "APPLIED",
      actionLabel: "APPLIED",
      verificationStatus: "VERIFIED",
      reviewStatus: "ACCEPTED",
    });
    const deployment: RawInstitutionalDeployment = {
      deploymentId: "deployment-other-basis",
      selectionId: null,
      managerOrganizationId: "manager-1",
      managerName: "테스트자산운용",
      trackCode: "GLOBAL_RE",
      trackName: "해외 부동산",
      vehicleName: "다른 전략 펀드",
      linkedTargetLabel: "해외 자산",
      basis: "FUND_EQUITY_DEPLOYMENT",
      status: "EXECUTED",
      deployedAt: "2026-05-20",
      amount: "50000000000",
      currency: "KRW",
      evidenceStatus: "SOURCE_CLAIM",
      reviewStatus: "APPROVED",
      confidence: 0.9,
      sourceClaimId: "claim-other",
      sourceDocument: followUpDocument,
    };
    const [assessment] = buildInstitutionalSelectionAssessments(input([bidSignal], [deployment]));
    expect(assessment.verdict).toBe("BID_PARTICIPATION");
    expect(assessment.steps.find((item) => item.code === "DEPLOYMENT_MATCH")?.status).toBe("MISSING");
  });
});
