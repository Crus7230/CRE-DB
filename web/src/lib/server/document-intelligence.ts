import type { SqlExecutor } from "@/lib/server/market-search";
import type { RecordClassification } from "@/lib/search-contract";

export type DocumentDetail = {
  id: string;
  title: string;
  publisher: string | null;
  documentType: string;
  sourceUrl: string | null;
  author: string | null;
  publishedAt: string | null;
  collectedAt: string | null;
  rightsStatus: string | null;
  contentMode: "FULL_TEXT" | "SAFE_EXCERPT" | "SNIPPET" | "METADATA";
  summaryMode: "BODY_EXTRACTIVE" | "MODEL" | "EVENT_EXTRACTION" | "SOURCE_SNIPPET" | "NONE";
  summaryGeneratedAt: string | null;
  summaryPipeline: string | null;
  summary: string | null;
  eventExtraction: Record<string, unknown> | null;
  safeExcerpt: string | null;
  snippet: string | null;
  storedText: string | null;
  eventSignals: Array<{ category: string; categoryLabel: string; title: string | null; summary: string | null; stage: string | null; eventDate: string | null; confidence: number | null; status: string }>;
  keywords: Array<{ type: string; label: string; value: string; confidence: number | null }>;
  relatedEntities: Array<{
    kind: "EVENT" | "ASSET" | "ORGANIZATION" | "PROJECT" | "LP_MANDATE" | "SALE_PROCESS";
    id: string;
    title: string;
    relationBasis: "CANONICAL_EVENT" | "RESOLVED_MENTION" | "VERIFIED_CLAIM" | "SOURCE_CLAIM";
    relationRole: string;
    evidenceStatus: string;
    confidence: number | null;
  }>;
  classifications: RecordClassification[];
  transaction: null | {
    dealDate: string | null; dealAmount: string | null; buildingAr: string | null; plottageAr: string | null;
    buildingUse: string | null; buildingType: string | null; buildYear: string | null; floor: string | null;
    region: string | null; address: string | null; landUse: string | null; dealingType: string | null;
    buyerType: string | null; sellerType: string | null; shareType: string | null; cancelDate: string | null;
    duplicateOccurrence: number; screeningBand: "EXCLUDED" | "REVIEW" | "KEEP" | "UNKNOWN";
  };
};

