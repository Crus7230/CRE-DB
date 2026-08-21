import type { SearchKind, SearchRequest, SearchResponse, SearchResult } from "@/lib/search-contract";

export type SqlValue = string | number | boolean | null;

export type SqlExecutor = (
  text: string,
  values: readonly SqlValue[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

const resultKinds = ["EVENT", "ASSET", "ORGANIZATION", "DOCUMENT", "LP_MANDATE", "SALE_PROCESS"] as const;

const searchSql = `
WITH runtime AS (
  SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS now_utc
), document_type_groups(group_key, group_label, document_type) AS (
  VALUES
    ('TRANSACTION_EVIDENCE', '거래·가격 근거', 'API_RECORD'),
    ('CORPORATE_EVIDENCE', '기업·사업 근거', 'DISCLOSURE'),
    ('CORPORATE_EVIDENCE', '기업·사업 근거', 'OFFICIAL_FILING'),
    ('CORPORATE_EVIDENCE', '기업·사업 근거', 'PRESS_RELEASE'),
    ('MARKET_EVIDENCE', '시장동향 근거', 'RSS_ITEM'),
    ('MARKET_EVIDENCE', '시장동향 근거', 'ARTICLE'),
    ('MARKET_EVIDENCE', '시장동향 근거', 'RESEARCH_REPORT'),
    ('PROCESS_EVIDENCE', '절차·공고 근거', 'BID_NOTICE'),
    ('PROCESS_EVIDENCE', '절차·공고 근거', 'NOTICE')
), archive_rows AS (
  SELECT ai.*
  FROM market_intelligence.archived_serving_index ai
  JOIN market_intelligence.archive_snapshots ars
    ON ars.archive_snapshot_id=ai.archive_snapshot_id
   AND ars.is_current=1 AND ars.integrity_status='VALIDATED'
), latest_documents AS (
  SELECT DISTINCT ON (document_id)
    document_version_id, document_id, version_no, title, author_name,
    published_at, collected_at, snippet_text, rights_status, metadata_json
  FROM market_intelligence.document_versions
  WHERE $2::text <> 'DOCUMENT' OR $7::text = '' OR $9::text <> '' OR document_id IN (
    SELECT document_id FROM market_intelligence.source_documents
    WHERE document_type = $7 OR document_type IN (
      SELECT document_type FROM document_type_groups WHERE group_key = $7
    )
  )
  ORDER BY document_id, version_no DESC, document_version_id DESC
), classification_summary AS (
  SELECT rc.target_kind,rc.target_id,
    max(t.term_code) FILTER (WHERE s.scheme_code='MARKET_CATEGORY' AND rc.is_primary=1) AS primary_market_category_code,
    max(t.term_name_ko) FILTER (WHERE s.scheme_code='MARKET_CATEGORY' AND rc.is_primary=1) AS primary_market_category_label,
    max(t.term_code) FILTER (WHERE s.scheme_code='DOCUMENT_PURPOSE' AND rc.is_primary=1) AS primary_document_purpose_code,
    max(t.term_name_ko) FILTER (WHERE s.scheme_code='DOCUMENT_PURPOSE' AND rc.is_primary=1) AS primary_document_purpose_label,
    max(t.term_code) FILTER (WHERE s.scheme_code='ASSET_CLASS' AND rc.is_primary=1) AS primary_asset_class_code,
    max(t.term_name_ko) FILTER (WHERE s.scheme_code='ASSET_CLASS' AND rc.is_primary=1) AS primary_asset_class_label,
    max(t.term_code) FILTER (WHERE s.scheme_code='ORGANIZATION_TYPE' AND rc.is_primary=1) AS primary_organization_type_code,
    max(t.term_name_ko) FILTER (WHERE s.scheme_code='ORGANIZATION_TYPE' AND rc.is_primary=1) AS primary_organization_type_label,
    max(t.term_code) FILTER (WHERE s.scheme_code='EVIDENCE_GRADE' AND rc.is_primary=1) AS primary_evidence_grade_code,
    max(t.term_name_ko) FILTER (WHERE s.scheme_code='EVIDENCE_GRADE' AND rc.is_primary=1) AS primary_evidence_grade_label,
    count(*)::int AS classification_count
  FROM market_intelligence.record_classifications rc
  JOIN market_intelligence.classification_schemes s
    ON s.classification_scheme_id=rc.classification_scheme_id
  JOIN market_intelligence.classification_terms t
    ON t.classification_scheme_id=rc.classification_scheme_id
   AND t.classification_term_id=rc.classification_term_id
  CROSS JOIN runtime rt
  WHERE rc.review_status NOT IN ('REJECTED','SUPERSEDED')
    AND (rc.valid_from IS NULL OR rc.valid_from<=rt.now_utc)
    AND (rc.valid_to IS NULL OR rc.valid_to>rt.now_utc)
    AND s.governance_status='ACTIVE' AND t.governance_status='ACTIVE'
    AND (s.valid_from IS NULL OR s.valid_from<=rt.now_utc)
    AND (s.valid_to IS NULL OR s.valid_to>rt.now_utc)
    AND (t.valid_from IS NULL OR t.valid_from<=rt.now_utc)
    AND (t.valid_to IS NULL OR t.valid_to>rt.now_utc)
  GROUP BY rc.target_kind,rc.target_id
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
    coalesce(rcs.primary_market_category_code, ec.code)::text AS category,
    coalesce(rcs.primary_market_category_label, ec.name_ko)::text AS category_label,
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
  LEFT JOIN classification_summary rcs ON rcs.target_kind='EVENT' AND rcs.target_id=e.event_id
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
    coalesce(rcs.primary_asset_class_code, ac.code)::text,
    coalesce(rcs.primary_asset_class_label, ac.name_ko)::text,
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
  LEFT JOIN classification_summary rcs ON rcs.target_kind='ASSET' AND rcs.target_id=a.asset_id
  LEFT JOIN market_intelligence.asset_classes ac ON ac.asset_class_id=a.asset_class_id
  LEFT JOIN market_intelligence.regions r ON r.region_id=a.region_id

  UNION ALL

  SELECT
    'ORGANIZATION', o.organization_id, o.canonical_name,
    o.organization_type,
    concat_ws(' · ', nullif(o.stock_code,''), nullif(o.dart_corp_code,'')),
    o.updated_at, o.status_code, null::double precision,
    'organization master', null::text,
    coalesce(rcs.primary_organization_type_code, o.organization_type)::text,
    coalesce(rcs.primary_organization_type_label, o.organization_type)::text,
    jsonb_strip_nulls(jsonb_build_object(
      'organizationType', o.organization_type,
      'country', o.country_code,
      'stockCode', o.stock_code,
      'dartCorpCode', o.dart_corp_code
    )),
    concat_ws(' ', o.canonical_name, o.organization_type, o.stock_code, o.dart_corp_code),
    o.updated_at
  FROM market_intelligence.organizations o
  LEFT JOIN classification_summary rcs ON rcs.target_kind='ORGANIZATION' AND rcs.target_id=o.organization_id
  JOIN market_intelligence.organization_scope_assessments osa
    ON osa.organization_id=o.organization_id
   AND osa.scope_code='CRE'
   AND osa.classifier_version='ORG_CRE_SCOPE_RULE_V1'
   AND osa.status_code='CRE_CONFIRMED'

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
    coalesce(rcs.primary_document_purpose_code, sd.document_type)::text,
    coalesce(rcs.primary_document_purpose_label, sd.document_type)::text,
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
  LEFT JOIN classification_summary rcs ON rcs.target_kind='DOCUMENT' AND rcs.target_id=sd.document_id
  LEFT JOIN market_intelligence.collection_sources cs ON cs.source_id=sd.source_id
  LEFT JOIN market_intelligence.document_scope_assessments dsa
    ON dsa.document_version_id=dv.document_version_id
   AND dsa.scope_code='CRE'
   AND dsa.classifier_version=CASE cs.source_code
     WHEN 'OPENDART' THEN 'DART_CRE_SCOPE_RULE_V1'
     WHEN 'GOOGLE_NEWS_RSS' THEN 'NEWS_CRE_SCOPE_RULE_V1'
     WHEN 'MOLIT_REAL_TRANSACTION' THEN 'MOLIT_SCOPE_TIERED_V2'
   END
  WHERE (
      cs.source_code IS NULL
      OR cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION')
      OR dsa.status_code='CRE_CONFIRMED'
    )

  UNION ALL

  SELECT
    'LP_MANDATE', lm.mandate_id, lm.mandate_name,
    concat_ws(' · ', o.canonical_name, lm.vintage_year::text),
    lm.mandate_scope,
    coalesce(lm.selected_at, lm.announced_at), lm.mandate_status, null::double precision,
    'LP mandate', null::text,
    coalesce(rcs.primary_market_category_code, lm.mandate_status)::text,
    coalesce(rcs.primary_market_category_label, lm.mandate_status)::text,
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
  LEFT JOIN classification_summary rcs ON rcs.target_kind='LP_MANDATE' AND rcs.target_id=lm.mandate_id
  LEFT JOIN market_intelligence.organizations o ON o.organization_id=lm.lp_organization_id
  UNION ALL

  SELECT
    'SALE_PROCESS', sp.sale_process_id,
    coalesce(e.canonical_title, sp.process_code),
    concat_ws(' · ', sp.sale_method, sp.process_status),
    concat_ws(' · ', sp.process_code, sp.evidence_status),
    coalesce(sp.closed_at, sp.launched_at), sp.process_status, null::double precision,
    'sale process', null::text,
    coalesce(rcs.primary_market_category_code, sp.process_status)::text,
    coalesce(rcs.primary_market_category_label, sp.process_status)::text,
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
  LEFT JOIN classification_summary rcs ON rcs.target_kind='SALE_PROCESS' AND rcs.target_id=sp.sale_process_id
  LEFT JOIN market_intelligence.events e ON e.event_id=sp.event_id
  UNION ALL

  SELECT
    ai.record_kind::text AS kind,
    ai.record_id AS id,
    ai.canonical_title AS title,
    concat_ws(' · ', '보관 인덱스', ai.lifecycle_status) AS subtitle,
    ai.summary_text AS summary,
    coalesce(ai.event_date_start, ai.event_date_end) AS date,
    'ARCHIVED_LOCAL'::text AS status,
    null::double precision AS confidence,
    coalesce(ai.publisher_name, 'local full archive') AS source,
    ai.canonical_url AS href,
    coalesce(rcs.primary_market_category_code, ai.category_code) AS category,
    coalesce(rcs.primary_market_category_label, ai.category_code) AS category_label,
    jsonb_strip_nulls(jsonb_build_object(
      'archived', true,
      'originalStatus', ai.lifecycle_status,
      'archiveLocator', ai.archive_locator,
      'archiveSnapshotSha256', ai.archive_snapshot_sha256,
      'sourceDocumentId', ai.source_document_id,
      'sourceDocumentVersionId', ai.source_document_version_id
    )) AS metadata,
    concat_ws(' ', ai.canonical_title, ai.summary_text, ai.publisher_name, ai.category_code, ai.lifecycle_status) AS search_text,
    coalesce(ai.event_date_start, ai.event_date_end) AS record_date
  FROM archive_rows ai
  LEFT JOIN classification_summary rcs ON rcs.target_kind=ai.record_kind AND rcs.target_id=ai.record_id
  WHERE ai.record_kind IN ('EVENT','DOCUMENT','LP_MANDATE','SALE_PROCESS')
    AND NOT (
      (ai.record_kind='EVENT' AND EXISTS (
        SELECT 1 FROM market_intelligence.events e WHERE e.event_id=ai.record_id
      )) OR
      (ai.record_kind='DOCUMENT' AND EXISTS (
        SELECT 1 FROM market_intelligence.source_documents sd WHERE sd.document_id=ai.record_id
      )) OR
      (ai.record_kind='LP_MANDATE' AND EXISTS (
        SELECT 1 FROM market_intelligence.lp_mandates lm WHERE lm.mandate_id=ai.record_id
      )) OR
      (ai.record_kind='SALE_PROCESS' AND EXISTS (
        SELECT 1 FROM market_intelligence.sale_processes sp WHERE sp.sale_process_id=ai.record_id
      ))
    )
),
scoped AS (
  SELECT * FROM search_index
  WHERE ($1::text='' OR search_text ILIKE '%' || $1 || '%')
    AND ($3::text IS NULL OR left(record_date,10) >= $3)
    AND ($4::text IS NULL OR left(record_date,10) <= $4)
    AND (
      $7::text='' OR
      EXISTS (
        SELECT 1
        FROM market_intelligence.record_classifications rc
        JOIN market_intelligence.classification_terms ct
          ON ct.classification_scheme_id=rc.classification_scheme_id
         AND ct.classification_term_id=rc.classification_term_id
        JOIN market_intelligence.classification_schemes csc
          ON csc.classification_scheme_id=rc.classification_scheme_id
        WHERE rc.target_kind=kind AND rc.target_id=id
          AND ct.term_code=$7
          AND ($9::text='' OR csc.scheme_code=$9)
          AND rc.review_status NOT IN ('REJECTED','SUPERSEDED')
          AND (rc.valid_from IS NULL OR rc.valid_from<=(SELECT now_utc FROM runtime))
          AND (rc.valid_to IS NULL OR rc.valid_to>(SELECT now_utc FROM runtime))
          AND csc.governance_status='ACTIVE' AND ct.governance_status='ACTIVE' AND ct.is_assignable=1
          AND (csc.valid_from IS NULL OR csc.valid_from<=(SELECT now_utc FROM runtime))
          AND (csc.valid_to IS NULL OR csc.valid_to>(SELECT now_utc FROM runtime))
          AND (ct.valid_from IS NULL OR ct.valid_from<=(SELECT now_utc FROM runtime))
          AND (ct.valid_to IS NULL OR ct.valid_to>(SELECT now_utc FROM runtime))
      ) OR
      ($9::text='' AND kind='DOCUMENT' AND (category=$7 OR category IN (
        SELECT document_type FROM document_type_groups WHERE group_key=$7
      ))) OR
      ($9::text='' AND kind<>'DOCUMENT' AND category=$7)
    )
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
page_base AS (
  SELECT *
  FROM filtered
  ORDER BY record_date DESC NULLS LAST, title, id
  LIMIT $5 OFFSET $6
),
page_rows AS (
  SELECT f.kind,f.id,f.title,f.subtitle,f.summary,f.date,f.status,f.confidence,f.source,f.href,
    f.category,f.category_label AS "categoryLabel",
    jsonb_strip_nulls(f.metadata || jsonb_build_object(
      'documentPurposeCode',rcs.primary_document_purpose_code,
      'documentPurposeLabel',rcs.primary_document_purpose_label,
      'evidenceGradeCode',rcs.primary_evidence_grade_code,
      'evidenceGradeLabel',rcs.primary_evidence_grade_label,
      'classificationCount',rcs.classification_count,
      'evidenceCount',CASE WHEN f.kind='EVENT' THEN coalesce(event_evidence.evidence_count,0) END
    )) AS metadata
  FROM page_base f
  LEFT JOIN classification_summary rcs ON rcs.target_kind=f.kind AND rcs.target_id=f.id
  LEFT JOIN LATERAL (
    SELECT count(DISTINCT relation.document_id)::int AS evidence_count
    FROM market_intelligence.v_document_entity_relations relation
    WHERE relation.entity_kind='EVENT'
      AND relation.entity_id=f.id
      AND relation.relation_basis='CANONICAL_EVENT'
  ) event_evidence ON f.kind='EVENT'
  ORDER BY f.record_date DESC NULLS LAST, f.title, f.id
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
    request.classificationScheme,
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
