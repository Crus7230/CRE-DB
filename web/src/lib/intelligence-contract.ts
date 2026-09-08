export const companyViews = ["OVERALL", "INDUSTRY", "TENANT_SIGNALS"] as const;
export type CompanyView = (typeof companyViews)[number];

export type CompanyListRequest = {
  view: CompanyView;
  industry: string;
  q: string;
  limit: number;
};

export type LocationEvidenceType = "RELOCATION" | "STAY" | "NEW_LEASE" | "EXPANSION";
export type LocationWordingStage = "CONFIRMED_WORDING" | "IN_PROGRESS_WORDING" | "EXPLORING_WORDING" | "REVIEW_REQUIRED";

export type LocationEvidence = {
  documentId: string;
  evidenceType: LocationEvidenceType;
  wordingStage: LocationWordingStage;
  evidenceLabel: string;
  title: string;
  matchedPhrase: string | null;
  evidenceExcerpt: string | null;
  evidenceReason: string;
  sourceCategory: "LEASE" | "CORPORATE_RELOCATION";
  classificationBasis: "MANAGED_TAXONOMY" | "LEGACY_DISCOVERY";
  classificationReviewStatus: string | null;
  publishedAt: string | null;
  publisher: string | null;
  href: string | null;
  mentionStatus: string | null;
  confidence: number | null;
};

export type CompanyListItem = {
  organizationId: string;
  name: string;
  stockCode: string | null;
  industry: string | null;
  marketCap: string | null;
  overallRank: number | null;
  industryRank: number | null;
  confirmedOccupancyCount: number;
  canonicalEventCount: number;
  relatedAssetCount: number;
  locationEvidenceDocumentCount: number;
  locationEvidencePublisherCount: number;
  primaryLocationEvidence: LocationEvidence | null;
};

export type CompanyListResponse = {
  request: CompanyListRequest;
  snapshotDate: string | null;
  items: CompanyListItem[];
  industries: Array<{ name: string; count: number }>;
  coverage: {
    verifiedOccupancies: number;
    companiesWithLocationEvidence: number;
    managedLocationDocuments: number;
    signalNote: string;
  };
  generatedAt: string;
  database: "turso-libsql";
};

export type RelatedDocument = {
  documentId: string;
  title: string;
  documentType: string | null;
  publishedAt: string | null;
  publisher: string | null;
  href: string | null;
  relationBasis:
    | "CANONICAL_EVENT"
    | "RESOLVED_MENTION"
    | "VERIFIED_CLAIM"
    | "EXACT_NAME_SIGNAL"
    | "SOURCE_CLAIM"
    | "OFFICIAL_SELECTION_EVIDENCE";
};

export type InstitutionalAssessmentVerdict =
  | "OFFICIAL_SELECTION"
  | "INFERRED_SELECTION"
  | "BID_PARTICIPATION"
  | "REVIEW_REQUIRED";

export type InstitutionalAssessmentStepCode =
  | "LP_SOURCE"
  | "TRACK_MATCH"
  | "FOLLOW_UP_ACTION"
  | "DEPLOYMENT_MATCH"
  | "MANAGER_MATCH"
  | "DECISION";

export type InstitutionalAssessmentStepStatus =
  | "CONFIRMED"
  | "SUPPORTED"
  | "MISSING"
  | "CONFLICT";

export type InstitutionalEvidenceRole =
  | "MANDATE_SOURCE"
  | "OFFICIAL_RESULT"
  | "REPORTED_SELECTION"
  | "BID_EVIDENCE"
  | "DEPLOYMENT_EVIDENCE";

export type InstitutionalAssessmentEvidence = RelatedDocument & {
  role: InstitutionalEvidenceRole;
  roleLabel: string;
};

export type InstitutionalAssessmentStep = {
  code: InstitutionalAssessmentStepCode;
  label: string;
  status: InstitutionalAssessmentStepStatus;
  detail: string;
  evidenceDocumentIds: string[];
};

export type InstitutionalSelectionAssessment = {
  assessmentId: string;
  managerOrganizationId: string | null;
  managerName: string;
  trackCode: string | null;
  trackName: string | null;
  verdict: InstitutionalAssessmentVerdict;
  verdictLabel: string;
  confidence: number | null;
  confidenceBand: "HIGH" | "MEDIUM" | "LOW" | "NOT_APPLICABLE";
  rationale: string;
  actionLabel: string;
  reportedAllocation: string | null;
  allocationCurrency: string | null;
  steps: InstitutionalAssessmentStep[];
  evidence: InstitutionalAssessmentEvidence[];
  missingChecks: string[];
};

