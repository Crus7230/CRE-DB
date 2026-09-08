import { isOperationsTimelineWindowDays, normalizeOperationsTimeline, type OperationsTimelineResponse } from "@/lib/operations-timeline-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

const TIMELINE_SQL = `
WITH RECURSIVE input AS (
  SELECT CAST(? AS INTEGER) AS window_days
), bounds AS (
  SELECT window_days,
         date('now', printf('-%d days', window_days - 1)) AS start_date,
         date('now') AS end_date
  FROM input
), archive_rows AS MATERIALIZED (
  SELECT asi.* FROM archived_serving_index asi
  JOIN archive_snapshots ars ON ars.archive_snapshot_id=asi.archive_snapshot_id
   AND ars.is_current=1 AND ars.integrity_status='VALIDATED'
), latest_document_versions_ranked AS MATERIALIZED (
  SELECT document_id,document_version_id,published_at,collected_at,
         row_number() OVER (
           PARTITION BY document_id
           ORDER BY version_no DESC,document_version_id DESC
         ) AS version_rank
  FROM document_versions
), latest_document_versions AS MATERIALIZED (
  SELECT document_id,document_version_id,published_at,collected_at
  FROM latest_document_versions_ranked
  WHERE version_rank=1
), serving_documents AS MATERIALIZED (
  SELECT sd.document_id,ldv.published_at,ldv.collected_at
  FROM source_documents sd
  LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
  LEFT JOIN latest_document_versions ldv ON ldv.document_id=sd.document_id
  LEFT JOIN document_scope_assessments dsa
    ON dsa.document_scope_assessment_id=(
      SELECT candidate.document_scope_assessment_id
      FROM document_scope_assessments candidate
      WHERE candidate.document_version_id=ldv.document_version_id
        AND candidate.scope_code='CRE'
        AND candidate.classifier_version IN (
          'DART_CRE_SCOPE_RULE_V1','NEWS_CRE_SCOPE_RULE_V3','NEWS_CRE_SCOPE_RULE_V2','NEWS_CRE_SCOPE_RULE_V1','MOLIT_SCOPE_TIERED_V2'
        )
      ORDER BY CASE candidate.classifier_version
                 WHEN 'NEWS_CRE_SCOPE_RULE_V3' THEN 0
                 WHEN 'NEWS_CRE_SCOPE_RULE_V2' THEN 1
                 ELSE 2
               END,
               candidate.assessed_at DESC,candidate.document_scope_assessment_id DESC
      LIMIT 1
    )
  WHERE cs.source_code IS NULL OR cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION') OR dsa.status_code='CRE_CONFIRMED'
), publication_daily AS (
  SELECT substr(sd.published_at,1,10) AS day,count(DISTINCT document_id) AS count
  FROM serving_documents sd,bounds b
  WHERE sd.published_at IS NOT NULL AND substr(sd.published_at,1,10) BETWEEN b.start_date AND b.end_date
  GROUP BY substr(sd.published_at,1,10)
), ingestion_daily AS (
  SELECT substr(sd.collected_at,1,10) AS day,count(DISTINCT document_id) AS count
  FROM serving_documents sd,bounds b
  WHERE sd.collected_at IS NOT NULL AND substr(sd.collected_at,1,10) BETWEEN b.start_date AND b.end_date
  GROUP BY substr(sd.collected_at,1,10)
), serving_events AS (
  SELECT e.event_id,e.event_date_start FROM events e
  UNION
  SELECT ar.record_id,ar.event_date_start FROM archive_rows ar
  WHERE ar.record_kind='EVENT' AND NOT EXISTS (SELECT 1 FROM events e WHERE e.event_id=ar.record_id)
), event_daily AS (
  SELECT substr(e.event_date_start,1,10) AS day,count(DISTINCT event_id) AS count
  FROM serving_events e,bounds b
  WHERE e.event_date_start IS NOT NULL AND substr(e.event_date_start,1,10) BETWEEN b.start_date AND b.end_date
  GROUP BY substr(e.event_date_start,1,10)
), calendar(day,end_date) AS (
  SELECT start_date,end_date FROM bounds
  UNION ALL
  SELECT date(day,'+1 day'),end_date
  FROM calendar
  WHERE day<end_date
)
SELECT json_object(
  'generatedAt',strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  'windowDays',(SELECT window_days FROM bounds),
  'publicationKnownCount',(SELECT count(DISTINCT document_id) FROM serving_documents WHERE published_at IS NOT NULL),
  'publicationUnknownCount',(SELECT count(DISTINCT document_id) FROM serving_documents WHERE published_at IS NULL),
  'archivedDocumentExcludedCount',(SELECT count(*) FROM archive_rows ar WHERE ar.record_kind='DOCUMENT' AND NOT EXISTS (SELECT 1 FROM source_documents sd WHERE sd.document_id=ar.record_id)),
  'series',json(coalesce((
    SELECT json_group_array(json_object(
      'date',c.day,
      'publicationCount',coalesce(p.count,0),
      'eventCount',coalesce(e.count,0),
      'ingestionCount',coalesce(i.count,0)
    ))
    FROM (SELECT day FROM calendar ORDER BY day) c
    LEFT JOIN publication_daily p ON p.day=c.day
    LEFT JOIN event_daily e ON e.day=c.day
    LEFT JOIN ingestion_daily i ON i.day=c.day
  ),'[]'))
) AS payload`;

export async function getOperationsTimeline(execute: SqlExecutor, requestedDays = 90): Promise<OperationsTimelineResponse> {
  if (!isOperationsTimelineWindowDays(requestedDays)) throw new RangeError("Unsupported operations timeline window");
  const query = await execute(TIMELINE_SQL, [requestedDays]);
  return normalizeOperationsTimeline(query.rows[0]?.payload);
}
