import type {
  InstitutionalAssessmentEvidence,
  InstitutionalAssessmentStep,
  InstitutionalAssessmentVerdict,
  InstitutionalCapitalItem,
  InstitutionalSelectionAssessment,
  RelatedDocument,
} from "@/lib/intelligence-contract";

export type RawInstitutionalManagerSignal = {
  signalId: string;
  selectionId: string | null;
  signalKind: "OFFICIAL_SELECTION" | "REPORTED_SELECTION" | "DEPLOYMENT_INFERENCE" | "BID_PARTICIPATION" | "REVIEW_REQUIRED";
  managerOrganizationId: string | null;
  managerName: string;
  trackCode: string | null;
  trackName: string | null;
  selectionStatus: string | null;
  selectedAt: string | null;
  valueStatus: string | null;
  canonicalEligible: boolean | number;
  confidence: number | null;
  independentFamilyCount: number | null;
  occurrenceCount: number | null;
  reportedAllocation: string | null;
  allocationCurrency: string | null;
  actionLabel: string | null;
  vehicleName: string | null;
  dealLabel: string | null;
  conflictNote: string | null;
  evidenceStatus: string | null;
  reviewStatus: string | null;
  certaintyCode: string | null;
  verificationStatus: string | null;
  extractionMethod: string | null;
  ruleVersion: string | null;
  fundingBasis: string | null;
  sourceDocument: RelatedDocument | null;
};

export type RawInstitutionalDeployment = {
  deploymentId: string;
  selectionId: string | null;
  managerOrganizationId: string | null;
  managerName: string | null;
  trackCode: string | null;
  trackName: string | null;
  vehicleName: string | null;
  linkedTargetLabel: string | null;
  basis: string | null;
  status: string | null;
  deployedAt: string | null;
  amount: string | null;
  currency: string | null;
  evidenceStatus: string | null;
  reviewStatus: string | null;
  confidence: number | null;
  sourceClaimId: string | null;
  sourceDocument: RelatedDocument | null;
};

export type InstitutionalAssessmentInput = Pick<
  InstitutionalCapitalItem,
  "mandateId" | "mandateName" | "lpName" | "tracks" | "documents"
> & {
  managerSignals: RawInstitutionalManagerSignal[];
  deployments: RawInstitutionalDeployment[];
};

const stepLabels: Record<InstitutionalAssessmentStep["code"], string> = {
  LP_SOURCE: "기관·자금 출처",
  TRACK_MATCH: "동일 프로그램·track",
  FOLLOW_UP_ACTION: "후속 입찰·집행",
  DEPLOYMENT_MATCH: "vehicle·deal 연결",
  MANAGER_MATCH: "집행 운용사",
  DECISION: "선정 판단",
};

const verdictLabels: Record<InstitutionalAssessmentVerdict, string> = {
  OFFICIAL_SELECTION: "공식 선정",
  INFERRED_SELECTION: "집행 기반 선정 유추",
  BID_PARTICIPATION: "입찰 참여",
  REVIEW_REQUIRED: "검토 필요",
};

const primarySourceTypes = new Set([
  "PRESS_RELEASE", "DISCLOSURE", "NOTICE", "BID_NOTICE", "REPORT", "API_RECORD", "LEGAL_DOCUMENT",
]);
const deploymentActions = new Set(["COMMITTED", "EXECUTED", "REALISED"]);
const bidActions = new Set([
  "APPLIED",
  "BID_SUBMITTED",
  "PRELIMINARY_BID_SUBMITTED",
  "FINAL_BID_SUBMITTED",
  "SHORTLISTED",
  "PREFERRED_BIDDER",
]);

function evidenceWithRole(
  document: RelatedDocument | null | undefined,
  role: InstitutionalAssessmentEvidence["role"],
  roleLabel: string,
): InstitutionalAssessmentEvidence | null {
  return document ? { ...document, role, roleLabel } : null;
}

function uniqueEvidence(evidence: Array<InstitutionalAssessmentEvidence | null>): InstitutionalAssessmentEvidence[] {
  const seen = new Set<string>();
  return evidence.filter((item): item is InstitutionalAssessmentEvidence => {
    if (!item || seen.has(`${item.documentId}:${item.role}`)) return false;
    seen.add(`${item.documentId}:${item.role}`);
    return true;
  });
}

