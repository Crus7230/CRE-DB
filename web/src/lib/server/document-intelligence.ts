import type { SqlExecutor } from "@/lib/server/market-search";

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
  contentMode: "FULL_TEXT" | "SNIPPET" | "METADATA";
  summary: string | null;
  snippet: string | null;
  storedText: string | null;
  eventSignals: Array<{ category: string; categoryLabel: string; title: string | null; summary: string | null; stage: string | null; eventDate: string | null; confidence: number | null; status: string }>;
  keywords: Array<{ type: string; label: string; value: string; confidence: number | null }>;
  transaction: null | {
    dealDate: string | null; dealAmount: string | null; buildingAr: string | null; plottageAr: string | null;
    buildingUse: string | null; buildingType: string | null; buildYear: string | null; floor: string | null;
    region: string | null; address: string | null; landUse: string | null; dealingType: string | null;
    buyerType: string | null; sellerType: string | null; shareType: string | null; cancelDate: string | null;
    duplicateOccurrence: number; screeningBand: "EXCLUDED" | "REVIEW" | "KEEP" | "UNKNOWN";
  };
};

const documentDetailSql = `
WITH latest AS (
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
  'sourceUrl',CASE WHEN sd.document_type='API_RECORD' THEN dv.metadata_json::jsonb->>'source_endpoint' ELSE sd.canonical_url END,
  'author',dv.author_name,
  'publishedAt',dv.published_at,
  'collectedAt',dv.collected_at,
  'rightsStatus',dv.rights_status,
  'contentMode',CASE WHEN length(trim(coalesce(dv.stored_text,'')))>0 THEN 'FULL_TEXT' WHEN length(trim(coalesce(dv.snippet_text,'')))>0 THEN 'SNIPPET' ELSE 'METADATA' END,
  'summary',coalesce(ev.primary_summary,nullif(dv.snippet_text,'')),
  'snippet',nullif(dv.snippet_text,''),
  'storedText',nullif(left(dv.stored_text,12000),''),
  'eventSignals',coalesce(ev.items,'[]'::jsonb),
  'keywords',coalesce(kw.items,'[]'::jsonb),
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
WHERE sd.document_id=$1
`;

export async function getDocumentDetail(execute: SqlExecutor, id: string): Promise<DocumentDetail | null> {
  const result = await execute(documentDetailSql, [id]);
  return (result.rows[0]?.payload as DocumentDetail | undefined) ?? null;
}
