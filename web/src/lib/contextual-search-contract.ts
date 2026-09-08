export type ContextualSearchMode = "APPROVED" | "CANDIDATE" | "LEGACY";

export type ContextualSearchRequest = {
  q: string;
  mode: ContextualSearchMode;
  domain: string;
  eventType: string;
  stage: string;
  processType: string;
  role: string;
  participantEntityId: string;
  assetId: string;
  region: string;
  industry: string;
  impact: string;
  sourceGrade: string;
  from: string;
  to: string;
  page: number;
  pageSize: number;
};

export type ContextualSearchResult = {
  id: string;
  mode: ContextualSearchMode;
  sourceRecordKind: string;
  sourceRecordId: string;
  title: string;
  summary: string | null;
  eventDomain: string | null;
  eventType: string | null;
  stageCode: string | null;
  processType: string | null;
  actionCode: string | null;
  eventDate: string | null;
  temporalBasis: string | null;
  participantRoles: string[];
  participantEntityIds: string[];
  assetIds: string[];
  regionIds: string[];
  industryCodes: string[];
  impactDirections: string[];
  sourceGrade: string | null;
  confidence: number | null;
  reviewStatus: string;
  evidenceText: string | null;
  ruleVersion: string | null;
  modelVersion: string | null;
  metadata: Record<string, unknown>;
};

export type ContextualSearchResponse = {
  request: ContextualSearchRequest;
  total: number;
  facets: Record<string, Array<{ key: string; count: number }>>;
  results: ContextualSearchResult[];
  generatedAt?: string;
  elapsedMs?: number;
  database?: string;
};

const MODES = new Set<ContextualSearchMode>(["APPROVED", "CANDIDATE", "LEGACY"]);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function value(params: URLSearchParams, key: string, max = 160) {
  const raw = (params.get(key) ?? "").trim();
  if (raw.length > max || /[\u0000-\u001f\u007f]/.test(raw)) {
    throw new Error(`Invalid contextual search ${key}`);
  }
  return raw;
}

function positiveInt(raw: string, fallback: number, max: number, key: string) {
  if (!raw) return fallback;
  if (!/^\d+$/.test(raw)) throw new Error(`Invalid contextual search ${key}`);
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > max) {
    throw new Error(`Invalid contextual search ${key}`);
  }
  return parsed;
}

function validDate(raw: string) {
  if (!DATE_RE.test(raw)) return false;
  const parsed = new Date(`${raw}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === raw;
}

export function parseContextualSearchParams(params: URLSearchParams): ContextualSearchRequest {
  const rawMode = value(params, "mode", 20) || "APPROVED";
  if (!MODES.has(rawMode as ContextualSearchMode)) throw new Error("Invalid contextual search mode");
  const from = value(params, "from", 10);
  const to = value(params, "to", 10);
  if ((from && !validDate(from)) || (to && !validDate(to)) || (from && to && from > to)) {
    throw new Error("Invalid contextual search date range");
  }
  return {
    q: value(params, "q", 200),
    mode: rawMode as ContextualSearchMode,
    domain: value(params, "domain", 80),
    eventType: value(params, "eventType", 80),
    stage: value(params, "stage", 80),
    processType: value(params, "processType", 80),
    role: value(params, "role", 80),
    participantEntityId: value(params, "participantEntityId", 160),
    assetId: value(params, "assetId", 160),
    region: value(params, "region", 160),
    industry: value(params, "industry", 160),
    impact: value(params, "impact", 80),
    sourceGrade: value(params, "sourceGrade", 80),
    from,
    to,
    page: positiveInt(value(params, "page", 10), 1, 10_000, "page"),
    pageSize: positiveInt(value(params, "pageSize", 10), 50, 100, "pageSize"),
  };
}
