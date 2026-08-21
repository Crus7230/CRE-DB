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
  SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS now_utc
), latest AS (
  SELECT * FROM market_intelligence.document_versions
  WHERE document_id=$1
  ORDER BY version_no DESC, document_version_id DESC
  LIMIT 1
)
SELECT jsonb_build_object(
  'id',sd.document_id,
  'title',dv.title,
  'publisher',sd.publisher_name,
  'documentType',sd.document_type,
  'sourceUrl',CASE WHEN sd.document_type='API_RECORD' THEN dv.metadata_json::jsonb->>'source_endpoint' ELSE coalesce(en.resolved_url,sd.canonical_url) END,
  'author',dv.author_name,
  'publishedAt',dv.published_at,
  'collectedAt',dv.collected_at,
  'rightsStatus',dv.rights_status,
  'contentMode',CASE WHEN length(trim(coalesce(dv.stored_text,'')))>0 THEN 'FULL_TEXT' WHEN en.safe_excerpt IS NOT NULL THEN 'SAFE_EXCERPT' WHEN length(trim(coalesce(dv.snippet_text,'')))>0 THEN 'SNIPPET' ELSE 'METADATA' END,
  'summaryMode',CASE
    WHEN en.summary_text IS NOT NULL AND en.summary_method='MODEL' THEN 'MODEL'
    WHEN en.summary_text IS NOT NULL THEN 'BODY_EXTRACTIVE'
    WHEN ev.primary_summary IS NOT NULL THEN 'EVENT_EXTRACTION'
    WHEN length(trim(coalesce(dv.snippet_text,'')))>0
      AND regexp_replace(lower(dv.snippet_text),'[^[:alnum:]가-힣]','','g') <> regexp_replace(lower(coalesce(dv.title,'')),'[^[:alnum:]가-힣]','','g') THEN 'SOURCE_SNIPPET'
    ELSE 'NONE' END,
  'summaryGeneratedAt',en.generated_at,
  'summaryPipeline',en.pipeline_version,
  'summary',coalesce(en.summary_text,ev.primary_summary,
    CASE WHEN regexp_replace(lower(coalesce(dv.snippet_text,'')),'[^[:alnum:]가-힣]','','g') <> regexp_replace(lower(coalesce(dv.title,'')),'[^[:alnum:]가-힣]','','g') THEN nullif(dv.snippet_text,'') END),
  'safeExcerpt',en.safe_excerpt,
  'snippet',nullif(dv.snippet_text,''),
  'storedText',nullif(left(dv.stored_text,12000),''),
  'eventSignals',coalesce(ev.items,'[]'::jsonb),
  'keywords',coalesce(kw.items,'[]'::jsonb),
  'relatedEntities',coalesce(rel.items,'[]'::jsonb),
  'classifications',coalesce(cls.items,'[]'::jsonb),
  'transaction',CASE WHEN sd.document_type='API_RECORD' THEN jsonb_build_object(
    'dealDate',dv.metadata_json::jsonb->>'deal_date',
    'dealAmount',dv.metadata_json::jsonb->'api_record'->>'dealAmount',
    'buildingAr',dv.metadata_json::jsonb->'api_record'->>'buildingAr',
    'plottageAr',dv.metadata_json::jsonb->'api_record'->>'plottageAr',
    'buildingUse',dv.metadata_json::jsonb->'api_record'->>'buildingUse',
    'buildingType',dv.metadata_json::jsonb->'api_record'->>'buildingType',
    'buildYear',dv.metadata_json::jsonb->'api_record'->>'buildYear',
    'floor',dv.metadata_json::jsonb->'api_record'->>'floor',
    'region',concat_ws(' ',dv.metadata_json::jsonb->'api_record'->>'sggNm',dv.metadata_json::jsonb->'api_record'->>'umdNm'),
    'address',concat_ws(' ',dv.metadata_json::jsonb->'api_record'->>'sggNm',dv.metadata_json::jsonb->'api_record'->>'umdNm',dv.metadata_json::jsonb->'api_record'->>'jibun'),
    'landUse',dv.metadata_json::jsonb->'api_record'->>'landUse',
    'dealingType',dv.metadata_json::jsonb->'api_record'->>'dealingGbn',
    'buyerType',dv.metadata_json::jsonb->'api_record'->>'buyerGbn',
    'sellerType',dv.metadata_json::jsonb->'api_record'->>'slerGbn',
    'shareType',dv.metadata_json::jsonb->'api_record'->>'shareDealingType',
    'cancelDate',dv.metadata_json::jsonb->'api_record'->>'cdealDay',
    'duplicateOccurrence',coalesce((dv.metadata_json::jsonb->>'duplicate_occurrence')::int,1),
    'screeningBand',CASE
      WHEN nullif(dv.metadata_json::jsonb->'api_record'->>'buildingAr','') IS NULL THEN 'UNKNOWN'
      WHEN (dv.metadata_json::jsonb->'api_record'->>'buildingAr')::numeric <= 1000 THEN 'EXCLUDED'
      WHEN (dv.metadata_json::jsonb->'api_record'->>'buildingAr')::numeric <= 3300 THEN 'REVIEW'
      ELSE 'KEEP' END
  ) END
) AS payload
FROM market_intelligence.source_documents sd
JOIN latest dv ON dv.document_id=sd.document_id
LEFT JOIN LATERAL (
  SELECT de.summary_text,de.safe_excerpt,de.resolved_url,de.summary_method,
    de.generated_at,de.pipeline_version
  FROM market_intelligence.document_enrichments de
  WHERE de.document_version_id=dv.document_version_id
    AND de.enrichment_kind='CONTENT_SUMMARY'
    AND de.status_code='COMPLETED'
    AND de.review_status<>'REJECTED'
  ORDER BY CASE WHEN de.review_status='APPROVED' THEN 0 ELSE 1 END,
    de.generated_at DESC,de.document_enrichment_id DESC
  LIMIT 1
) en ON true
LEFT JOIN LATERAL (
  SELECT
    (array_agg(nullif(x.summary_raw,'') ORDER BY x.confidence DESC NULLS LAST) FILTER (WHERE nullif(x.summary_raw,'') IS NOT NULL))[1] AS primary_summary,
    jsonb_agg(jsonb_build_object(
      'category',x.code,'categoryLabel',x.name_ko,'title',x.title_raw,
      'summary',x.summary_raw,'stage',x.stage_code_hint,'eventDate',x.event_date_start,
      'confidence',x.confidence,'status',x.status_code
    ) ORDER BY x.confidence DESC NULLS LAST) AS items
  FROM (
    SELECT DISTINCT em.event_mention_id,ec.code,ec.name_ko,em.title_raw,em.summary_raw,
      em.stage_code_hint,em.event_date_start,em.confidence,em.status_code
    FROM market_intelligence.extraction_runs er
    JOIN market_intelligence.event_mentions em ON em.extraction_run_id=er.extraction_run_id
    LEFT JOIN market_intelligence.event_categories ec ON ec.event_category_id=em.event_category_id
    WHERE er.document_version_id=dv.document_version_id AND em.status_code<>'REJECTED'
    ORDER BY em.confidence DESC NULLS LAST
    LIMIT 20
  ) x
) ev ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object(
    'type',x.mention_type,'label',coalesce(x.name_ko,x.mention_type),
    'value',x.value,'confidence',x.confidence
  ) ORDER BY x.confidence DESC NULLS LAST,x.value) AS items
  FROM (
    SELECT DISTINCT ON (raw.mention_type,raw.value)
      raw.mention_type,raw.name_ko,raw.value,raw.confidence
    FROM (
      SELECT m.mention_type,td.name_ko,
        coalesce(nullif(m.normalized_text,''),m.surface_text) AS value,m.confidence
      FROM market_intelligence.extraction_runs er
      JOIN market_intelligence.mentions m ON m.extraction_run_id=er.extraction_run_id
      LEFT JOIN market_intelligence.mention_type_definitions td ON td.mention_type=m.mention_type
      WHERE er.document_version_id=dv.document_version_id AND m.review_status<>'REJECTED'
      UNION ALL
      SELECT 'EVENT_CATEGORY','업무 카테고리',ec.name_ko,em.confidence
      FROM market_intelligence.extraction_runs er
      JOIN market_intelligence.event_mentions em ON em.extraction_run_id=er.extraction_run_id
      JOIN market_intelligence.event_categories ec ON ec.event_category_id=em.event_category_id
      WHERE er.document_version_id=dv.document_version_id AND em.status_code<>'REJECTED'
      UNION ALL
      SELECT 'EVENT_STAGE','절차 단계',em.stage_code_hint,em.confidence
      FROM market_intelligence.extraction_runs er
      JOIN market_intelligence.event_mentions em ON em.extraction_run_id=er.extraction_run_id
      WHERE er.document_version_id=dv.document_version_id AND em.status_code<>'REJECTED'
        AND nullif(em.stage_code_hint,'') IS NOT NULL
    ) raw
    WHERE length(trim(coalesce(raw.value,'')))>1
    ORDER BY raw.mention_type,raw.value,raw.confidence DESC NULLS LAST
    LIMIT 40
  ) x
) kw ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object(
    'schemeCode',s.scheme_code,'schemeLabel',s.scheme_name_ko,
    'termCode',t.term_code,'termLabel',t.term_name_ko,
    'parentCode',parent.term_code,'parentLabel',parent.term_name_ko,
    'isPrimary',(rc.is_primary=1),'assignmentRole',rc.assignment_role,
    'evidenceStatus',rc.evidence_status,'reviewStatus',rc.review_status,
    'confidence',rc.confidence
  ) ORDER BY s.scheme_code,rc.is_primary DESC,t.sort_order,t.term_code) AS items
  FROM market_intelligence.record_classifications rc
  JOIN market_intelligence.classification_schemes s
    ON s.classification_scheme_id=rc.classification_scheme_id
  JOIN market_intelligence.classification_terms t
    ON t.classification_scheme_id=rc.classification_scheme_id
   AND t.classification_term_id=rc.classification_term_id
  LEFT JOIN market_intelligence.classification_terms parent
    ON parent.classification_scheme_id=t.classification_scheme_id
   AND parent.classification_term_id=t.parent_term_id
  CROSS JOIN runtime rt
  WHERE rc.target_kind='DOCUMENT' AND rc.target_id=sd.document_id
    AND rc.review_status NOT IN ('REJECTED','SUPERSEDED')
    AND (rc.valid_from IS NULL OR rc.valid_from<=rt.now_utc)
    AND (rc.valid_to IS NULL OR rc.valid_to>rt.now_utc)
    AND s.governance_status='ACTIVE' AND t.governance_status='ACTIVE'
    AND (s.valid_from IS NULL OR s.valid_from<=rt.now_utc)
    AND (s.valid_to IS NULL OR s.valid_to>rt.now_utc)
    AND (t.valid_from IS NULL OR t.valid_from<=rt.now_utc)
    AND (t.valid_to IS NULL OR t.valid_to>rt.now_utc)
) cls ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object(
    'kind',x.entity_kind,'id',x.entity_id,'title',x.entity_title,
    'relationBasis',x.relation_basis,'relationRole',x.relation_role,
    'evidenceStatus',x.evidence_status,'confidence',x.confidence
  ) ORDER BY x.entity_kind,x.entity_title) AS items
  FROM (
    SELECT DISTINCT ON (r.entity_kind,r.entity_id)
      r.entity_kind,r.entity_id,
      coalesce(e.canonical_title,a.canonical_name,o.canonical_name,p.canonical_name,
               lm.mandate_name,sp.process_code,r.entity_id) AS entity_title,
      r.relation_basis,r.relation_role,r.evidence_status,r.confidence
    FROM market_intelligence.v_document_entity_relations r
    LEFT JOIN market_intelligence.events e
      ON r.entity_kind='EVENT' AND e.event_id=r.entity_id
    LEFT JOIN market_intelligence.assets a
      ON r.entity_kind='ASSET' AND a.asset_id=r.entity_id
    LEFT JOIN market_intelligence.organizations o
      ON r.entity_kind='ORGANIZATION' AND o.organization_id=r.entity_id
    LEFT JOIN market_intelligence.projects p
      ON r.entity_kind='PROJECT' AND p.project_id=r.entity_id
    LEFT JOIN market_intelligence.lp_mandates lm
      ON r.entity_kind='LP_MANDATE' AND lm.mandate_id=r.entity_id
    LEFT JOIN market_intelligence.sale_processes sp
      ON r.entity_kind='SALE_PROCESS' AND sp.sale_process_id=r.entity_id
    WHERE r.document_version_id=dv.document_version_id
    ORDER BY r.entity_kind,r.entity_id,
      CASE r.relation_basis WHEN 'CANONICAL_EVENT' THEN 1 WHEN 'RESOLVED_MENTION' THEN 2
           WHEN 'VERIFIED_CLAIM' THEN 3 ELSE 4 END,
      r.confidence DESC NULLS LAST
    LIMIT 100
  ) x
) rel ON true
WHERE sd.document_id=$1
`;

export async function getDocumentDetail(execute: SqlExecutor, id: string): Promise<DocumentDetail | null> {
  const result = await execute(documentDetailSql, [id]);
  return (result.rows[0]?.payload as DocumentDetail | undefined) ?? null;
}