const documentDetailSql = `
WITH runtime AS (
  SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now') AS now_utc
), latest AS (
  SELECT * FROM document_versions
  WHERE document_id=$1
  ORDER BY version_no DESC,document_version_id DESC
  LIMIT 1
), ranked_enrichments AS (
  SELECT de.*,
         row_number() OVER (ORDER BY CASE WHEN de.review_status='APPROVED' THEN 0 ELSE 1 END,
                                      de.generated_at DESC,de.document_enrichment_id DESC) AS item_rank
  FROM document_enrichments de
  JOIN latest dv ON dv.document_version_id=de.document_version_id
  WHERE de.enrichment_kind='CONTENT_SUMMARY'
    AND de.status_code='COMPLETED' AND de.review_status<>'REJECTED'
), selected_enrichment AS (
  SELECT * FROM ranked_enrichments WHERE item_rank=1
), event_rows AS (
  SELECT DISTINCT em.event_mention_id,ec.code,ec.name_ko,em.title_raw,em.summary_raw,
         em.stage_code_hint,em.event_date_start,em.confidence,em.status_code
  FROM extraction_runs er
  JOIN latest dv ON dv.document_version_id=er.document_version_id
  JOIN event_mentions em ON em.extraction_run_id=er.extraction_run_id
  LEFT JOIN event_categories ec ON ec.event_category_id=em.event_category_id
  WHERE em.status_code<>'REJECTED'
  ORDER BY em.confidence IS NULL,em.confidence DESC,em.event_mention_id
  LIMIT 20
), event_payload AS (
  SELECT json_group_array(json(item)) AS items
  FROM (
    SELECT json_object(
      'category',code,'categoryLabel',name_ko,'title',title_raw,'summary',summary_raw,
      'stage',stage_code_hint,'eventDate',event_date_start,
      'confidence',confidence,'status',status_code
    ) AS item
    FROM event_rows
    ORDER BY confidence IS NULL,confidence DESC,event_mention_id
  ) ordered_events
), keyword_candidates AS (
  SELECT m.mention_type,td.name_ko,
         coalesce(nullif(m.normalized_text,''),m.surface_text) AS value,m.confidence
  FROM extraction_runs er
  JOIN latest dv ON dv.document_version_id=er.document_version_id
  JOIN mentions m ON m.extraction_run_id=er.extraction_run_id
  LEFT JOIN mention_type_definitions td ON td.mention_type=m.mention_type
  WHERE m.review_status<>'REJECTED'

  UNION ALL

  SELECT 'EVENT_CATEGORY','업무 카테고리',ec.name_ko,em.confidence
  FROM extraction_runs er
  JOIN latest dv ON dv.document_version_id=er.document_version_id
  JOIN event_mentions em ON em.extraction_run_id=er.extraction_run_id
  JOIN event_categories ec ON ec.event_category_id=em.event_category_id
  WHERE em.status_code<>'REJECTED'

  UNION ALL

  SELECT 'EVENT_STAGE','절차 단계',em.stage_code_hint,em.confidence
  FROM extraction_runs er
  JOIN latest dv ON dv.document_version_id=er.document_version_id
  JOIN event_mentions em ON em.extraction_run_id=er.extraction_run_id
  WHERE em.status_code<>'REJECTED' AND nullif(em.stage_code_hint,'') IS NOT NULL
), ranked_keywords AS (
  SELECT keyword_candidates.*,
         row_number() OVER (
           PARTITION BY mention_type,value
           ORDER BY confidence IS NULL,confidence DESC
         ) AS item_rank
  FROM keyword_candidates
  WHERE length(trim(coalesce(value,'')))>1
), selected_keywords AS (
  SELECT * FROM ranked_keywords WHERE item_rank=1
  ORDER BY confidence IS NULL,confidence DESC,value,mention_type LIMIT 40
), keyword_payload AS (
  SELECT json_group_array(json(item)) AS items
  FROM (
    SELECT json_object(
      'type',mention_type,'label',coalesce(name_ko,mention_type),
      'value',value,'confidence',confidence
    ) AS item
    FROM selected_keywords
    ORDER BY confidence IS NULL,confidence DESC,value,mention_type
  ) ordered_keywords
), classification_payload AS (
  SELECT json_group_array(json(item)) AS items
  FROM (
    SELECT json_object(
      'schemeCode',s.scheme_code,'schemeLabel',s.scheme_name_ko,
      'termCode',t.term_code,'termLabel',t.term_name_ko,
      'parentCode',parent.term_code,'parentLabel',parent.term_name_ko,
      'isPrimary',json(CASE WHEN rc.is_primary=1 THEN 'true' ELSE 'false' END),
      'assignmentRole',rc.assignment_role,'evidenceStatus',rc.evidence_status,
      'reviewStatus',rc.review_status,'confidence',rc.confidence
    ) AS item
    FROM record_classifications rc
    JOIN source_documents sd ON sd.document_id=rc.target_id
    JOIN classification_schemes s ON s.classification_scheme_id=rc.classification_scheme_id
    JOIN classification_terms t ON t.classification_scheme_id=rc.classification_scheme_id
      AND t.classification_term_id=rc.classification_term_id
    LEFT JOIN classification_terms parent ON parent.classification_scheme_id=t.classification_scheme_id
      AND parent.classification_term_id=t.parent_term_id
    CROSS JOIN runtime rt
    WHERE rc.target_kind='DOCUMENT' AND sd.document_id=$1
      AND rc.review_status NOT IN ('REJECTED','SUPERSEDED')
      AND (rc.valid_from IS NULL OR rc.valid_from<=rt.now_utc)
      AND (rc.valid_to IS NULL OR rc.valid_to>rt.now_utc)
      AND s.governance_status='ACTIVE' AND t.governance_status='ACTIVE'
      AND (s.valid_from IS NULL OR s.valid_from<=rt.now_utc)
      AND (s.valid_to IS NULL OR s.valid_to>rt.now_utc)
      AND (t.valid_from IS NULL OR t.valid_from<=rt.now_utc)
      AND (t.valid_to IS NULL OR t.valid_to>rt.now_utc)
    ORDER BY s.scheme_code,rc.is_primary DESC,t.sort_order,t.term_code,rc.record_classification_id
  ) ordered_classifications
), relation_candidates AS (
  SELECT r.entity_kind,r.entity_id,
         coalesce(e.canonical_title,a.canonical_name,o.canonical_name,p.canonical_name,
                  lm.mandate_name,sp.process_code,r.entity_id) AS entity_title,
         r.relation_basis,r.relation_role,r.evidence_status,r.confidence,
         row_number() OVER (
           PARTITION BY r.entity_kind,r.entity_id
           ORDER BY CASE r.relation_basis WHEN 'CANONICAL_EVENT' THEN 1
                    WHEN 'RESOLVED_MENTION' THEN 2 WHEN 'VERIFIED_CLAIM' THEN 3 ELSE 4 END,
                    r.confidence IS NULL,r.confidence DESC,r.relation_role,r.evidence_status
         ) AS relation_rank
  FROM v_document_entity_relations r
  JOIN latest dv ON dv.document_version_id=r.document_version_id
  LEFT JOIN events e ON r.entity_kind='EVENT' AND e.event_id=r.entity_id
  LEFT JOIN assets a ON r.entity_kind='ASSET' AND a.asset_id=r.entity_id
  LEFT JOIN organizations o ON r.entity_kind='ORGANIZATION' AND o.organization_id=r.entity_id
  LEFT JOIN projects p ON r.entity_kind='PROJECT' AND p.project_id=r.entity_id
  LEFT JOIN lp_mandates lm ON r.entity_kind='LP_MANDATE' AND lm.mandate_id=r.entity_id
  LEFT JOIN sale_processes sp ON r.entity_kind='SALE_PROCESS' AND sp.sale_process_id=r.entity_id
), selected_relations AS (
  SELECT * FROM relation_candidates WHERE relation_rank=1
  ORDER BY entity_kind,entity_title,entity_id LIMIT 100
), relation_payload AS (
  SELECT json_group_array(json(item)) AS items
  FROM (
    SELECT json_object(
      'kind',entity_kind,'id',entity_id,'title',entity_title,
      'relationBasis',relation_basis,'relationRole',relation_role,
      'evidenceStatus',evidence_status,'confidence',confidence
    ) AS item
    FROM selected_relations
    ORDER BY entity_kind,entity_title,entity_id
  ) ordered_relations
)
SELECT json_object(
  'id',sd.document_id,'title',dv.title,'publisher',sd.publisher_name,
  'documentType',sd.document_type,
  'sourceUrl',CASE WHEN sd.document_type='API_RECORD'
    THEN json_extract(dv.metadata_json,'$.source_endpoint')
    ELSE coalesce(en.resolved_url,sd.canonical_url) END,
  'author',dv.author_name,'publishedAt',dv.published_at,'collectedAt',dv.collected_at,
  'rightsStatus',dv.rights_status,
  'contentMode',CASE WHEN length(trim(coalesce(dv.stored_text,'')))>0 THEN 'FULL_TEXT'
    WHEN en.safe_excerpt IS NOT NULL THEN 'SAFE_EXCERPT'
    WHEN length(trim(coalesce(dv.snippet_text,'')))>0 THEN 'SNIPPET' ELSE 'METADATA' END,
  'summaryMode',CASE
    WHEN en.summary_text IS NOT NULL AND en.summary_method='MODEL' THEN 'MODEL'
    WHEN en.summary_text IS NOT NULL THEN 'BODY_EXTRACTIVE'
    WHEN (SELECT nullif(summary_raw,'') FROM event_rows
          WHERE nullif(summary_raw,'') IS NOT NULL
          ORDER BY confidence IS NULL,confidence DESC LIMIT 1) IS NOT NULL THEN 'EVENT_EXTRACTION'
    WHEN length(trim(coalesce(dv.snippet_text,'')))>0
      AND lower(trim(dv.snippet_text))<>lower(trim(coalesce(dv.title,''))) THEN 'SOURCE_SNIPPET'
    ELSE 'NONE' END,
  'summaryGeneratedAt',en.generated_at,'summaryPipeline',en.pipeline_version,
  'summary',coalesce(en.summary_text,
    (SELECT nullif(summary_raw,'') FROM event_rows WHERE nullif(summary_raw,'') IS NOT NULL
     ORDER BY confidence IS NULL,confidence DESC LIMIT 1),
    CASE WHEN lower(trim(coalesce(dv.snippet_text,'')))<>lower(trim(coalesce(dv.title,'')))
      THEN nullif(dv.snippet_text,'') END),
  'safeExcerpt',en.safe_excerpt,'snippet',nullif(dv.snippet_text,''),
  'storedText',nullif(substr(dv.stored_text,1,12000),''),
  'eventSignals',json(COALESCE(ev.items,'[]')),
  'keywords',json(COALESCE(kw.items,'[]')),
  'relatedEntities',json(COALESCE(rel.items,'[]')),
  'classifications',json(COALESCE(cls.items,'[]')),
  'transaction',CASE WHEN sd.document_type='API_RECORD' THEN json_object(
    'dealDate',json_extract(dv.metadata_json,'$.deal_date'),
    'dealAmount',json_extract(dv.metadata_json,'$.api_record.dealAmount'),
    'buildingAr',json_extract(dv.metadata_json,'$.api_record.buildingAr'),
    'plottageAr',json_extract(dv.metadata_json,'$.api_record.plottageAr'),
    'buildingUse',json_extract(dv.metadata_json,'$.api_record.buildingUse'),
    'buildingType',json_extract(dv.metadata_json,'$.api_record.buildingType'),
    'buildYear',json_extract(dv.metadata_json,'$.api_record.buildYear'),
    'floor',json_extract(dv.metadata_json,'$.api_record.floor'),
    'region',concat_ws(' ',json_extract(dv.metadata_json,'$.api_record.sggNm'),json_extract(dv.metadata_json,'$.api_record.umdNm')),
    'address',concat_ws(' ',json_extract(dv.metadata_json,'$.api_record.sggNm'),json_extract(dv.metadata_json,'$.api_record.umdNm'),json_extract(dv.metadata_json,'$.api_record.jibun')),
    'landUse',json_extract(dv.metadata_json,'$.api_record.landUse'),
    'dealingType',json_extract(dv.metadata_json,'$.api_record.dealingGbn'),
    'buyerType',json_extract(dv.metadata_json,'$.api_record.buyerGbn'),
    'sellerType',json_extract(dv.metadata_json,'$.api_record.slerGbn'),
    'shareType',json_extract(dv.metadata_json,'$.api_record.shareDealingType'),
    'cancelDate',json_extract(dv.metadata_json,'$.api_record.cdealDay'),
    'duplicateOccurrence',CAST(coalesce(json_extract(dv.metadata_json,'$.duplicate_occurrence'),1) AS INTEGER),
    'screeningBand',CASE
      WHEN nullif(json_extract(dv.metadata_json,'$.api_record.buildingAr'),'') IS NULL THEN 'UNKNOWN'
      WHEN CAST(json_extract(dv.metadata_json,'$.api_record.buildingAr') AS REAL)<=1000 THEN 'EXCLUDED'
      WHEN CAST(json_extract(dv.metadata_json,'$.api_record.buildingAr') AS REAL)<=3300 THEN 'REVIEW'
      ELSE 'KEEP' END
  ) END
) AS payload
FROM source_documents sd
JOIN latest dv ON dv.document_id=sd.document_id
LEFT JOIN selected_enrichment en ON true
LEFT JOIN event_payload ev ON true
LEFT JOIN keyword_payload kw ON true
LEFT JOIN relation_payload rel ON true
LEFT JOIN classification_payload cls ON true
WHERE sd.document_id=$1`;

