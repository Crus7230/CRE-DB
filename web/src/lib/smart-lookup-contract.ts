export type LookupKind = "auto" | "address" | "company";
export type ResolvedLookupKind = Exclude<LookupKind, "auto">;
export type LookupSourceState = "ok" | "empty" | "unconfigured" | "error" | "timeout";

export interface LookupSource {
  id: string;
  label: string;
  status: LookupSourceState;
  message?: string;
  checkedAt?: string;
  asOf?: string;
}

export interface LookupCard {
  id: string;
  presentation?: "building" | "company" | "disclosures" | "security";
  title: string;
  sourceLabel: string;
  subtitle?: string;
  fields: Array<{ label: string; value: string }>;
  links?: Array<{ label: string; url: string }>;
  note?: string;
  asOf?: string;
}

export interface LookupCandidate {
  /** Short-lived signed selection token; never an arbitrary external URL. */
  id: string;
  kind: ResolvedLookupKind;
  title: string;
  subtitle: string;
  sourceLabel: string;
}

export interface LookupRequest {
  query: string;
  kind?: LookupKind;
  selection?: string;
}

export interface LookupResponse {
  query: string;
  kind: LookupKind;
  stage: "candidates" | "detail" | "empty" | "unavailable";
  candidates: LookupCandidate[];
  cards: LookupCard[];
  sources: LookupSource[];
  queriedAt: string;
  message?: string;
  cacheHit?: boolean;
}

/** Conservative hint only. Ambiguous names are resolved across both domains. */
export function detectLookupKind(query: string): LookupKind {
  const text = query.trim();
  if (/^\d{6}$/.test(text) || /^\d{8}$/.test(text) || /주식회사|\(주\)|㈜/.test(text)) return "company";
  if (/\d/.test(text) && /(?:특별시|광역시|특별자치시|특별자치도|[가-힣]+(?:시|군|구|동|읍|면|리|로|길))/.test(text)) return "address";
  return "auto";
}