function isMandateSource(document: RelatedDocument, lpName: string): boolean {
  const type = (document.documentType ?? "").toUpperCase();
  return primarySourceTypes.has(type) && (document.publisher === lpName || document.relationBasis !== "SOURCE_CLAIM");
}

function isOfficialSelectionSource(document: RelatedDocument | null, lpName: string): boolean {
  if (!document || !primarySourceTypes.has((document.documentType ?? "").toUpperCase())) return false;
  return document.publisher === lpName || document.relationBasis === "OFFICIAL_SELECTION_EVIDENCE";
}

function normalizedAction(value: string | null): string {
  return (value ?? "").trim().toUpperCase().replaceAll(/[\s-]+/g, "_");
}

function hasDisqualifyingStatus(signal: RawInstitutionalManagerSignal): boolean {
  const status = `${signal.valueStatus ?? ""} ${signal.verificationStatus ?? ""} ${signal.reviewStatus ?? ""}`.toUpperCase();
  return Boolean(signal.conflictNote || ["CONFLICT", "CONTRADICTED", "SUPERSEDED", "CORRECTED", "REJECTED"].some((token) => status.includes(token)));
}

function strongInferenceClaim(signal: RawInstitutionalManagerSignal): boolean {
  return Boolean(
    signal.signalKind === "DEPLOYMENT_INFERENCE"
    && signal.sourceDocument
    && signal.trackCode
    && signal.managerName
    && (signal.vehicleName || signal.dealLabel)
    && deploymentActions.has(normalizedAction(signal.actionLabel))
    && signal.fundingBasis === "LP_SOURCE_DEPLOYMENT"
    && signal.certaintyCode === "INFERRED"
    && signal.extractionMethod === "CALCULATED"
    && signal.verificationStatus === "VERIFIED"
    && signal.reviewStatus === "ACCEPTED"
    && Boolean(signal.ruleVersion?.trim()),
  );
}

function confidenceBand(
  verdict: InstitutionalAssessmentVerdict,
  confidence: number | null,
): InstitutionalSelectionAssessment["confidenceBand"] {
  if (verdict === "OFFICIAL_SELECTION") return "NOT_APPLICABLE";
  if (confidence === null) return "LOW";
  if (confidence >= 0.85) return "HIGH";
  if (confidence >= 0.65) return "MEDIUM";
  return "LOW";
}

function toBoolean(value: boolean | number): boolean {
  return value === true || value === 1;
}

function strongDeployment(deployment: RawInstitutionalDeployment): boolean {
  return Boolean(
    deployment.sourceClaimId
    && deployment.sourceDocument
    && deployment.managerName
    && deployment.trackCode
    && (deployment.vehicleName || deployment.linkedTargetLabel)
    && deployment.basis === "LP_SOURCE_DEPLOYMENT"
    && ["COMMITTED", "EXECUTED", "REALISED"].includes(deployment.status ?? "")
    && deployment.reviewStatus === "APPROVED"
    && ["SOURCE_CLAIM", "MANUAL_VERIFIED"].includes(deployment.evidenceStatus ?? ""),
  );
}

function trackNameFor(input: InstitutionalAssessmentInput, trackCode: string | null): string | null {
  if (!trackCode) return null;
  const track = input.tracks.find((candidate) => String(candidate.code ?? "") === trackCode);
  return track ? String(track.name ?? trackCode) : trackCode;
}

function step(
  code: InstitutionalAssessmentStep["code"],
  status: InstitutionalAssessmentStep["status"],
  detail: string,
  evidenceDocumentIds: string[] = [],
): InstitutionalAssessmentStep {
  return { code, label: stepLabels[code], status, detail, evidenceDocumentIds };
}