export const servingDocumentDetailSql = `
SELECT payload_json AS payload
FROM serving_daily_article_details
WHERE document_id=$1
LIMIT 1`;

export async function getDocumentDetail(
  execute: SqlExecutor,
  id: string,
  options: { allowArchiveFallback?: boolean } = {},
): Promise<DocumentDetail | null> {
  // Production publication guarantees this compact projection, while the raw
  // archive intentionally remains local. Reading compact first also prevents a
  // stale raw version from winning over a newly published serving payload.
  const serving = await execute(servingDocumentDetailSql, [id]);
  let raw = serving.rows[0]?.payload;
  if (raw === undefined && options.allowArchiveFallback === true) {
    raw = (await execute(documentDetailSql, [id])).rows[0]?.payload;
  }
  const detail = (typeof raw === "string" ? JSON.parse(raw) : raw) as Omit<DocumentDetail, "eventExtraction"> | undefined;
  if (!detail) return null;

  const normalizedSummary = normalizeObjectLikeSummary(detail.summary);
  return {
    ...detail,
    summary: normalizedSummary.summary,
    eventExtraction: detail.summaryMode === "EVENT_EXTRACTION" ? normalizedSummary.object : null,
    eventSignals: detail.eventSignals.map((signal) => ({
      ...signal,
      summary: normalizeObjectLikeSummary(signal.summary).summary,
    })),
  };
}

function normalizeObjectLikeSummary(value: string | null): {
  summary: string | null;
  object: Record<string, unknown> | null;
} {
  const trimmed = value?.trim();
  if (!trimmed?.startsWith("{")) return { summary: value, object: null };

  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { summary: null, object: parsed as Record<string, unknown> };
    }
  } catch {
    // Object-looking extraction text must never leak into the human-readable summary.
  }
  return { summary: null, object: null };
}
