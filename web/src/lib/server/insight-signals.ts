import { normalizeInsightSignals, type InsightSignalsResponse } from "@/lib/insight-signals-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

const SQL = `WITH selected AS (
  SELECT s.* FROM insight_signals s
  WHERE s.review_status NOT IN ('REJECTED','SUPERSEDED')
    AND ($2=0 OR s.review_status IN ('UNREVIEWED','PENDING'))
  ORDER BY CASE WHEN $2<>0 THEN CASE s.severity_code WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END ELSE 0 END,
           CASE WHEN $2=0 THEN CASE s.review_status WHEN 'APPROVED' THEN 0 WHEN 'PENDING' THEN 1 ELSE 2 END ELSE 0 END,
           s.signal_date DESC,s.confidence_score DESC,s.insight_signal_id
  LIMIT $1
), payloads AS (
  SELECT s.insight_signal_id,s.review_status,s.signal_date,s.confidence_score,json_object(
    'signalId',s.insight_signal_id,'signalType',s.signal_type,'signalDate',s.signal_date,
    'title',s.title,'summary',s.summary_text,'reviewStatus',s.review_status,'severity',s.severity_code,
    'scores',json_object('strength',s.strength_score,'evidence',s.evidence_score,
      'sourceDiversity',s.source_diversity_score,'confidence',s.confidence_score),
    'syndicationDedupeStatus',COALESCE(json_extract(s.metadata_json,'$.syndication_dedupe_status'),'UNKNOWN'),
    'evidence',json(COALESCE((SELECT json_group_array(json_object(
      'targetKind',evidence.target_kind,'targetId',evidence.target_id,
      'documentId',evidence.document_id,'documentVersionId',evidence.source_document_version_id,
      'title',evidence.title,'sourceName',evidence.source_name,
      'publishedAt',evidence.published_at,'canonicalUrl',evidence.canonical_url,
      'role',evidence.evidence_role,'rank',evidence.evidence_rank
    )) FROM (
      SELECT e.target_kind,e.target_id,
        CASE WHEN e.target_kind='DOCUMENT' THEN e.target_id WHEN e.target_kind='DOCUMENT_VERSION' THEN dv.document_id ELSE NULL END AS document_id,
        e.source_document_version_id,COALESCE(dv.title,e.evidence_locator,'제목 미상') AS title,
        COALESCE(cs.source_name,sd.publisher_name,'출처 미상') AS source_name,
        dv.published_at,sd.canonical_url,e.evidence_role,e.evidence_rank
      FROM insight_signal_evidence e
      LEFT JOIN document_versions dv ON dv.document_version_id=e.source_document_version_id
      LEFT JOIN source_documents sd ON sd.document_id=CASE
        WHEN e.target_kind='DOCUMENT' THEN e.target_id
        WHEN e.target_kind='DOCUMENT_VERSION' THEN dv.document_id
        ELSE NULL END
      LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
      WHERE e.insight_signal_id=s.insight_signal_id
      ORDER BY e.evidence_rank,e.insight_signal_evidence_id
    ) evidence),'[]'))
  ) item FROM selected s
), statuses AS (
  SELECT review_status,count(*) count FROM insight_signals GROUP BY review_status
)
SELECT json_object(
  'generatedAt',(SELECT max(computed_at) FROM insight_signals),
  'algorithmVersion',COALESCE((SELECT algorithm_version FROM insight_signals ORDER BY computed_at DESC,insight_signal_id DESC LIMIT 1),'NOT_REFRESHED'),
  'statusCounts',json(COALESCE((SELECT json_group_array(json_object('status',status.review_status,'count',status.count)) FROM (
    SELECT * FROM statuses status ORDER BY status.review_status
  ) status),'[]')),
  'signals',json(COALESCE((SELECT json_group_array(json(signal.item)) FROM (
    SELECT * FROM payloads signal
    ORDER BY CASE signal.review_status WHEN 'APPROVED' THEN 0 WHEN 'PENDING' THEN 1 ELSE 2 END,
      signal.signal_date DESC,signal.confidence_score DESC,signal.insight_signal_id
  ) signal),'[]'))
) payload`;

export async function getInsightSignals(execute: SqlExecutor, limit = 20, reviewableOnly = false): Promise<InsightSignalsResponse> {
  const safeLimit = Number.isFinite(limit) ? Math.max(1, Math.min(50, Math.trunc(limit))) : 20;
  const query = await execute(SQL, [safeLimit, reviewableOnly]);
  return normalizeInsightSignals(query.rows[0]?.payload);
}
