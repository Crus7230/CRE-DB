export type DailyArticleTopic = {
  key: string;
  label: string;
  status: "CONFIRMED" | "CANDIDATE";
  provenance:
    | "APPROVED_CLASSIFICATION"
    | "PENDING_CLASSIFICATION"
    /** @deprecated Accepted only while older cached payloads expire. */
    | "APPROVED_EVENT_MENTION"
    /** @deprecated Accepted only while older cached payloads expire. */
    | "COLLECTION_QUERY";
};

export type DailyArticleClassification = {
  code: string;
  label: string;
};

export type DailyArticle = {
  id: string;
  title: string;
  publisher: string | null;
  publishedAt: string;
  collectedAt: string;
  summary: string | null;
  summaryMode: "BODY_EXTRACTIVE" | "MODEL" | "NONE";
  summaryGeneratedAt: string | null;
  href: string | null;
  /** Server-ranked; the first topic is the representative grouping topic. */
  topics: DailyArticleTopic[];
  documentPurpose?: DailyArticleClassification | null;
  evidenceGrade?: DailyArticleClassification | null;
};

export type DailyArticlesResponse = {
  selectedDate: string;
  latestAvailableDate: string | null;
  lastCollectedAt: string | null;
  generatedAt: string;
  total: number;
  /** Number of rows returned after the server-side response limit. */
  returned: number;
  articles: DailyArticle[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || !value) throw new Error(`Invalid ${key}`);
  return value;
}

function nullableText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") throw new Error("Invalid nullable text");
  return value;
}

function classification(value: unknown): DailyArticleClassification | null {
  if (value === null || value === undefined) return null;
  if (!isRecord(value)) throw new Error("Invalid article classification");
  return { code: text(value, "code"), label: text(value, "label") };
}

export function normalizeDailyArticles(value: unknown): DailyArticlesResponse {
  if (!isRecord(value) || !Array.isArray(value.articles) || typeof value.total !== "number" || !Number.isFinite(value.total)) {
    throw new Error("Invalid daily articles payload");
  }
  const returned = value.returned === undefined ? value.articles.length : value.returned;
  if (typeof returned !== "number" || !Number.isFinite(returned)) {
    throw new Error("Invalid returned article count");
  }
  return {
    selectedDate: text(value, "selectedDate"),
    latestAvailableDate: nullableText(value.latestAvailableDate),
    lastCollectedAt: nullableText(value.lastCollectedAt),
    generatedAt: text(value, "generatedAt"),
    total: value.total,
    returned,
    articles: value.articles.map((raw) => {
      if (!isRecord(raw)) throw new Error("Invalid daily article");
      const summaryMode = text(raw, "summaryMode");
      if (!["BODY_EXTRACTIVE", "MODEL", "NONE"].includes(summaryMode)) throw new Error("Invalid summary mode");
      const topics = raw.topics === undefined ? [] : raw.topics;
      if (!Array.isArray(topics)) throw new Error("Invalid topics");
      return {
        id: text(raw, "id"), title: text(raw, "title"), publisher: nullableText(raw.publisher),
        publishedAt: text(raw, "publishedAt"), collectedAt: text(raw, "collectedAt"),
        summary: nullableText(raw.summary), summaryMode: summaryMode as DailyArticle["summaryMode"],
        summaryGeneratedAt: nullableText(raw.summaryGeneratedAt), href: nullableText(raw.href),
        topics: topics.map((topic) => {
          if (!isRecord(topic)) throw new Error("Invalid topic");
          const status = text(topic, "status"); const provenance = text(topic, "provenance");
          if (
            !["CONFIRMED", "CANDIDATE"].includes(status)
            || ![
              "APPROVED_CLASSIFICATION",
              "PENDING_CLASSIFICATION",
              "APPROVED_EVENT_MENTION",
              "COLLECTION_QUERY",
            ].includes(provenance)
          ) throw new Error("Invalid topic enum");
          return { key: text(topic, "key"), label: text(topic, "label"), status: status as DailyArticleTopic["status"], provenance: provenance as DailyArticleTopic["provenance"] };
        }),
        documentPurpose: classification(raw.documentPurpose), evidenceGrade: classification(raw.evidenceGrade),
      };
    }),
  };
}

const isoDate = /^\d{4}-\d{2}-\d{2}$/;

export function todayInSeoul(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

export function parseDailyArticleDate(value: string | null, now = new Date()): string {
  if (!value || !isoDate.test(value)) return todayInSeoul(now);
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value
    ? todayInSeoul(now)
    : value;
}

export function resolveDailyArticleDate(value: string | null, now = new Date()): string {
  return value === null ? "LATEST" : parseDailyArticleDate(value, now);
}
