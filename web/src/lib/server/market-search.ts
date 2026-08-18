import type { SearchKind, SearchRequest, SearchResponse, SearchResult } from "@/lib/search-contract";

export type SqlValue = string | number | boolean | null;

export type SqlExecutor = (
  text: string,
  values: readonly SqlValue[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

const resultKinds = ["EVENT", "ASSET", "ORGANIZATION", "DOCUMENT", "LP_MANDATE", "SALE_PROCESS"] as const;

const searchSql = `
WITH latest_documents AS (
  SELECT DISTINCT ON (document_id)
    document_version_id, document_id, version_no, title, author_name,
    published_at, collected_at, snippet_text, rights_status, metadata_json
  FROM market_intelligence.document_versions
  WHERE $2::text <> 'DOCUMENT' OR $7::text = '' OR document_id IN (
    SELECT document_id FROM market_intelligence.source_documents WHERE document_type = $7
  )
  ORDER BY document_id, version_no DESC, document_version_id DESC
),
search_index AS (
  SELECT
    'EVENT'::text AS kind,
    e.event_id AS id,
    e.canonical_title AS title,
    concat_ws(' · ', ec.name_ko, e.current_stage_code) AS subtitle,
    null::text AS summary,
    e.event_date_start AS date,
    e.lifecycle_status AS status,
    e.overall_confidence::double precision AS confidence,
    'canonical event'::text AS source,
    null::text AS href,
    ec.code::text AS category,
    ec.name_ko::text AS category_label,
    jsonb_strip_nulls(jsonb_build_object(
      'category', ec.name_ko,
      'stage', e.current_stage_code,
      'verification', e.verification_level,
      'assets', ea.asset_names,
      'participants', ep.participant_names
    )) AS metadata,
    concat_ws(' ', e.canonical_title, ec.name_ko, e.current_stage_code, ea.asset_names, ep.participant_names) AS search_text,
    e.event_date_start AS record_date
  FROM market_intelligence.events e
  LEFT JOIN market_intelligence.event_categories ec ON ec.event_category_id=e.primary_category_id
  LEFT JOIN LATERAL (
    SELECT string_agg(a.canonical_name, ', ' ORDER BY a.canonical_name) AS asset_names
    FROM market_intelligence.event_assets link
    JOIN market_intelligence.assets a ON a.asset_id=link.asset_id
    WHERE link.event_id=e.event_id
  ) ea ON true
  LEFT JOIN LATERAL (
    SELECT string_agg(concat(o.canonical_name, ' (', link.role_code, ')'), ', ' ORDER BY o.canonical_name) AS participant_names
    FROM market_intelligence.event_participants link
    JOIN market_intelligence.organizations o ON o.organization_id=link.organization_id
    WHERE link.event_id=e.event_id
  ) ep ON true

  UNION ALL

  SELECT
    'ASSET', a.asset_id, a.canonical_name,
    concat_ws(' · ', ac.name_ko, r.canonical_name),
    coalesce(a.road_address, a.jibun_address),
    a.updated_at, a.status_code, null::double precision,
    'asset master', null::text,
    ac.code::text, ac.name_ko::text,
    jsonb_strip_nulls(jsonb_build_object(
      'assetClass', ac.name_ko,
      'region', r.canonical_name,
      'roadAddress', a.road_address,
      'jibunAddress', a.jibun_address,
      'latitude', a.latitude,
      'longitude', a.longitude
    )),
    concat_ws(' ', a.canonical_name, a.road_address, a.jibun_address, ac.name_ko, r.canonical_name),
    a.updated_at
  FROM market_intelligence.assets a
  LEFT JOIN market_intelligence.asset_classes ac ON ac.asset_class_id=a.asset_class_id
  LEFT JOIN market_intelligence.regions r ON r.region_id=a.region_id

  UNION ALL

  SELECT
    'ORGANIZATION', o.organization_id, o.canonical_name,
    o.organization_type,
    concat_ws(' · ', nullif(o.stock_code,''), nullif(o.dart_corp_code,'')),
    o.updated_at, o.status_code, null::double precision,
    'organization master', null::text,
    o.organization_type::text, o.organization_type::text,
    jsonb_strip_nulls(jsonb_build_object(
      'organizationType', o.organization_type,
      'country', o.country_code,
      'stockCode', o.stock_code,
      'dartCorpCode', o.dart_corp_code
    )),
    concat_ws(' ', o.canonical_name, o.organization_type, o.stock_code, o.dart_corp_code),
    o.updated_at
  FROM market_intelligence.organizations o

  UNION ALL

  SELECT
    'DOCUMENT', sd.document_id, dv.title,
    concat_ws(' · ', sd.publisher_name, sd.document_type),
    CASE WHEN sd.document_type='API_RECORD' THEN concat_ws(' · ',
      concat_ws(' ',dv.metadata_json::jsonb->'api_record'->>'sggNm',dv.metadata_json::jsonb->'api_record'->>'umdNm',dv.metadata_json::jsonb->'api_record'->>'jibun'),
      nullif(dv.metadata_json::jsonb->'api_record'->>'buildingUse',''),
      CASE WHEN nullif(dv.metadata_json::jsonb->'api_record'->>'buildingAr','') IS NOT NULL THEN (dv.metadata_json::jsonb->'api_record'->>'buildingAr') || '㎡' END,
      nullif(dv.metadata_json::jsonb->'api_record'->>'dealingGbn','')
    ) ELSE nullif(dv.snippet_text,'') END,
    coalesce(dv.published_at, dv.collected_at), sd.access_status, null::double precision,
    sd.publisher_name, CASE WHEN sd.document_type='API_RECORD' THEN dv.metadata_json::jsonb->>'source_endpoint' ELSE sd.canonical_url END,
    sd.document_type::text, sd.document_type::text,
    jsonb_strip_nulls(jsonb_build_object(
      'publisher', sd.publisher_name,
      'documentType', sd.document_type,
      'author', dv.author_name,
      'rightsStatus', dv.rights_status,
      'version', dv.version_no,
      'apiRecord', CASE WHEN sd.document_type='API_RECORD' THEN dv.metadata_json::jsonb->'api_record' END,
      'dealDate', CASE WHEN sd.document_type='API_RECORD' THEN dv.metadata_json::jsonb->>'deal_date' END,
      'duplicateOccurrence', CASE WHEN sd.document_type='API_RECORD' THEN dv.metadata_json::jsonb->>'duplicate_occurrence' END
    )),
    concat_ws(' ', dv.title, sd.publisher_name, dv.snippet_text),
    coalesce(dv.published_at, dv.collected_at)
  FROM market_intelligence.source_documents sd
  JOIN latest_documents dv ON dv.document_id=sd.document_id

  UNION ALL

  SELECT
    'LP_MANDATE', lm.mandate_id, lm.mandate_name,
    concat_ws(' · ', o.canonical_name, lm.vintage_year::text),
    lm.mandate_scope,
    coalesce(lm.selected_at, lm.announced_at), lm.mandate_status, null::double precision,
    'LP mandate', null::text,
    lm.mandate_status::text, lm.mandate_status::text,
    jsonb_strip_nulls(jsonb_build_object(
      'lp', o.canonical_name,
      'mandateCode', lm.mandate_code,
      'vintageYear', lm.vintage_year,
      'evidenceStatus', lm.evidence_status,
      'reviewStatus', lm.review_status,
      'applicationDeadline', lm.application_deadline
    )),
    concat_ws(' ', lm.mandate_name, lm.mandate_code, lm.mandate_scope, o.canonical_name),
    coalesce(lm.selected_at, lm.announced_at)
  FROM market_intelligence.lp_mandates lm
  LEFT JOIN market_intelligence.organizations o ON o.organization_id=lm.lp_organization_id

  UNION ALL

  SELECT
    'SALE_PROCESS', sp.sale_process_id,
    coalesce(e.canonical_title, sp.process_code),
    concat_ws(' · ', sp.sale_method, sp.process_status),
    concat_ws(' · ', sp.process_code, sp.evidence_status),
    coalesce(sp.closed_at, sp.launched_at), sp.process_status, null::double precision,
    'sale process', null::text,
    sp.process_status::text, sp.process_status::text,
    jsonb_strip_nulls(jsonb_build_object(
      'processCode', sp.process_code,
      'saleMethod', sp.sale_method,
      'eventId', sp.event_id,
      'evidenceStatus', sp.evidence_status,
      'reviewStatus', sp.review_status
    )),
    concat_ws(' ', e.canonical_title, sp.process_code, sp.sale_method, sp.process_status),
    coalesce(sp.closed_at, sp.launched_at)
  FROM market_intelligence.sale_processes sp
  LEFT JOIN market_intelligence.events e ON e.event_id=sp.event_id
),
scoped AS (
  SELECT * FROM search_index
  WHERE ($1::text='' OR search_text ILIKE '%' || $1 || '%')
    AND ($3::text IS NULL OR left(record_date,10) >= $3)
    AND ($4::text IS NULL OR left(record_date,10) <= $4)
    AND ($7::text='' OR category=$7)
    AND (
      kind<>'DOCUMENT' OR coalesce(metadata->>'documentType','')<>'API_RECORD' OR $8::boolean
      OR coalesce(nullif(regexp_replace(metadata->'apiRecord'->>'dealAmount','[^0-9.]','','g'),''),'0')::numeric >= 10000000
    )
),
facet_rows AS (
  SELECT kind, count(*)::int AS count FROM scoped GROUP BY kind
),
filtered AS (
  SELECT * FROM scoped WHERE $2::text='ALL' OR kind=$2
),
page_rows AS (
  SELECT kind,id,title,subtitle,summary,date,status,confidence,source,href,category,category_label AS "categoryLabel",metadata
  FROM filtered
  ORDER BY record_date DESC NULLS LAST, title, id
  LIMIT $5 OFFSET $6
)
SELECT jsonb_build_object(
  'total', (SELECT count(*)::int FROM filtered),
  'facets', coalesce((SELECT jsonb_object_agg(kind,count) FROM facet_rows), '{}'::jsonb),
  'results', coalesce((SELECT jsonb_agg(to_jsonb(page_rows)) FROM page_rows), '[]'::jsonb)
) AS payload
`;

type Payload = {
  total?: number;
  facets?: Partial<Record<(typeof resultKinds)[number], number>>;
  results?: SearchResult[];
};

export async function searchMarket(execute: SqlExecutor, request: SearchRequest): Promise<Omit<SearchResponse, "elapsedMs" | "generatedAt" | "database">> {
  const offset = (request.page - 1) * request.pageSize;
  const queryResult = await execute(searchSql, [
    request.q,
    request.kind,
    request.from,
    request.to,
    request.pageSize,
    offset,
    request.category,
    request.includeTransactionsUnder1000Eok,
  ]);
  const payload = (queryResult.rows[0]?.payload ?? {}) as Payload;
  const facets = Object.fromEntries(
    resultKinds.map((kind) => [kind, Number(payload.facets?.[kind] ?? 0)]),
  ) as Record<Exclude<SearchKind, "ALL">, number>;

  return {
    request,
    results: payload.results ?? [],
    facets,
    total: Number(payload.total ?? 0),
  };
}
