import { normalizeKeywordAnalytics, type KeywordAnalyticsResponse } from "@/lib/keyword-analytics-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

const SQL = `WITH latest_refresh AS (
  SELECT * FROM analytics_refresh_runs
  WHERE pipeline_code='KEYWORD_DAILY' AND status_code='COMPLETED'
  ORDER BY completed_at DESC,analytics_refresh_run_id DESC LIMIT 1
), latest_day AS (
  SELECT max(o.bucket_date) AS bucket_date
  FROM keyword_observations_daily o JOIN latest_refresh r ON r.algorithm_version=o.algorithm_version
), selected AS MATERIALIZED (
  SELECT o.*,kd.display_term,kd.term_kind,kd.is_collection_bias
  FROM keyword_observations_daily o
  JOIN keyword_dictionary kd ON kd.keyword_id=o.keyword_id
  JOIN latest_refresh r ON r.algorithm_version=o.algorithm_version
  JOIN latest_day d ON d.bucket_date=o.bucket_date
  WHERE kd.status_code='ACTIVE'
  ORDER BY CASE WHEN ?2<>0 AND kd.is_collection_bias=0 AND o.document_frequency>=2 AND o.burst_score>0 THEN 0
                WHEN ?2<>0 THEN 1 ELSE 0 END,
           kd.is_collection_bias ASC,o.burst_score DESC,o.document_frequency DESC,kd.display_term
  LIMIT ?1
), trend_rows AS (
  SELECT s.keyword_id,x.bucket_date,x.document_frequency
  FROM selected s
  JOIN keyword_observations_daily x
    ON x.keyword_id=s.keyword_id AND x.algorithm_version=s.algorithm_version
   AND x.bucket_date>=date(s.bucket_date,'-29 days') AND x.bucket_date<=s.bucket_date
), trend_payload AS (
  SELECT keyword_id,json_group_array(json_object(
    'date',bucket_date,'documentFrequency',document_frequency
  )) AS payload
  FROM (SELECT * FROM trend_rows ORDER BY keyword_id,bucket_date)
  GROUP BY keyword_id
), cooccurrence_sums AS (
  SELECT s.keyword_id,other.display_term,sum(c.document_frequency) AS document_frequency
  FROM selected s
  JOIN keyword_cooccurrences_daily c
    ON (c.keyword_left_id=s.keyword_id OR c.keyword_right_id=s.keyword_id)
   AND c.algorithm_version=s.algorithm_version
   AND c.bucket_date>=date(s.bucket_date,'-29 days')
  JOIN keyword_dictionary other ON other.keyword_id=CASE
    WHEN c.keyword_left_id=s.keyword_id THEN c.keyword_right_id ELSE c.keyword_left_id END
  GROUP BY s.keyword_id,other.display_term
), cooccurrence_ranked AS (
  SELECT *,row_number() OVER (
    PARTITION BY keyword_id ORDER BY document_frequency DESC,display_term
  ) AS rank_no
  FROM cooccurrence_sums
), cooccurrence_payload AS (
  SELECT keyword_id,json_group_array(json_object(
    'term',display_term,'documentFrequency',document_frequency
  )) AS payload
  FROM (SELECT * FROM cooccurrence_ranked WHERE rank_no<=5 ORDER BY keyword_id,rank_no)
  GROUP BY keyword_id
), keyword_payload AS (
  SELECT s.keyword_id,s.is_collection_bias,s.burst_score,json_object(
    'keywordId',s.keyword_id,'term',s.display_term,'termKind',s.term_kind,
    'isCollectionBias',json(CASE WHEN s.is_collection_bias=1 THEN 'true' ELSE 'false' END),
    'documentFrequency',s.document_frequency,
    'baselineDocumentFrequency',s.baseline_document_frequency,'burstScore',s.burst_score,
    'trend',json(COALESCE(t.payload,'[]')),
    'cooccurrences',json(COALESCE(c.payload,'[]'))
  ) AS item
  FROM selected s
  LEFT JOIN trend_payload t ON t.keyword_id=s.keyword_id
  LEFT JOIN cooccurrence_payload c ON c.keyword_id=s.keyword_id
)
SELECT json_object(
  'generatedAt',strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  'algorithmVersion',COALESCE(r.algorithm_version,'NOT_REFRESHED'),
  'computedAt',COALESCE(r.completed_at,strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  'windowStart',COALESCE(r.window_start,''),'windowEnd',COALESCE(r.window_end,''),
  'latestDate',d.bucket_date,
  'summary',json_object(
    'keywordCount',COALESCE((SELECT count(*) FROM keyword_dictionary k WHERE k.algorithm_version=r.algorithm_version),0),
    'observationCount',COALESCE((SELECT count(*) FROM keyword_observations_daily o WHERE o.algorithm_version=r.algorithm_version),0),
    'qualifiedKeywordCount',COALESCE((SELECT count(*) FROM keyword_observations_daily o
      JOIN keyword_dictionary k ON k.keyword_id=o.keyword_id
      WHERE o.algorithm_version=r.algorithm_version AND o.bucket_date=d.bucket_date AND k.status_code='ACTIVE'
        AND k.is_collection_bias=0 AND o.document_frequency>=2 AND o.burst_score>0),0),
    'excludedMissingPublicationCount',CAST(COALESCE(json_extract(r.metadata_json,'$.documents_excluded_missing_publication'),0) AS INTEGER)),
  'keywords',json(COALESCE((SELECT json_group_array(json(keyword.item)) FROM (
    SELECT * FROM keyword_payload keyword
    ORDER BY keyword.is_collection_bias,keyword.burst_score DESC,keyword.keyword_id
  ) keyword),'[]'))
) AS payload
FROM (SELECT 1) anchor LEFT JOIN latest_refresh r ON true LEFT JOIN latest_day d ON true`;

export async function getKeywordAnalytics(execute: SqlExecutor, limit = 30, briefingPriority = false): Promise<KeywordAnalyticsResponse> {
  const safeLimit = Number.isFinite(limit) ? Math.max(1, Math.min(50, Math.trunc(limit))) : 30;
  const query = await execute(SQL, [safeLimit, briefingPriority]);
  return normalizeKeywordAnalytics(query.rows[0]?.payload);
}
