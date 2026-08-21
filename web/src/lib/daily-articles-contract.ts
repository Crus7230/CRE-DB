export type DailyArticleTopic = {
  key: string;
  label: string;
  status: "CONFIRMED" | "CANDIDATE";
  provenance: "APPROVED_EVENT_MENTION" | "COLLECTION_QUERY";
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
  articles: DailyArticle[];
};

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
