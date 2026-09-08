import type { SearchKind, SearchRequest, SearchResponse, SearchResult } from "@/lib/search-contract";

export type SqlValue = string | number | boolean | null;

export type SqlExecutor = (
  text: string,
  values: readonly SqlValue[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

const resultKinds = ["EVENT", "ASSET", "ORGANIZATION", "DOCUMENT", "LP_MANDATE", "SALE_PROCESS"] as const;

const searchSql = `
WITH runtime AS (
  SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now') AS now_utc
), document_type_groups(group_key,group_label,document_type) AS (
  VALUES
    ('TRANSACTION_EVIDENCE','거래·가격 근거','API_RECORD'),
    ('CORPORATE_EVIDENCE','기업·사업 근거','DISCLOSURE'),
    ('CORPORATE_EVIDENCE','기업·사업 근거','OFFICIAL_FILING'),
    ('CORPORATE_EVIDENCE','기업·사업 근거','PRESS_RELEASE'),
    ('MARKET_EVIDENCE','시장동향 근거','RSS_ITEM'),
    ('MARKET_EVIDENCE','시장동향 근거','ARTICLE'),
    ('MARKET_EVIDENCE','시장동향 근거','RESEARCH_REPORT'),
    ('PROCESS_EVIDENCE','절차·공고 근거','BID_NOTICE'),
    ('PROCESS_EVIDENCE','절차·공고 근거','NOTICE')
), archive_rows AS (
  SELECT ai.*
  FROM archived_serving_index ai
  JOIN archive_snapshots ars ON ars.archive_snapshot_id=ai.archive_snapshot_id
    AND ars.is_current=1 AND ars.integrity_status='VALIDATED'
), ranked_documents AS (
  SELECT document_version_id,document_id,version_no,title,author_name,
         published_at,collected_at,snippet_text,rights_status,metadata_json,
         row_number() OVER (
           PARTITION BY document_id ORDER BY version_no DESC,document_version_id DESC
         ) AS version_rank
  FROM document_versions
  WHERE $2<>'DOCUMENT' OR $7='' OR $9<>'' OR document_id IN (
    SELECT document_id FROM source_documents
    WHERE document_type=$7 OR document_type IN (
      SELECT document_type FROM document_type_groups WHERE group_key=$7
    )
  )
), latest_documents AS (
  SELECT document_version_id,document_id,version_no,title,author_name,
         published_at,collected_at,snippet_text,rights_status,metadata_json
  FROM ranked_documents WHERE version_rank=1
), ranked_cre_scope AS (
  SELECT document_version_id,classifier_version,status_code,
         row_number() OVER (
           PARTITION BY document_version_id
           ORDER BY CASE classifier_version
             WHEN 'NEWS_CRE_SCOPE_RULE_V3' THEN 0
             WHEN 'NEWS_CRE_SCOPE_RULE_V2' THEN 1
             ELSE 2 END,
             assessed_at DESC,document_scope_assessment_id DESC
         ) AS scope_rank
  FROM document_scope_assessments
  WHERE scope_code='CRE' AND classifier_version IN (
    'DART_CRE_SCOPE_RULE_V1','NEWS_CRE_SCOPE_RULE_V3','NEWS_CRE_SCOPE_RULE_V2',
    'NEWS_CRE_SCOPE_RULE_V1','MOLIT_SCOPE_TIERED_V2'
  )
), current_cre_scope AS (
  SELECT document_version_id,classifier_version,status_code
  FROM ranked_cre_scope WHERE scope_rank=1
), classification_summary AS (
  SELECT rc.target_kind,rc.target_id,
    max(CASE WHEN s.scheme_code='MARKET_CATEGORY' AND rc.is_primary=1 THEN t.term_code END) AS primary_market_category_code,
    max(CASE WHEN s.scheme_code='MARKET_CATEGORY' AND rc.is_primary=1 THEN t.term_name_ko END) AS primary_market_category_label,
    max(CASE WHEN s.scheme_code='DOCUMENT_PURPOSE' AND rc.is_primary=1 THEN t.term_code END) AS primary_document_purpose_code,
    max(CASE WHEN s.scheme_code='DOCUMENT_PURPOSE' AND rc.is_primary=1 THEN t.term_name_ko END) AS primary_document_purpose_label,
    max(CASE WHEN s.scheme_code='ASSET_CLASS' AND rc.is_primary=1 THEN t.term_code END) AS primary_asset_class_code,
    max(CASE WHEN s.scheme_code='ASSET_CLASS' AND rc.is_primary=1 THEN t.term_name_ko END) AS primary_asset_class_label,
    max(CASE WHEN s.scheme_code='ORGANIZATION_TYPE' AND rc.is_primary=1 THEN t.term_code END) AS primary_organization_type_code,
    max(CASE WHEN s.scheme_code='ORGANIZATION_TYPE' AND rc.is_primary=1 THEN t.term_name_ko END) AS primary_organization_type_label,
    max(CASE WHEN s.scheme_code='EVIDENCE_GRADE' AND rc.is_primary=1 THEN t.term_code END) AS primary_evidence_grade_code,
    max(CASE WHEN s.scheme_code='EVIDENCE_GRADE' AND rc.is_primary=1 THEN t.term_name_ko END) AS primary_evidence_grade_label,
    count(*) AS classification_count
  FROM record_classifications rc
  JOIN classification_schemes s ON s.classification_scheme_id=rc.classification_scheme_id
  JOIN classification_terms t ON t.classification_scheme_id=rc.classification_scheme_id
    AND t.classification_term_id=rc.classification_term_id
  CROSS JOIN runtime rt
  WHERE rc.review_status='APPROVED' AND rc.assignment_role<>'LEGACY_BACKFILL'
    AND ($2='ALL' OR rc.target_kind=$2)
    AND (rc.valid_from IS NULL OR rc.valid_from<=rt.now_utc)
    AND (rc.valid_to IS NULL OR rc.valid_to>rt.now_utc)
    AND s.governance_status='ACTIVE' AND t.governance_status='ACTIVE'
    AND (s.valid_from IS NULL OR s.valid_from<=rt.now_utc)
    AND (s.valid_to IS NULL OR s.valid_to>rt.now_utc)
    AND (t.valid_from IS NULL OR t.valid_from<=rt.now_utc)
    AND (t.valid_to IS NULL OR t.valid_to>rt.now_utc)
  GROUP BY rc.target_kind,rc.target_id
), search_index AS (
  SELECT
    'EVENT' AS kind,e.event_id AS id,e.canonical_title AS title,
    concat_ws(' · ',ec.name_ko,e.current_stage_code) AS subtitle,
    NULL AS summary,e.event_date_start AS date,e.lifecycle_status AS status,
    e.overall_confidence AS confidence,'canonical event' AS source,NULL AS href,
    coalesce(rcs.primary_market_category_code,ec.code) AS category,
    coalesce(rcs.primary_market_category_label,ec.name_ko) AS category_label,
    json_patch('{}',json_object(
      'category',ec.name_ko,'stage',e.current_stage_code,'verification',e.verification_level,
      'assets',(SELECT group_concat(a.canonical_name,', ')
        FROM event_assets link JOIN assets a ON a.asset_id=link.asset_id
        WHERE link.event_id=e.event_id),
      'participants',(SELECT group_concat(o.canonical_name || ' (' || link.role_code || ')',', ')
        FROM event_participants link JOIN organizations o ON o.organization_id=link.organization_id
        WHERE link.event_id=e.event_id)
    )) AS metadata,
    concat_ws(' ',e.canonical_title,ec.name_ko,e.current_stage_code,
      (SELECT group_concat(a.canonical_name,' ') FROM event_assets link
       JOIN assets a ON a.asset_id=link.asset_id WHERE link.event_id=e.event_id),
      (SELECT group_concat(o.canonical_name,' ') FROM event_participants link
       JOIN organizations o ON o.organization_id=link.organization_id WHERE link.event_id=e.event_id)
    ) AS search_text,
    e.event_date_start AS record_date
  FROM events e
  LEFT JOIN classification_summary rcs ON rcs.target_kind='EVENT' AND rcs.target_id=e.event_id
  LEFT JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
  WHERE $2 IN ('ALL','EVENT')

  UNION ALL

  SELECT 'ASSET',a.asset_id,a.canonical_name,concat_ws(' · ',ac.name_ko,r.canonical_name),
    coalesce(a.road_address,a.jibun_address),a.updated_at,a.status_code,NULL,
    'asset master',NULL,
    coalesce(rcs.primary_asset_class_code,ac.code),
    coalesce(rcs.primary_asset_class_label,ac.name_ko),
    json_patch('{}',json_object(
      'assetClass',ac.name_ko,'region',r.canonical_name,'roadAddress',a.road_address,
      'jibunAddress',a.jibun_address,'latitude',a.latitude,'longitude',a.longitude
    )),
    concat_ws(' ',a.canonical_name,a.road_address,a.jibun_address,ac.name_ko,r.canonical_name),
    a.updated_at
  FROM assets a
  LEFT JOIN classification_summary rcs ON rcs.target_kind='ASSET' AND rcs.target_id=a.asset_id
  LEFT JOIN asset_classes ac ON ac.asset_class_id=a.asset_class_id
  LEFT JOIN regions r ON r.region_id=a.region_id
  WHERE $2 IN ('ALL','ASSET')

  UNION ALL

  SELECT 'ORGANIZATION',o.organization_id,o.canonical_name,o.organization_type,
    concat_ws(' · ',nullif(o.stock_code,''),nullif(o.dart_corp_code,'')),
    o.updated_at,o.status_code,NULL,'organization master',NULL,
    coalesce(rcs.primary_organization_type_code,o.organization_type),
    coalesce(rcs.primary_organization_type_label,o.organization_type),
    json_patch('{}',json_object(
      'organizationType',o.organization_type,'country',o.country_code,
      'stockCode',o.stock_code,'dartCorpCode',o.dart_corp_code
    )),
    concat_ws(' ',o.canonical_name,o.organization_type,o.stock_code,o.dart_corp_code),o.updated_at
  FROM organizations o
  LEFT JOIN classification_summary rcs ON rcs.target_kind='ORGANIZATION' AND rcs.target_id=o.organization_id
  JOIN organization_scope_assessments osa ON osa.organization_id=o.organization_id
    AND osa.scope_code='CRE' AND osa.classifier_version='ORG_CRE_SCOPE_RULE_V1'
    AND osa.status_code='CRE_CONFIRMED'
  WHERE $2 IN ('ALL','ORGANIZATION')

  UNION ALL

  SELECT 'DOCUMENT',sd.document_id,dv.title,concat_ws(' · ',sd.publisher_name,sd.document_type),
    CASE WHEN sd.document_type='API_RECORD' THEN concat_ws(' · ',
      concat_ws(' ',json_extract(dv.metadata_json,'$.api_record.sggNm'),
        json_extract(dv.metadata_json,'$.api_record.umdNm'),json_extract(dv.metadata_json,'$.api_record.jibun')),
      nullif(json_extract(dv.metadata_json,'$.api_record.buildingUse'),''),
      CASE WHEN nullif(json_extract(dv.metadata_json,'$.api_record.buildingAr'),'') IS NOT NULL
        THEN json_extract(dv.metadata_json,'$.api_record.buildingAr') || '㎡' END,
      nullif(json_extract(dv.metadata_json,'$.api_record.dealingGbn'),'')
    ) ELSE nullif(dv.snippet_text,'') END,
    coalesce(dv.published_at,dv.collected_at),sd.access_status,NULL,sd.publisher_name,
    CASE WHEN sd.document_type='API_RECORD' THEN json_extract(dv.metadata_json,'$.source_endpoint')
      ELSE sd.canonical_url END,
    coalesce(rcs.primary_document_purpose_code,sd.document_type),
    coalesce(rcs.primary_document_purpose_label,sd.document_type),
    json_patch('{}',json_object(
      'publisher',sd.publisher_name,'documentType',sd.document_type,'author',dv.author_name,
      'rightsStatus',dv.rights_status,'version',dv.version_no,
      'apiRecord',CASE WHEN sd.document_type='API_RECORD' THEN json(json_extract(dv.metadata_json,'$.api_record')) END,
      'dealDate',CASE WHEN sd.document_type='API_RECORD' THEN json_extract(dv.metadata_json,'$.deal_date') END,
      'duplicateOccurrence',CASE WHEN sd.document_type='API_RECORD' THEN json_extract(dv.metadata_json,'$.duplicate_occurrence') END
    )),
    concat_ws(' ',dv.title,sd.publisher_name,dv.snippet_text),
    coalesce(dv.published_at,dv.collected_at)
  FROM source_documents sd
  JOIN latest_documents dv ON dv.document_id=sd.document_id
  LEFT JOIN classification_summary rcs ON rcs.target_kind='DOCUMENT' AND rcs.target_id=sd.document_id
  LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
  LEFT JOIN current_cre_scope dsa ON dsa.document_version_id=dv.document_version_id
  WHERE (cs.source_code IS NULL
      OR cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION')
      OR dsa.status_code='CRE_CONFIRMED')
    AND $2 IN ('ALL','DOCUMENT')

  UNION ALL

  SELECT 'LP_MANDATE',lm.mandate_id,lm.mandate_name,
    concat_ws(' · ',o.canonical_name,lm.vintage_year),lm.mandate_scope,
    coalesce(lm.selected_at,lm.announced_at),lm.mandate_status,NULL,'LP mandate',NULL,
    coalesce(rcs.primary_market_category_code,lm.mandate_status),
    coalesce(rcs.primary_market_category_label,lm.mandate_status),
    json_patch('{}',json_object(
      'lp',o.canonical_name,'mandateCode',lm.mandate_code,'vintageYear',lm.vintage_year,
      'evidenceStatus',lm.evidence_status,'reviewStatus',lm.review_status,
      'applicationDeadline',lm.application_deadline
    )),
    concat_ws(' ',lm.mandate_name,lm.mandate_code,lm.mandate_scope,o.canonical_name),
    coalesce(lm.selected_at,lm.announced_at)
  FROM lp_mandates lm
  LEFT JOIN classification_summary rcs ON rcs.target_kind='LP_MANDATE' AND rcs.target_id=lm.mandate_id
  LEFT JOIN organizations o ON o.organization_id=lm.lp_organization_id
  WHERE $2 IN ('ALL','LP_MANDATE')

  UNION ALL

  SELECT 'SALE_PROCESS',sp.sale_process_id,coalesce(e.canonical_title,sp.process_code),
    concat_ws(' · ',sp.sale_method,sp.process_status),concat_ws(' · ',sp.process_code,sp.evidence_status),
    coalesce(sp.closed_at,sp.launched_at),sp.process_status,NULL,'sale process',NULL,
    coalesce(rcs.primary_market_category_code,sp.process_status),
    coalesce(rcs.primary_market_category_label,sp.process_status),
    json_patch('{}',json_object(
      'processCode',sp.process_code,'saleMethod',sp.sale_method,'eventId',sp.event_id,
      'evidenceStatus',sp.evidence_status,'reviewStatus',sp.review_status
    )),
    concat_ws(' ',e.canonical_title,sp.process_code,sp.sale_method,sp.process_status),
    coalesce(sp.closed_at,sp.launched_at)
  FROM sale_processes sp
  LEFT JOIN classification_summary rcs ON rcs.target_kind='SALE_PROCESS' AND rcs.target_id=sp.sale_process_id
  LEFT JOIN events e ON e.event_id=sp.event_id
  WHERE $2 IN ('ALL','SALE_PROCESS')

  UNION ALL

  SELECT ai.record_kind,ai.record_id,ai.canonical_title,
    concat_ws(' · ','보관 인덱스',ai.lifecycle_status),ai.summary_text,
    coalesce(ai.event_date_start,ai.event_date_end),'ARCHIVED_LOCAL',NULL,
    coalesce(ai.publisher_name,'local full archive'),ai.canonical_url,
    coalesce(rcs.primary_market_category_code,ai.category_code),
    coalesce(rcs.primary_market_category_label,ai.category_code),
    json_patch('{}',json_object(
      'archived',json('true'),'originalStatus',ai.lifecycle_status,
      'archiveLocator',ai.archive_locator,'archiveSnapshotSha256',ai.archive_snapshot_sha256,
      'sourceDocumentId',ai.source_document_id,'sourceDocumentVersionId',ai.source_document_version_id
    )),
    concat_ws(' ',ai.canonical_title,ai.summary_text,ai.publisher_name,ai.category_code,ai.lifecycle_status),
    coalesce(ai.event_date_start,ai.event_date_end)
  FROM archive_rows ai
  LEFT JOIN classification_summary rcs ON rcs.target_kind=ai.record_kind AND rcs.target_id=ai.record_id
  WHERE ai.record_kind IN ('EVENT','DOCUMENT','LP_MANDATE','SALE_PROCESS')
    AND ($2='ALL' OR ai.record_kind=$2)
    AND NOT (
      (ai.record_kind='EVENT' AND EXISTS (SELECT 1 FROM events e WHERE e.event_id=ai.record_id)) OR
      (ai.record_kind='DOCUMENT' AND EXISTS (SELECT 1 FROM source_documents sd WHERE sd.document_id=ai.record_id)) OR
      (ai.record_kind='LP_MANDATE' AND EXISTS (SELECT 1 FROM lp_mandates lm WHERE lm.mandate_id=ai.record_id)) OR
      (ai.record_kind='SALE_PROCESS' AND EXISTS (SELECT 1 FROM sale_processes sp WHERE sp.sale_process_id=ai.record_id))
    )
), scoped AS (
  SELECT * FROM search_index
  WHERE ($1='' OR lower(search_text) LIKE '%' || lower($1) || '%')
    AND ($3 IS NULL OR substr(record_date,1,10)>=$3)
    AND ($4 IS NULL OR substr(record_date,1,10)<=$4)
    AND (
      $7='' OR EXISTS (
        SELECT 1
        FROM record_classifications rc
        JOIN classification_terms ct ON ct.classification_scheme_id=rc.classification_scheme_id
          AND ct.classification_term_id=rc.classification_term_id
        JOIN classification_schemes csc ON csc.classification_scheme_id=rc.classification_scheme_id
        WHERE rc.target_kind=kind AND rc.target_id=id AND ct.term_code=$7
          AND ($9='' OR csc.scheme_code=$9)
          AND rc.review_status='APPROVED' AND rc.assignment_role<>'LEGACY_BACKFILL'
          AND (rc.valid_from IS NULL OR rc.valid_from<=(SELECT now_utc FROM runtime))
          AND (rc.valid_to IS NULL OR rc.valid_to>(SELECT now_utc FROM runtime))
          AND csc.governance_status='ACTIVE' AND ct.governance_status='ACTIVE' AND ct.is_assignable=1
          AND (csc.valid_from IS NULL OR csc.valid_from<=(SELECT now_utc FROM runtime))
          AND (csc.valid_to IS NULL OR csc.valid_to>(SELECT now_utc FROM runtime))
          AND (ct.valid_from IS NULL OR ct.valid_from<=(SELECT now_utc FROM runtime))
          AND (ct.valid_to IS NULL OR ct.valid_to>(SELECT now_utc FROM runtime))
      ) OR ($9='' AND kind='DOCUMENT' AND (category=$7 OR category IN (
        SELECT document_type FROM document_type_groups WHERE group_key=$7
      ))) OR ($9='' AND kind<>'DOCUMENT' AND category=$7)
    )
    AND (
      kind<>'DOCUMENT' OR coalesce(json_extract(metadata,'$.documentType'),'')<>'API_RECORD' OR $8<>0
      OR $9='MARKET_CATEGORY'
      OR CAST(replace(coalesce(json_extract(metadata,'$.apiRecord.dealAmount'),'0'),',','') AS REAL)>=10000000
    )
), facet_rows AS (
  SELECT kind,count(*) AS count FROM scoped GROUP BY kind
), filtered AS (
  SELECT * FROM scoped WHERE $2='ALL' OR kind=$2
), page_base AS (
  SELECT * FROM filtered
  ORDER BY record_date IS NULL,record_date DESC,title,id
  LIMIT $5 OFFSET $6
), page_rows AS (
  SELECT f.*,
    json_patch(COALESCE(f.metadata,'{}'),json_object(
      'documentPurposeCode',rcs.primary_document_purpose_code,
      'documentPurposeLabel',rcs.primary_document_purpose_label,
      'evidenceGradeCode',rcs.primary_evidence_grade_code,
      'evidenceGradeLabel',rcs.primary_evidence_grade_label,
      'classificationCount',rcs.classification_count,
      'evidenceCount',CASE WHEN f.kind='EVENT' THEN (
        SELECT count(DISTINCT relation.document_id)
        FROM v_document_entity_relations relation
        WHERE relation.entity_kind='EVENT' AND relation.entity_id=f.id
          AND relation.relation_basis='CANONICAL_EVENT'
      ) END
    )) AS result_metadata
  FROM page_base f
  LEFT JOIN classification_summary rcs ON rcs.target_kind=f.kind AND rcs.target_id=f.id
)
SELECT json_object(
  'total',(SELECT count(*) FROM filtered),
  'facets',json(COALESCE((SELECT json_group_object(kind,count) FROM facet_rows),'{}')),
  'results',json(COALESCE((SELECT json_group_array(json_object(
    'kind',kind,'id',id,'title',title,'subtitle',subtitle,'summary',summary,
    'date',date,'status',status,'confidence',confidence,'source',source,'href',href,
    'category',category,'categoryLabel',category_label,'metadata',json(result_metadata)
  )) FROM (
    SELECT * FROM page_rows
    ORDER BY record_date IS NULL,record_date DESC,title,id
  )),'[]'))
) AS payload`;

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
  const rawPayload = queryResult.rows[0]?.payload;
  const payload = (typeof rawPayload === "string" ? JSON.parse(rawPayload) : (rawPayload ?? {})) as Payload;
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
