export const EVIDENCE_SEARCH_MAX_RESULTS = 8;
export const EVIDENCE_SEARCH_DEFAULT_RESULTS = 8;

export type EvidenceSearchRequest = {
  q: string;
  from: string | null;
  to: string | null;
  topic: string | null;
  topK: number;
};

export type EvidenceSearchItem = {
  documentId: string;
  title: string;
  publisher: string | null;
  publishedAt: string;
  href: string | null;
  evidenceText: string;
  score: number;
};

export type EvidenceSearchResponse = {
  datasetVersion: string;
  query: string;
  generatedAt: string;
  filters: Pick<EvidenceSearchRequest, "from" | "to" | "topic">;
  returned: number;
  truncated: boolean;
  maxResults: number;
  items: EvidenceSearchItem[];
};

export class EvidenceSearchRequestError extends Error {
  readonly code = "INVALID_EVIDENCE_SEARCH";

  constructor(message: string) {
    super(message);
    this.name = "EvidenceSearchRequestError";
  }
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/u;
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/u;
const UNSAFE_RESPONSE_CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u;

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function boundedText(
  value: unknown,
  name: string,
  maximum: number,
  options: { nullable: true; minimum?: number },
): string | null;
function boundedText(
  value: unknown,
  name: string,
  maximum: number,
  options?: { nullable?: false; minimum?: number },
): string;
function boundedText(
  value: unknown,
  name: string,
  maximum: number,
  options: { nullable?: boolean; minimum?: number } = {},
) {
  if ((value === null || value === undefined || value === "") && options.nullable) return null;
  if (typeof value !== "string") throw new EvidenceSearchRequestError(`Invalid ${name}`);
  const normalized = value.trim();
  if (
    normalized.length < (options.minimum ?? 1)
    || normalized.length > maximum
    || CONTROL_CHARACTER.test(normalized)
  ) {
    throw new EvidenceSearchRequestError(`Invalid ${name}`);
  }
  return normalized;
}

function validDate(value: string) {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function optionalDate(value: unknown, name: string) {
  const normalized = boundedText(value, name, 10, { nullable: true });
  if (normalized && !validDate(normalized)) throw new EvidenceSearchRequestError(`Invalid ${name}`);
  return normalized;
}

export function parseEvidenceSearchBody(value: unknown): EvidenceSearchRequest {
  if (!record(value)) throw new EvidenceSearchRequestError("Invalid evidence search body");
  const q = boundedText(value.q, "query", 200, { minimum: 2 });
  const from = optionalDate(value.from, "from");
  const to = optionalDate(value.to, "to");
  if (from && to && from > to) throw new EvidenceSearchRequestError("Invalid date range");
  const topic = boundedText(value.topic, "topic", 80, { nullable: true });
  const requestedTopK = value.topK ?? EVIDENCE_SEARCH_DEFAULT_RESULTS;
  if (
    typeof requestedTopK !== "number"
    || !Number.isSafeInteger(requestedTopK)
    || requestedTopK < 1
    || requestedTopK > EVIDENCE_SEARCH_MAX_RESULTS
  ) {
    throw new EvidenceSearchRequestError("Invalid topK");
  }
  return { q, from, to, topic, topK: requestedTopK };
}

function responseText(value: unknown, name: string, maximum: number) {
  if (typeof value !== "string" || !value || value.length > maximum || UNSAFE_RESPONSE_CONTROL.test(value)) {
    throw new Error(`Invalid evidence search ${name}`);
  }
  return value;
}

function evidenceText(value: unknown) {
  const text = responseText(value, "evidence", 4_000).replace(/\s+/gu, " ").trim();
  if (!text) throw new Error("Invalid evidence search evidence");
  return text;
}

function nullableResponseText(value: unknown, name: string, maximum: number) {
  if (value === null || value === undefined || value === "") return null;
  return responseText(value, name, maximum);
}

function safeHttpUrl(value: unknown) {
  const text = nullableResponseText(value, "href", 2_048);
  if (!text) return null;
  let parsed: URL;
  try {
    parsed = new URL(text);
  } catch {
    throw new Error("Invalid evidence search href");
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error("Invalid evidence search href");
  }
  return parsed.toString();
}

export function normalizeEvidenceSearchResponse(
  value: unknown,
  request: EvidenceSearchRequest,
  expectedDatasetVersion?: string,
): EvidenceSearchResponse {
  if (!record(value) || !Array.isArray(value.items)) throw new Error("Invalid evidence search payload");
  const datasetVersion = responseText(value.datasetVersion, "dataset version", 256);
  if (expectedDatasetVersion && datasetVersion !== expectedDatasetVersion) {
    throw new Error("Evidence search dataset version mismatch");
  }
  const query = responseText(value.query, "query", 200);
  if (query !== request.q) throw new Error("Evidence search query mismatch");
  if (value.items.length > request.topK || value.items.length > EVIDENCE_SEARCH_MAX_RESULTS) {
    throw new Error("Evidence search result limit exceeded");
  }
  const seen = new Set<string>();
  const items = value.items.map((item) => {
    if (!record(item)) throw new Error("Invalid evidence search item");
    const documentId = responseText(item.documentId, "document id", 256);
    if (seen.has(documentId)) throw new Error("Duplicate evidence search item");
    seen.add(documentId);
    if (typeof item.score !== "number" || !Number.isFinite(item.score) || item.score < 0) {
      throw new Error("Invalid evidence search score");
    }
    return {
      documentId,
      title: responseText(item.title, "title", 800),
      publisher: nullableResponseText(item.publisher, "publisher", 256),
      publishedAt: responseText(item.publishedAt, "published at", 64),
      href: safeHttpUrl(item.href),
      evidenceText: evidenceText(item.evidenceText),
      score: item.score,
    };
  });
  const returned = value.returned === undefined ? items.length : value.returned;
  if (returned !== items.length) throw new Error("Evidence search returned count mismatch");
  if (typeof value.truncated !== "undefined" && typeof value.truncated !== "boolean") {
    throw new Error("Invalid evidence search truncated flag");
  }
  return {
    datasetVersion,
    query,
    generatedAt: responseText(value.generatedAt, "generated at", 64),
    filters: { from: request.from, to: request.to, topic: request.topic },
    returned: items.length,
    truncated: value.truncated === true,
    maxResults: request.topK,
    items,
  };
}
