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
  metadata: Record<string, unknown>;
};

export type SearchResponse = {
  request: SearchRequest;
  results: SearchResult[];
  facets: Record<Exclude<SearchKind, "ALL">, number>;
  total: number;
  elapsedMs: number;
  generatedAt: string;
  database: "supabase-postgresql";
};

export type CategoryIndexItem = {
  key: string;
  label: string;
  itemCount: number;
  canonicalCount?: number;
};

export type CategoryIndexGroup = {
  group: "EVENT_CATEGORY" | "ASSET_CLASS" | "DOCUMENT_TYPE" | "ORGANIZATION_TYPE" | "LP_STATUS" | "SALE_STATUS";
  label: string;
  kind: Exclude<SearchKind, "ALL">;
  items: CategoryIndexItem[];
};

export type CategoryIndexResponse = {
  groups: CategoryIndexGroup[];
  generatedAt: string;
  elapsedMs: number;
  database: "supabase-postgresql";
};

const kindSet = new Set<string>(searchKinds);
const isoDate = /^\d{4}-\d{2}-\d{2}$/;

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
    from: validDate(params.get("from")),
    to: validDate(params.get("to")),
    page: positiveInteger(params.get("page"), 1),
    pageSize: Math.min(50, positiveInteger(params.get("pageSize"), 20)),
    includeTransactionsUnder1000Eok: params.get("includeTransactionsUnder1000Eok") === "true",
  };
}