function verdictFor(
  input: InstitutionalAssessmentInput,
  signal: RawInstitutionalManagerSignal,
  deployments: RawInstitutionalDeployment[],
): InstitutionalAssessmentVerdict {
  const official = signal.selectionStatus === "SELECTED"
    && toBoolean(signal.canonicalEligible)
    && signal.reviewStatus === "APPROVED"
    && ["SOURCE_CLAIM", "MANUAL_VERIFIED"].includes(signal.evidenceStatus ?? "")
    && isOfficialSelectionSource(signal.sourceDocument, input.lpName);
  if (official) return "OFFICIAL_SELECTION";

  if (hasDisqualifyingStatus(signal)) return "REVIEW_REQUIRED";
  if (strongInferenceClaim(signal) || deployments.some(strongDeployment)) return "INFERRED_SELECTION";
  if (signal.signalKind === "BID_PARTICIPATION" || ["APPLIED", "SHORTLISTED"].includes(signal.selectionStatus ?? "")) {
    const structuredBid = Boolean(
      signal.selectionId
      && signal.trackCode
      && signal.sourceDocument
      && signal.reviewStatus === "APPROVED"
      && ["SOURCE_CLAIM", "MANUAL_VERIFIED"].includes(signal.evidenceStatus ?? ""),
    );
    const claimBid = Boolean(
      !signal.selectionId
      && signal.trackCode
      && signal.sourceDocument
      && bidActions.has(normalizedAction(signal.actionLabel))
      && signal.verificationStatus === "VERIFIED"
      && signal.reviewStatus === "ACCEPTED",
    );
    return structuredBid || claimBid ? "BID_PARTICIPATION" : "REVIEW_REQUIRED";
  }
  return "REVIEW_REQUIRED";
}

function buildSteps(
  input: InstitutionalAssessmentInput,
  signal: RawInstitutionalManagerSignal,
  verdict: InstitutionalAssessmentVerdict,
  deployments: RawInstitutionalDeployment[],
  evidence: InstitutionalAssessmentEvidence[],
): InstitutionalAssessmentStep[] {
  const mandateEvidenceIds = evidence.filter((item) => item.role === "MANDATE_SOURCE").map((item) => item.documentId);
  const signalEvidenceIds = evidence.filter((item) => item.role !== "MANDATE_SOURCE" && item.role !== "DEPLOYMENT_EVIDENCE").map((item) => item.documentId);
  const deploymentEvidenceIds = evidence.filter((item) => item.role === "DEPLOYMENT_EVIDENCE").map((item) => item.documentId);
  const hasTrack = Boolean(signal.trackCode);
  const hasStrongDeployment = deployments.some(strongDeployment) || strongInferenceClaim(signal);
  const targetLabel = deployments.find((item) => item.vehicleName || item.linkedTargetLabel);
  const followUpDetail = verdict === "OFFICIAL_SELECTION"
    ? "기관의 공식 선정 결과에서 운용사를 직접 확인"
    : verdict === "INFERRED_SELECTION"
      ? signal.actionLabel || "후속 문서에서 기관자금의 약정·집행을 확인"
      : verdict === "BID_PARTICIPATION"
        ? signal.actionLabel || "입찰 또는 shortlist 참여만 확인"
        : signal.signalKind === "DEPLOYMENT_INFERENCE"
          ? "집행 추론 claim은 있으나 검증·승인·기관자금 연결 조건이 남음"
          : signal.signalKind === "BID_PARTICIPATION"
            ? "입찰 claim은 있으나 원문·track·검증 조건이 남음"
            : "기사상 선정 보도는 있으나 공식 결과·집행 교차검증이 남음";

  return [
    step(
      "LP_SOURCE",
      mandateEvidenceIds.length ? "CONFIRMED" : "MISSING",
      mandateEvidenceIds.length ? `${input.lpName}의 공고·프로그램 근거 확인` : "기관 공고 원문 연결 필요",
      mandateEvidenceIds,
    ),
    step(
      "TRACK_MATCH",
      hasTrack ? "CONFIRMED" : "MISSING",
      hasTrack ? `${signal.trackName ?? trackNameFor(input, signal.trackCode) ?? signal.trackCode} track과 연결` : "동일 전략·빈티지·track 확인 필요",
      mandateEvidenceIds,
    ),
    step(
      "FOLLOW_UP_ACTION",
      signalEvidenceIds.length || hasStrongDeployment ? (verdict === "REVIEW_REQUIRED" ? "SUPPORTED" : "CONFIRMED") : "MISSING",
      followUpDetail,
      signalEvidenceIds,
    ),
    step(
      "DEPLOYMENT_MATCH",
      hasStrongDeployment ? "CONFIRMED" : "MISSING",
      hasStrongDeployment
        ? `${signal.vehicleName || targetLabel?.vehicleName || signal.dealLabel || targetLabel?.linkedTargetLabel || "vehicle·deal"}에 기관자금 연결`
        : verdict === "OFFICIAL_SELECTION"
          ? "선정은 공식 확인됐으며 후속 vehicle·deal 집행은 아직 미연결"
          : "vehicle·deal 또는 실제 자금 집행 연결 미확인",
      deploymentEvidenceIds,
    ),
    step(
      "MANAGER_MATCH",
      signal.managerName ? (verdict === "REVIEW_REQUIRED" ? "SUPPORTED" : "CONFIRMED") : "MISSING",
      signal.managerName ? `${signal.managerName}이 운용·집행 주체로 식별됨` : "운용사 identity 확인 필요",
      [...signalEvidenceIds, ...deploymentEvidenceIds],
    ),
    step(
      "DECISION",
      verdict === "OFFICIAL_SELECTION" ? "CONFIRMED" : verdict === "INFERRED_SELECTION" ? "SUPPORTED" : "MISSING",
      verdict === "OFFICIAL_SELECTION"
        ? "공식 선정으로 확정"
        : verdict === "INFERRED_SELECTION"
          ? "공식 결과는 아니며, 후속 집행 근거로 선정 가능성이 높다고 유추"
          : verdict === "BID_PARTICIPATION"
            ? "입찰 참여는 선정과 다르므로 선정 판단을 보류"
            : signal.conflictNote || "공식 결과 또는 동일 자금의 실제 집행 근거가 더 필요",
      signalEvidenceIds,
    ),
  ];
}

