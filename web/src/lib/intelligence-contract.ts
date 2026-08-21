export const companyViews = ["OVERALL", "INDUSTRY", "TENANT_SIGNALS"] as const;
export type CompanyView = (typeof companyViews)[number];

export type CompanyListRequest = {
  view: CompanyView;
  industry: string;
  q: string;
  limit: number;
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
  leaseDocumentSignalCount: number;
};

export type CompanyListResponse = {
  request: CompanyListRequest;
  snapshotDate: string | null;
  items: CompanyListItem[];
  industries: Array<{ name: string; count: number }>;
  coverage: {
    verifiedOccupancies: number;
    companiesWithLeaseDocumentSignals: number;
    signalNote: string;
  };
  generatedAt: string;
  database: "supabase-postgresql";
};

export type RelatedDocument = {
  documentId: string;
  title: string;
  documentType: string | null;
  publishedAt: string | null;
  publisher: string | null;
  href: string | null;
  relationBasis: "CANONICAL_EVENT" | "RESOLVED_MENTION" | "VERIFIED_CLAIM" | "EXACT_NAME_SIGNAL" | "SOURCE_CLAIM";
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
  counts: { events: number; assets: number; documents: number; occupancies: number };
  events: Array<Record<string, string | number | null>>;
  assets: Array<Record<string, string | number | null>>;
  documents: RelatedDocument[];
  occupancies: Array<Record<string, string | number | null>>;
  generatedAt: string;
  database: "supabase-postgresql";
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
  tracks: Array<Record<string, unknown>>;
  amounts: Array<Record<string, unknown>>;
  selections: Array<Record<string, unknown>>;
  documents: RelatedDocument[];
};

export type InstitutionalCapitalResponse = {
  items: InstitutionalCapitalItem[];
  coverage: { mandates: number; selections: number; amounts: number; deployments: number };
  generatedAt: string;
  database: "supabase-postgresql";
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

export type SaleProcessResponse = {
  items: SaleProcessItem[];
  coverage: { processes: number; rounds: number; bidders: number; submissions: number; decisions: number; fundingComponents: number; milestones: number };
  generatedAt: string;
  database: "supabase-postgresql";
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