export type CompanyDetailResponse = {
  organization: {
    organizationId: string;
    name: string;
    organizationType: string;
    stockCode: string | null;
    industry: string | null;
    marketCap: string | null;
    overallRank: number | null;
  };
  counts: { events: number; assets: number; documents: number; occupancies: number; locationEvidence: number };
  events: Array<Record<string, string | number | null>>;
  assets: Array<Record<string, string | number | null>>;
  documents: RelatedDocument[];
  occupancies: Array<Record<string, string | number | null>>;
  locationEvidence: LocationEvidence[];
  generatedAt: string;
  database: "turso-libsql";
};

export type InstitutionalCapitalItem = {
  mandateId: string;
  mandateName: string;
  lpName: string;
  status: string;
  scope: string;
  announcedAt: string | null;
  selectedAt: string | null;
  evidenceStatus: string;
  trackCount: number;
  selectionCount: number;
  amountCount: number;
  guidelineCount: number;
  deploymentCount: number;
  officialSelectionCount: number;
  inferredSelectionCount: number;
  bidParticipationCount: number;
  reviewRequiredCount: number;
  tracks: Array<Record<string, unknown>>;
  amounts: Array<Record<string, unknown>>;
  selections: Array<Record<string, unknown>>;
  deployments: Array<Record<string, unknown>>;
  assessments: InstitutionalSelectionAssessment[];
  documents: RelatedDocument[];
};

export type InstitutionalCapitalResponse = {
  items: InstitutionalCapitalItem[];
  coverage: {
    mandates: number;
    selections: number;
    amounts: number;
    deployments: number;
    officialSelections: number;
    inferredSelections: number;
    bidParticipations: number;
    reviewRequired: number;
  };
  generatedAt: string;
  database: "turso-libsql";
};

export type SaleProcessItem = {
  saleProcessId: string;
  processCode: string;
  title: string;
  status: string;
  saleMethod: string;
  launchedAt: string | null;
  closedAt: string | null;
  evidenceStatus: string;
  assets: Array<Record<string, unknown>>;
  rounds: Array<Record<string, unknown>>;
  milestones: Array<Record<string, unknown>>;
  funding: Array<Record<string, unknown>>;
  documents: RelatedDocument[];
};

export type SaleProcessResearchCandidate = {
  candidateId: string;
  processCode: string;
  title: string;
  assetType: string;
  method: string;
  status: string;
  stageCode: string;
  evidenceGrade: string;
  confidence: number;
  roles: Record<string, unknown>;
  rounds: Array<Record<string, unknown>>;
  milestones: Array<Record<string, unknown>>;
  amounts: Array<Record<string, unknown>>;
  financing: Array<Record<string, unknown>>;
  sources: Array<{ date: string | null; url: string; span: string | null }>;
};

export type SaleProcessResponse = {
  items: SaleProcessItem[];
  candidateProcesses: SaleProcessResearchCandidate[];
  coverage: {
    processes: number;
    rounds: number;
    bidders: number;
    submissions: number;
    decisions: number;
    fundingComponents: number;
    milestones: number;
    signalYear: number;
    candidateCutoffDate: string;
    currentYearProcesses: number;
    currentYearCandidateProcesses: number;
    currentYearArticleSignals: number;
    currentYearPriorityArticleSignals: number;
    currentYearResolvedStageArticleSignals: number;
  };
  generatedAt: string;
  database: "turso-libsql";
};

const companyViewSet = new Set<string>(companyViews);

export function parseCompanyParams(params: URLSearchParams): CompanyListRequest {
  const rawView = params.get("view") ?? "OVERALL";
  const rawLimit = Number.parseInt(params.get("limit") ?? "50", 10);
  return {
    view: (companyViewSet.has(rawView) ? rawView : "OVERALL") as CompanyView,
    industry: (params.get("industry") ?? "").trim().slice(0, 120),
    q: (params.get("q") ?? "").trim().slice(0, 120),
    limit: Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(100, rawLimit) : 50,
  };
}