function missingChecksFor(
  signal: RawInstitutionalManagerSignal,
  verdict: InstitutionalAssessmentVerdict,
  deployments: RawInstitutionalDeployment[],
): string[] {
  const checks: string[] = [];
  if (!signal.trackCode) checks.push("동일 mandate·track 확인");
  if (!signal.sourceDocument) checks.push("후속 기사·공식문서 원문");
  if (signal.signalKind === "DEPLOYMENT_INFERENCE" && signal.fundingBasis !== "LP_SOURCE_DEPLOYMENT") checks.push("기관 출처 자금 basis 확인");
  if (signal.signalKind === "DEPLOYMENT_INFERENCE" && !deploymentActions.has(normalizedAction(signal.actionLabel))) checks.push("약정·집행·회수 후속 행위 확인");
  if (signal.signalKind === "DEPLOYMENT_INFERENCE" && signal.certaintyCode !== "INFERRED") checks.push("추론 certainty 표기");
  if (signal.signalKind === "DEPLOYMENT_INFERENCE" && signal.extractionMethod !== "CALCULATED") checks.push("결정론적 산출 방식 확인");
  if (signal.signalKind === "DEPLOYMENT_INFERENCE" && !signal.ruleVersion?.trim()) checks.push("추론 규칙 버전");
  if (signal.signalKind === "DEPLOYMENT_INFERENCE" && (signal.verificationStatus !== "VERIFIED" || signal.reviewStatus !== "ACCEPTED")) checks.push("추론 검증·검토 승인");
  if (verdict !== "OFFICIAL_SELECTION" && !deployments.some(strongDeployment) && !strongInferenceClaim(signal)) checks.push("기관자금→vehicle·deal 집행 연결");
  if (verdict !== "OFFICIAL_SELECTION") checks.push("기관 공식 선정 결과");
  if (signal.conflictNote) checks.push(`상충 근거 해소: ${signal.conflictNote}`);
  return [...new Set(checks)];
}

