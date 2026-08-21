import type { DailyArticlesResponse } from "@/lib/daily-articles-contract";

export type DailyArticleSqlExecutor = (
  text: string,
  values: readonly (string | number | null)[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

const dailyArticlesSql = `
WITH runtime AS (
  SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS now_utc
), market_category_terms AS (
  SELECT t.term_code,t.term_name_ko
  FROM market_intelligence.classification_schemes s
  JOIN market_intelligence.classification_terms t
    ON t.classification_scheme_id=s.classification_scheme_id
  CROSS JOIN runtime rt
  WHERE s.scheme_code='MARKET_CATEGORY'
    AND s.governance_status='ACTIVE' AND t.governance_status='ACTIVE' AND t.is_assignable=1
    AND (s.valid_from IS NULL OR s.valid_from<=rt.now_utc)
    AND (s.valid_to IS NULL OR s.valid_to>rt.now_utc)
    AND (t.valid_from IS NULL OR t.valid_from<=rt.now_utc)
    AND (t.valid_to IS NULL OR t.valid_to>rt.now_utc)
), latest_versions AS (
  SELECT DISTINCT ON (dv.document_id)
         dv.document_id, dv.document_version_id, dv.title, dv.published_at, dv.collected_at,
         de.summary_text, de.summary_method, de.generated_at AS summary_generated_at,
         sd.publisher_name, coalesce(de.resolved_url,sd.canonical_url) AS canonical_url,
         cls.document_purpose_code,cls.document_purpose_label,
         cls.evidence_grade_code,cls.evidence_grade_label
  FROM market_intelligence.document_versions dv
  JOIN market_intelligence.source_documents sd ON sd.document_id = dv.document_id
  LEFT JOIN LATERAL (
    SELECT summary_text,summary_method,generated_at,resolved_url
    FROM market_intelligence.document_enrichments de
    WHERE de.document_version_id=dv.document_version_id
      AND de.enrichment_kind='CONTENT_SUMMARY'
      AND de.status_code='COMPLETED'
      AND de.review_status<>'REJECTED'
    ORDER BY CASE WHEN de.review_status='APPROVED' THEN 0 ELSE 1 END,
      de.generated_at DESC,de.document_enrichment_id DESC
    LIMIT 1
  ) de ON true
  LEFT JOIN LATERAL (
    SELECT
      max(t.term_code) FILTER (WHERE s.scheme_code='DOCUMENT_PURPOSE' AND rc.is_primary=1) AS document_purpose_code,
      max(t.term_name_ko) FILTER (WHERE s.scheme_code='DOCUMENT_PURPOSE' AND rc.is_primary=1) AS document_purpose_label,
      max(t.term_code) FILTER (WHERE s.scheme_code='EVIDENCE_GRADE' AND rc.is_primary=1) AS evidence_grade_code,
      max(t.term_name_ko) FILTER (WHERE s.scheme_code='EVIDENCE_GRADE' AND rc.is_primary=1) AS evidence_grade_label
    FROM market_intelligence.record_classifications rc
    JOIN market_intelligence.classification_schemes s
      ON s.classification_scheme_id=rc.classification_scheme_id
    JOIN market_intelligence.classification_terms t
      ON t.classification_scheme_id=rc.classification_scheme_id
     AND t.classification_term_id=rc.classification_term_id
    CROSS JOIN runtime rt
    WHERE rc.target_kind='DOCUMENT' AND rc.target_id=dv.document_id
      AND s.scheme_code IN ('DOCUMENT_PURPOSE','EVIDENCE_GRADE')
      AND rc.review_status NOT IN ('REJECTED','SUPERSEDED')
      AND (rc.valid_from IS NULL OR rc.valid_from<=rt.now_utc)
      AND (rc.valid_to IS NULL OR rc.valid_to>rt.now_utc)
      AND s.governance_status='ACTIVE' AND t.governance_status='ACTIVE'
      AND (s.valid_from IS NULL OR s.valid_from<=rt.now_utc)
      AND (s.valid_to IS NULL OR s.valid_to>rt.now_utc)
      AND (t.valid_from IS NULL OR t.valid_from<=rt.now_utc)
      AND (t.valid_to IS NULL OR t.valid_to>rt.now_utc)
  ) cls ON true
  WHERE sd.document_type IN ('RSS_ITEM','ARTICLE')
    AND dv.published_at IS NOT NULL
  ORDER BY dv.document_id, dv.version_no DESC
), article_stats AS (
  SELECT max((published_at::timestamptz AT TIME ZONE 'Asia/Seoul')::date) AS latest_available_date,
         max(collected_at::timestamptz) AS last_collected_at
  FROM latest_versions
), selected_articles AS (
  SELECT lv.*,
         coalesce(article_topics.topics, '[]'::jsonb) AS topics
  FROM latest_versions lv
  LEFT JOIN LATERAL (
    SELECT jsonb_agg(
      jsonb_build_object(
        'key', topic_rows.code,
        'label', topic_rows.name_ko,
        'status', topic_rows.topic_status,
        'provenance', topic_rows.provenance
      )
      ORDER BY topic_rows.status_rank,
               topic_rows.confidence_rank DESC NULLS LAST,
               topic_rows.relevance_rank ASC NULLS LAST,
               topic_rows.support_count DESC,
               topic_rows.code
    ) AS topics
    FROM (
      SELECT DISTINCT ON (topic_candidates.code)
             topic_candidates.code,
             coalesce(managed_term.term_name_ko,topic_candidates.name_ko) AS name_ko,
             topic_candidates.topic_status,
             topic_candidates.provenance,
             topic_candidates.status_rank,
             topic_candidates.confidence_rank,
             topic_candidates.relevance_rank,
             topic_candidates.support_count
      FROM (
        SELECT CASE ec.code
                 WHEN 'INVESTMENT' THEN 'EQUITY_INVESTMENT'
                 WHEN 'NEW_SUPPLY' THEN 'SUPPLY'
                 WHEN 'CORPORATE_RELOCATION' THEN 'RELOCATION'
                 ELSE ec.code
               END AS code,
               ec.name_ko,
               'CONFIRMED'::text AS topic_status,
               'APPROVED_EVENT_MENTION'::text AS provenance,
               0 AS status_rank,
               max(em.confidence) AS confidence_rank,
               NULL::integer AS relevance_rank,
               count(*) AS support_count
        FROM market_intelligence.extraction_runs er
        JOIN market_intelligence.event_mentions em ON em.extraction_run_id = er.extraction_run_id
        JOIN market_intelligence.event_categories ec ON ec.event_category_id = em.event_category_id
        WHERE er.document_version_id = lv.document_version_id
          AND em.status_code = 'APPROVED'
          AND ec.is_active = 1
        GROUP BY ec.code, ec.name_ko

        UNION ALL

        SELECT CASE ec.code
                 WHEN 'INVESTMENT' THEN 'EQUITY_INVESTMENT'
                 WHEN 'NEW_SUPPLY' THEN 'SUPPLY'
                 WHEN 'CORPORATE_RELOCATION' THEN 'RELOCATION'
                 ELSE ec.code
               END AS code,
               ec.name_ko,
               'CANDIDATE'::text AS topic_status,
               'COLLECTION_QUERY'::text AS provenance,
               1 AS status_rank,
               NULL::real AS confidence_rank,
               min(rd.result_rank) AS relevance_rank,
               count(DISTINCT rd.run_id) AS support_count
        FROM market_intelligence.run_documents rd
        JOIN market_intelligence.collection_runs cr ON cr.run_id = rd.run_id
        JOIN market_intelligence.collection_job_categories cjc ON cjc.job_id = cr.job_id
        JOIN market_intelligence.event_categories ec ON ec.event_category_id = cjc.event_category_id
        WHERE rd.document_version_id = lv.document_version_id
          AND cr.status_code = 'COMPLETED'
          AND cjc.is_primary = 1
          AND ec.is_active = 1
        GROUP BY ec.code, ec.name_ko
      ) topic_candidates
      LEFT JOIN market_category_terms managed_term ON managed_term.term_code=topic_candidates.code
      ORDER BY topic_candidates.code, topic_candidates.status_rank,
               topic_candidates.confidence_rank DESC NULLS LAST,
               topic_candidates.relevance_rank ASC NULLS LAST,
               topic_candidates.support_count DESC
    ) topic_rows
  ) article_topics ON true
  WHERE (lv.published_at::timestamptz AT TIME ZONE 'Asia/Seoul')::date = $1::date
  ORDER BY lv.published_at::timestamptz DESC, lv.document_id
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
      'summary', summary_text,
      'summaryMode', CASE WHEN summary_method='MODEL' THEN 'MODEL' WHEN summary_text IS NOT NULL THEN 'BODY_EXTRACTIVE' ELSE 'NONE' END,
      'summaryGeneratedAt', summary_generated_at,
      'href', canonical_url,
      'topics', topics,
      'documentPurpose',CASE WHEN document_purpose_code IS NULL THEN NULL ELSE jsonb_build_object(
        'code',document_purpose_code,'label',document_purpose_label
      ) END,
      'evidenceGrade',CASE WHEN evidence_grade_code IS NULL THEN NULL ELSE jsonb_build_object(
        'code',evidence_grade_code,'label',evidence_grade_label
      ) END
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
