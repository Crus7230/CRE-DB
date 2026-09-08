export type SourceOnboarding = "ONBOARDED" | "NOT_ONBOARDED" | "DISABLED";
export type SourceSlaMode = "SCHEDULED" | "EVENT_DRIVEN" | "MANUAL" | "NOT_ONBOARDED";
export type SourceFreshness = "RECENT" | "DUE" | "OVERDUE" | "NO_SLA" | "NEVER_SUCCEEDED";
export type LatestExecution = "QUEUED" | "RUNNING" | "COMPLETED" | "PARTIAL" | "FAILED" | "CANCELLED" | "NONE";
export type DataOutcome = "NEW_DATA" | "ZERO_RESULT" | "REUSED_ONLY" | "UNKNOWN";

export interface SourceHealthItem {
  sourceCode: string;
  sourceName: string;
  sourceKind: string;
  onboarding: SourceOnboarding;
  slaMode: SourceSlaMode;
  freshness: SourceFreshness;
  latestExecution: LatestExecution;
  dataOutcome: DataOutcome;
  activeJobCount: number;
  scheduledJobCount: number;
  runCount: number;
  completedRunCount: number;
  distinctDocumentCount: number;
  documentVersionCount: number;
  latestSuccessfulAt: string | null;
  latestRunAt: string | null;
  expectedIntervalSeconds: number | null;
  graceSeconds: number | null;
  latestDiscoveredCount: number | null;
  latestInsertedCount: number | null;
  latestUpdatedCount: number | null;
  latestRejectedCount: number | null;
}

export type ClassificationSchemeQuality = {
  schemeCode: string;
  schemeName: string;
  cardinality: "SINGLE" | "MULTIPLE";
  vocabularyVersion: string;
  eligibleTargetCount: number;
  assignedTargetCount: number;
  approvedTargetCount: number;
  pendingTargetCount: number;
  primaryTargetCount: number;
  primaryMissingCount: number;
  primaryConflictCount: number;
  deprecatedAssignmentCount: number;
};

export type StatusCount = { status: string; count: number };

export type ClassificationQuality = {
  schemes: ClassificationSchemeQuality[];
  reviewStatusCounts: StatusCount[];
  evidenceStatusCounts: StatusCount[];
  currentAssignmentCount: number;
  supersededAssignmentCount: number;
};

export interface OperationsOverviewResponse {
  generatedAt: string;
  asOfAt: string;
  policyVersion: string;
  summary: {
    sourceCount: number;
    onboardedSourceCount: number;
    notOnboardedSourceCount: number;
    distinctDocumentCount: number;
    documentVersionCount: number;
    runCount: number;
  };
  runStatusCounts: StatusCount[];
  classificationQuality: ClassificationQuality;
  sources: SourceHealthItem[];
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
const finite=(o:Record<string,unknown>,k:string)=>typeof o[k]==="number"&&Number.isFinite(o[k]);
const text=(o:Record<string,unknown>,k:string)=>typeof o[k]==="string"&&Boolean(o[k]);
const nullableNumber=(v:unknown)=>v===null||(typeof v==="number"&&Number.isFinite(v));
const nullableText=(v:unknown)=>v===null||typeof v==="string";
const RUN_STATUSES=new Set(["QUEUED","RUNNING","COMPLETED","PARTIAL","FAILED","CANCELLED"]);
const REVIEW_STATUSES=new Set(["UNREVIEWED","PENDING","APPROVED","REJECTED","SUPERSEDED"]);
const EVIDENCE_STATUSES=new Set(["DIRECT_OFFICIAL","DERIVED_OFFICIAL","DIRECT_STRUCTURED","MEDIA_DIRECT","MANUAL_REVIEWED","INFERRED","UNVERIFIED"]);
const statusCounts=(v:unknown,allowed:Set<string>)=>Array.isArray(v)&&v.every(x=>isRecord(x)&&typeof x.status==="string"&&allowed.has(x.status)&&finite(x,"count"));
export function normalizeOperationsOverview(value: unknown): OperationsOverviewResponse {
  if(!isRecord(value)||!text(value,"generatedAt")||!text(value,"asOfAt")||!text(value,"policyVersion")||!isRecord(value.summary)||!Array.isArray(value.sources)||!statusCounts(value.runStatusCounts,RUN_STATUSES)||!isRecord(value.classificationQuality))throw new Error("Invalid operations overview payload");
  const summary=value.summary; const summaryKeys=["sourceCount","onboardedSourceCount","notOnboardedSourceCount","distinctDocumentCount","documentVersionCount","runCount"];
  if(!summaryKeys.every(k=>finite(summary,k)))throw new Error("Invalid operations summary");
  const q=value.classificationQuality;if(!Array.isArray(q.schemes)||!statusCounts(q.reviewStatusCounts,REVIEW_STATUSES)||!statusCounts(q.evidenceStatusCounts,EVIDENCE_STATUSES)||!["currentAssignmentCount","supersededAssignmentCount"].every(k=>finite(q,k)))throw new Error("Invalid classification quality");
  const schemeNums=["eligibleTargetCount","assignedTargetCount","approvedTargetCount","pendingTargetCount","primaryTargetCount","primaryMissingCount","primaryConflictCount","deprecatedAssignmentCount"];
  const cardinalities=new Set(["SINGLE","MULTIPLE"]);
  if(!q.schemes.every(x=>isRecord(x)&&["schemeCode","schemeName","vocabularyVersion"].every(k=>text(x,k))&&typeof x.cardinality==="string"&&cardinalities.has(x.cardinality)&&schemeNums.every(k=>finite(x,k))))throw new Error("Invalid classification scheme");
  const sourceTextKeys=["sourceCode","sourceName","sourceKind"];
  const allowed={onboarding:new Set(["ONBOARDED","NOT_ONBOARDED","DISABLED"]),slaMode:new Set(["SCHEDULED","EVENT_DRIVEN","MANUAL","NOT_ONBOARDED"]),freshness:new Set(["RECENT","DUE","OVERDUE","NO_SLA","NEVER_SUCCEEDED"]),latestExecution:new Set(["QUEUED","RUNNING","COMPLETED","PARTIAL","FAILED","CANCELLED","NONE"]),dataOutcome:new Set(["NEW_DATA","ZERO_RESULT","REUSED_ONLY","UNKNOWN"])};
  const sourceNums=["activeJobCount","scheduledJobCount","runCount","completedRunCount","distinctDocumentCount","documentVersionCount"];
  if(!value.sources.every(x=>isRecord(x)&&sourceTextKeys.every(k=>text(x,k))&&Object.entries(allowed).every(([k,values])=>typeof x[k]==="string"&&values.has(x[k] as string))&&sourceNums.every(k=>finite(x,k))&&nullableText(x.latestSuccessfulAt)&&nullableText(x.latestRunAt)&&["expectedIntervalSeconds","graceSeconds","latestDiscoveredCount","latestInsertedCount","latestUpdatedCount","latestRejectedCount"].every(k=>nullableNumber(x[k]))))throw new Error("Invalid source health");
  return value as unknown as OperationsOverviewResponse;
}
