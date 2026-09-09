import type {
  EvidenceSearchRequest,
  EvidenceSearchResponse,
} from "@/lib/evidence-search-contract";
import { normalizeEvidenceSearchResponse } from "@/lib/evidence-search-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

// Local split snapshots do not carry the PostgreSQL trigram/search-term
// indexes. Keep their compatibility path bounded to the compact news serving
// projection; hosted requests always use dashboard_contextual_evidence_search.
export const localEvidenceSearchSql = String.raw`
WITH candidates AS MATERIALIZED (
  SELECT article.*,
    CASE
      WHEN instr(lower(article.title),lower($1))>0 THEN 1.0
      WHEN instr(lower(coalesce(article.summary_text,'')),lower($1))>0 THEN 0.75
      ELSE 0.6
    END AS match_score
  FROM serving_daily_articles article
  WHERE ($2 IS NULL OR article.article_date >= $2)
    AND ($3 IS NULL OR article.article_date <= $3)
    AND ($4 IS NULL OR EXISTS (
      SELECT 1 FROM serving_daily_article_topics topic_filter
      WHERE topic_filter.document_id=article.document_id
        AND topic_filter.term_code=$4
    ))
    AND (
      instr(lower(article.title),lower($1))>0
      OR instr(lower(coalesce(article.summary_text,'')),lower($1))>0
      OR EXISTS (
        SELECT 1 FROM serving_daily_article_topics topic_match
        WHERE topic_match.document_id=article.document_id
          AND (
            instr(lower(topic_match.term_label),lower($1))>0
            OR instr(lower(topic_match.term_code),lower($1))>0
          )
      )
    )
  ORDER BY match_score DESC,article.published_at DESC,article.document_id
  LIMIT $5 + 1
), displayed AS MATERIALIZED (
  SELECT * FROM candidates
  ORDER BY match_score DESC,published_at DESC,document_id
  LIMIT $5
)
SELECT json_object(
  'datasetVersion',$6,
  'query',$1,
  'generatedAt',$7,
  'filters',json_object('from',$2,'to',$3,'topic',$4),
  'returned',(SELECT count(*) FROM displayed),
  'truncated',json(CASE WHEN (SELECT count(*) FROM candidates)>$5 THEN 'true' ELSE 'false' END),
  'items',json(COALESCE((SELECT json_group_array(json_object(
    'documentId',candidate.document_id,
    'title',candidate.title,
    'publisher',candidate.publisher_name,
    'publishedAt',candidate.published_at,
    'href',candidate.canonical_url,
    'evidenceText',CASE
      WHEN instr(lower(candidate.title),lower($1))>0 THEN candidate.title
      ELSE coalesce(nullif(substr(candidate.summary_text,1,800),''),candidate.title)
    END,
    'score',candidate.match_score
  )) FROM (
    SELECT * FROM displayed
    ORDER BY match_score DESC,published_at DESC,document_id
  ) candidate),'[]'))
) AS payload`;

export async function searchLocalArticleEvidence(
  execute: SqlExecutor,
  request: EvidenceSearchRequest,
  datasetVersion: string,
  clock: () => Date = () => new Date(),
): Promise<EvidenceSearchResponse> {
  const result = await execute(localEvidenceSearchSql, [
    request.q,
    request.from,
    request.to,
    request.topic,
    request.topK,
    datasetVersion,
    clock().toISOString(),
  ]);
  return normalizeEvidenceSearchResponse(result.rows[0]?.payload, request, datasetVersion);
}
