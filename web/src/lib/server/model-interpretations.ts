import { normalizeModelInterpretations, type ModelInterpretationsResponse } from "@/lib/model-interpretations-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

const SQL = `WITH models AS (
  SELECT model_registry_id,provider_code,model_name,model_version,embedding_version,
         prompt_version,prompt_hash,status_code
  FROM analytics_model_registry
  WHERE task_code='TOPIC_INTERPRETATION'
), selected AS (
  SELECT i.* FROM insight_interpretations i
  WHERE i.interpretation_status IN ('APPROVED','DRAFT','IN_REVIEW')
  ORDER BY CASE i.interpretation_status WHEN 'APPROVED' THEN 0 WHEN 'IN_REVIEW' THEN 1 ELSE 2 END,
           i.generated_at DESC
  LIMIT $1
), evidence AS (
  SELECT evidence_row.interpretation_id,json_group_array(json_object(
    'targetKind',evidence_row.target_kind,'targetId',evidence_row.target_id,
    'documentId',evidence_row.document_id,
    'documentVersionId',evidence_row.source_document_version_id,
    'title',evidence_row.title,'sourceName',evidence_row.source_name,
    'publishedAt',evidence_row.published_at,'canonicalUrl',evidence_row.canonical_url
  )) payload
  FROM (
    SELECT l.interpretation_id,se.target_kind,se.target_id,
      CASE WHEN se.target_kind='DOCUMENT' THEN se.target_id
           WHEN se.target_kind='DOCUMENT_VERSION' THEN dv.document_id ELSE NULL END AS document_id,
      se.source_document_version_id,coalesce(se.evidence_locator,dv.title,se.target_id) AS title,
      coalesce(cs.source_name,'') AS source_name,dv.published_at,sd.canonical_url
    FROM insight_interpretation_evidence l
    JOIN insight_signal_evidence se ON se.insight_signal_evidence_id=l.insight_signal_evidence_id
    LEFT JOIN document_versions dv ON dv.document_version_id=se.source_document_version_id
    LEFT JOIN source_documents sd ON sd.document_id=CASE
      WHEN se.target_kind='DOCUMENT' THEN se.target_id
      WHEN se.target_kind='DOCUMENT_VERSION' THEN dv.document_id
      ELSE NULL END
    LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
    ORDER BY l.interpretation_id,se.evidence_rank,se.insight_signal_evidence_id
  ) evidence_row
  GROUP BY evidence_row.interpretation_id
)
SELECT json_object(
  'generatedAt',strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  'models',json(COALESCE((SELECT json_group_array(json_object(
    'modelRegistryId',model.model_registry_id,'providerCode',model.provider_code,
    'modelName',model.model_name,'modelVersion',model.model_version,'embeddingVersion',model.embedding_version,
    'promptVersion',model.prompt_version,'promptHash',model.prompt_hash,'statusCode',model.status_code
  )) FROM (
    SELECT * FROM models model ORDER BY model.model_name,model.model_version,model.model_registry_id
  ) model),'[]')),
  'statusCounts',json(COALESCE((SELECT json_group_array(json_object('status',status.interpretation_status,'count',status.count)) FROM (
    SELECT interpretation_status,count(*) count
    FROM insight_interpretations GROUP BY interpretation_status ORDER BY interpretation_status
  ) status),'[]')),
  'interpretations',json(COALESCE((SELECT json_group_array(json_object(
    'interpretationId',interpretation.interpretation_id,'signalId',interpretation.insight_signal_id,
    'status',interpretation.interpretation_status,'headline',interpretation.headline,'narrative',interpretation.narrative_text,
    'generatedAt',interpretation.generated_at,
    'model',json_object('modelRegistryId',interpretation.model_registry_id,'providerCode',interpretation.provider_code,
      'modelName',interpretation.model_name,'modelVersion',interpretation.model_version,'embeddingVersion',interpretation.embedding_version,
      'promptVersion',interpretation.prompt_version,'promptHash',interpretation.prompt_hash,'statusCode',interpretation.status_code),
    'evidence',json(COALESCE(interpretation.evidence_payload,'[]'))
  )) FROM (
    SELECT s.*,m.provider_code,m.model_name,m.model_version,m.embedding_version,
      m.prompt_version,m.prompt_hash,m.status_code,e.payload AS evidence_payload
    FROM selected s JOIN models m ON m.model_registry_id=s.model_registry_id
    LEFT JOIN evidence e ON e.interpretation_id=s.interpretation_id
    ORDER BY s.generated_at DESC,s.interpretation_id
  ) interpretation),'[]'))
) payload`;

export async function getModelInterpretations(execute: SqlExecutor, limit = 20): Promise<ModelInterpretationsResponse> {
  const safe = Number.isFinite(limit) ? Math.max(1, Math.min(50, Math.trunc(limit))) : 20;
  const query = await execute(SQL, [safe]);
  return normalizeModelInterpretations(query.rows[0]?.payload);
}