export function buildInstitutionalSelectionAssessments(
  input: InstitutionalAssessmentInput,
): InstitutionalSelectionAssessment[] {
  const priority: Record<InstitutionalAssessmentVerdict, number> = {
    OFFICIAL_SELECTION: 4,
    INFERRED_SELECTION: 3,
    BID_PARTICIPATION: 2,
    REVIEW_REQUIRED: 1,
  };
  const assessments = input.managerSignals.map((signal) => {
    const deployments = signal.trackCode ? input.deployments.filter((deployment) => (
      deployment.trackCode === signal.trackCode && (
        (signal.selectionId && deployment.selectionId === signal.selectionId)
        || (signal.managerOrganizationId && deployment.managerOrganizationId === signal.managerOrganizationId)
      )
    )) : [];
    const verdict = verdictFor(input, signal, deployments);
    const signalRole: InstitutionalAssessmentEvidence["role"] = verdict === "OFFICIAL_SELECTION"
      ? "OFFICIAL_RESULT"
      : verdict === "INFERRED_SELECTION"
        ? "DEPLOYMENT_EVIDENCE"
        : verdict === "BID_PARTICIPATION"
          ? "BID_EVIDENCE"
          : "REPORTED_SELECTION";
    const signalRoleLabel = verdict === "OFFICIAL_SELECTION"
      ? "공식 선정 결과"
      : verdict === "INFERRED_SELECTION"
        ? "후속 집행 근거"
        : verdict === "BID_PARTICIPATION"
          ? "입찰 참여 근거"
          : "기사상 선정 보도";
    const evidence = uniqueEvidence([
      ...input.documents.filter((document) => isMandateSource(document, input.lpName))
        .map((document) => evidenceWithRole(document, "MANDATE_SOURCE", "기관 공고·프로그램")),
      evidenceWithRole(signal.sourceDocument, signalRole, signalRoleLabel),
      ...deployments.map((deployment) => evidenceWithRole(deployment.sourceDocument, "DEPLOYMENT_EVIDENCE", "vehicle·deal 집행")),
    ]);
    const rationale = verdict === "OFFICIAL_SELECTION"
      ? `${input.lpName}의 공식 결과에서 ${signal.managerName} 선정을 직접 확인했습니다.`
      : verdict === "INFERRED_SELECTION"
        ? `${input.lpName}의 동일 track 자금이 vehicle·deal에 집행되고 ${signal.managerName}이 운용 주체로 연결되어 선정으로 유추합니다.`
        : verdict === "BID_PARTICIPATION"
          ? `${signal.managerName}의 입찰 참여는 확인되지만 선정 또는 집행 사실은 확인되지 않았습니다.`
          : signal.signalKind === "DEPLOYMENT_INFERENCE"
            ? `${signal.managerName}의 집행 연결 후보가 있으나 기관 출처 자금·동일 track·검증 승인 조건을 모두 충족하지 못했습니다.`
            : signal.signalKind === "BID_PARTICIPATION"
              ? `${signal.managerName}의 입찰 참여 후보가 있으나 원문·동일 track·검증 승인 조건을 더 확인해야 합니다.`
              : `${signal.managerName}이 선정사로 보도됐지만 공식 결과나 동일 자금의 후속 집행 연결이 필요합니다.`;

    return {
      assessmentId: signal.signalId,
      managerOrganizationId: signal.managerOrganizationId,
      managerName: signal.managerName,
      trackCode: signal.trackCode,
      trackName: signal.trackName ?? trackNameFor(input, signal.trackCode),
      verdict,
      verdictLabel: verdictLabels[verdict],
      confidence: signal.confidence,
      confidenceBand: confidenceBand(verdict, signal.confidence),
      rationale,
      actionLabel: signal.actionLabel || (verdict === "OFFICIAL_SELECTION" ? "공식 선정 결과" : verdict === "REVIEW_REQUIRED" ? "기사상 선정 보도" : verdictLabels[verdict]),
      reportedAllocation: signal.reportedAllocation,
      allocationCurrency: signal.allocationCurrency,
      steps: buildSteps(input, signal, verdict, deployments, evidence),
      evidence,
      missingChecks: missingChecksFor(signal, verdict, deployments),
    } satisfies InstitutionalSelectionAssessment;
  });

  const byIdentity = new Map<string, InstitutionalSelectionAssessment>();
  for (const assessment of assessments) {
    const key = `${assessment.managerOrganizationId ?? assessment.managerName}:${assessment.trackCode ?? "UNKNOWN"}`;
    const current = byIdentity.get(key);
    if (!current || priority[assessment.verdict] > priority[current.verdict]) byIdentity.set(key, assessment);
  }
  return [...byIdentity.values()].sort((a, b) => (
    priority[b.verdict] - priority[a.verdict]
    || a.managerName.localeCompare(b.managerName, "ko")
  ));
}
