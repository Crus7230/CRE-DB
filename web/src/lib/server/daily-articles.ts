import {
  normalizeDailyArticles,
  type DailyArticlesResponse,
} from "@/lib/daily-articles-contract";

export type DailyArticleSqlExecutor = (
  text: string,
  values: readonly (string | number | null)[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

// Online reads are intentionally restricted to refresh-built serving tables.
// Governed scope/classification selection remains in the offline materializer,
// where it is parity-tested against the former raw-history query.
export const dailyArticlesSql = `
WITH article_stats AS MATERIALIZED (
  SELECT (
    SELECT article_date
    FROM serving_daily_article_dates
    ORDER BY article_date DESC
    LIMIT 1
  ) AS latest_available_date,(
    SELECT last_collected_at
    FROM serving_daily_article_dates
    WHERE last_collected_at IS NOT NULL
    ORDER BY article_date DESC
    LIMIT 1
  ) AS last_collected_at
), selected_day AS MATERIALIZED (
  SELECT CASE WHEN $1='LATEST'
      THEN coalesce(latest_available_date,date('now','+9 hours'))
      ELSE $1
    END AS selected_date
  FROM article_stats
), selected_articles AS MATERIALIZED (
  SELECT article.*
  FROM selected_day day
  CROSS JOIN serving_daily_articles article
  WHERE article.article_date=day.selected_date
  ORDER BY article.published_at DESC,article.document_id
  LIMIT 200
)
SELECT json_object(
  'selectedDate',(SELECT selected_date FROM selected_day),
  'latestAvailableDate',(SELECT latest_available_date FROM article_stats),
  'lastCollectedAt',(SELECT last_collected_at FROM article_stats),
  'generatedAt',strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  'total',coalesce((
    SELECT dates.article_count
    FROM selected_day day
    CROSS JOIN serving_daily_article_dates dates
    WHERE dates.article_date=day.selected_date
  ),0),
  'returned',(SELECT count(*) FROM selected_articles),
  'articles',json(COALESCE((SELECT json_group_array(json_object(
    'id',article.document_id,
    'title',article.title,
    'publisher',article.publisher_name,
    'publishedAt',article.published_at,
    'collectedAt',article.collected_at,
    'summary',article.summary_text,
    'summaryMode',article.summary_mode,
    'summaryGeneratedAt',article.summary_generated_at,
    'href',article.canonical_url,
    'topics',json(COALESCE((
      SELECT json_group_array(json_object(
        'key',topic.term_code,
        'label',topic.term_label,
        'status',topic.status_code,
        'provenance',topic.provenance_code
      ))
      FROM (
        SELECT term_code,term_label,status_code,provenance_code
        FROM serving_daily_article_topics
        WHERE document_id=article.document_id
        ORDER BY topic_rank,term_code
      ) topic
    ),'[]')),
    'documentPurpose',CASE WHEN article.document_purpose_code IS NULL THEN NULL ELSE json_object(
      'code',article.document_purpose_code,'label',article.document_purpose_label) END,
    'evidenceGrade',CASE WHEN article.evidence_grade_code IS NULL THEN NULL ELSE json_object(
      'code',article.evidence_grade_code,'label',article.evidence_grade_label) END
  )) FROM (
    SELECT * FROM selected_articles
    ORDER BY published_at DESC,document_id
  ) article),'[]'))
) AS payload`;

export async function getDailyArticles(
  execute: DailyArticleSqlExecutor,
  selectedDate: string,
): Promise<DailyArticlesResponse> {
  const query = await execute(dailyArticlesSql, [selectedDate]);
  return normalizeDailyArticles(query.rows[0]?.payload);
}
