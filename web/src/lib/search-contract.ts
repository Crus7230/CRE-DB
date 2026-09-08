export const searchKinds = [
  "ALL",
  "EVENT",
  "ASSET",
  "ORGANIZATION",
  "DOCUMENT",
  "LP_MANDATE",
  "SALE_PROCESS",
] as const;

export type SearchKind = (typeof searchKinds)[number];

export type SearchRequest = {
  q: string;
  kind: SearchKind;
  category: string;
  classificationScheme: string;
  from: string | null;
  to: string | null;
  page: number;
  pageSize: number;
  includeTransactionsUnder1000Eok: boolean;
};

export type SearchResult = {
  kind: Exclude<SearchKind, "ALL">;
  id: string;
  title: string;
  subtitle: string | null;
  summary: string | null;
  date: string | null;
  status: string | null;
  confidence: number | null;
  source: string | null;
  href: string | null;
  category: string | null;
  categoryLabel: string | null;
  metadata: SearchResultMetadata;
};

export type SearchResultMetadata = Record<string, unknown> & {
  documentPurposeCode?: string;
  documentPurposeLabel?: string;
  evidenceGradeCode?: string;
  evidenceGradeLabel?: string;
  classificationCount?: number;
  evidenceCount?: number;
};

export type RecordClassification = {
  schemeCode: string;
  schemeLabel: string;
  termCode: string;
  termLabel: string;
  parentCode: string | null;
  parentLabel: string | null;
  isPrimary: boolean;
  assignmentRole: string;
  evidenceStatus: string;
  reviewStatus: string;
  confidence: number | null;
};

export type SearchResponse = {
  request: SearchRequest;
  results: SearchResult[];
  facets: Record<Exclude<SearchKind, "ALL">, number>;
  total: number;
  elapsedMs: number;
  generatedAt: string;
  database: "turso-libsql";
};

export type CategoryIndexItem = {
  key: string;
  label: string;
  itemCount: number;
  canonicalCount?: number;
  parentKey?: string | null;
  parentLabel?: string | null;
  countsByKind?: Record<string, number>;
  yearToDateCountsByKind?: Record<string, number>;
};

export type CategoryIndexGroup = {
  group: "MARKET_CATEGORY" | "DOCUMENT_PURPOSE" | "ASSET_CLASS" | "EVIDENCE_GRADE" | "EVENT_CATEGORY" | "DOCUMENT_TYPE" | "ORGANIZATION_TYPE" | "LP_STATUS" | "SALE_STATUS";
  label: string;
  kind: SearchKind;
  items: CategoryIndexItem[];
  classificationScheme?: string;
  targetKinds?: string[];
  countSemantics?: string;
  countWindow?: { from: string; to: string };
  vocabularyVersion?: string;
};

export type CategoryIndexResponse = {
  groups: CategoryIndexGroup[];
  generatedAt: string;
  elapsedMs: number;
  database: "turso-libsql";
};

const kindSet = new Set<string>(searchKinds);
const isoDate = /^\d{4}-\d{2}-\d{2}$/;

export function hasInvalidSearchDateRange(from: string, to: string): boolean {
  return Boolean(from && to && from > to);
}

export function koreanIsoDate(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? "";
  return `${value("year")}-${value("month")}-${value("day")}`;
}

function validDate(value: string | null): string | null {
  if (!value || !isoDate.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value ? null : value;
}

function positiveInteger(value: string | null, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function parseSearchParams(params: URLSearchParams): SearchRequest {
  const rawKind = params.get("kind") ?? "ALL";
  return {
    q: (params.get("q") ?? "").trim().slice(0, 120),
    kind: (kindSet.has(rawKind) ? rawKind : "ALL") as SearchKind,
    category: (params.get("category") ?? "").trim().slice(0, 100),
    classificationScheme: (params.get("classificationScheme") ?? "").trim().slice(0, 100),
    from: validDate(params.get("from")),
    to: validDate(params.get("to")),
    page: positiveInteger(params.get("page"), 1),
    pageSize: Math.min(50, positiveInteger(params.get("pageSize"), 20)),
    includeTransactionsUnder1000Eok: params.get("includeTransactionsUnder1000Eok") === "true",
  };
}
