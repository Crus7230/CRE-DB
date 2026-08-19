import type { DailyArticlesResponse } from "@/lib/daily-articles-contract";

export type DailyArticleSqlExecutor = (
  text: string,
  values: readonly (string | number | null)[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

const dailyArticlesSql = `
WITH latest_versions AS (
  SELECT DISTINCT ON (dv.document_id)
         dv.document_id, dv.title, dv.published_at, dv.collected_at,
         dv.snippet_text, sd.publisher_name, sd.canonical_url
  FROM market_intelligence.document_versions dv
  JOIN market_intelligence.source_documents sd ON sd.document_id = dv.document_id
  WHERE sd.document_type IN ('RSS_ITEM','ARTICLE')
    AND dv.published_at IS NOT NULL
  ORDER BY dv.document_id, dv.version_no DESC
), article_stats AS (
  SELECT max((published_at::timestamptz AT TIME ZONE 'Asia/Seoul')::date) AS latest_available_date,
         max(collected_at::timestamptz) AS last_collected_at
  FROM latest_versions
), selected_articles AS (
  SELECT * FROM latest_versions
  WHERE (published_at::timestamptz AT TIME ZONE 'Asia/Seoul')::date = $1::date
  ORDER BY published_at::timestamptz DESC, document_id
  LIMIT 200
)
SELECT jsonb_build_object(
  'selectedDate', $1::text,
  'latestAvailableDate', (SELECT latest_available_date::text FROM article_stats),
  'lastCollectedAt', (SELECT last_collected_at::text FROM article_stats),
  'generatedAt', to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
  'total', (SELECT count(*)::int FROM selected_articles),
  'articles', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'id', document_id,
      'title', coalesce(title, '제목 없음'),
      'publisher', publisher_name,
      'publishedAt', published_at,
      'collectedAt', collected_at,
      'summary', snippet_text,
      'href', canonical_url
    ) ORDER BY published_at::timestamptz DESC, document_id)
    FROM selected_articles
  ), '[]'::jsonb)
) AS payload`;

export async function getDailyArticles(
  execute: DailyArticleSqlExecutor,
  selectedDate: string,
): Promise<DailyArticlesResponse> {
  const query = await execute(dailyArticlesSql, [selectedDate]);
  const payload = query.rows[0]?.payload as DailyArticlesResponse | undefined;
  if (!payload || !Array.isArray(payload.articles)) throw new Error("Invalid daily articles response");
  return payload;
}
