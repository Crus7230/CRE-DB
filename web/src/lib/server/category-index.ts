import type { CategoryIndexGroup, CategoryIndexResponse } from "@/lib/search-contract";

export type CategorySqlExecutor = (
  text: string,
  values: readonly (string | number | null)[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

const categoryIndexSql = `
WITH runtime AS (
  SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS now_utc
), document_type_groups(group_key, group_label, document_type, sort_order) AS (
  VALUES
    ('TRANSACTION_EVIDENCE', '거래·가격 근거', 'API_RECORD', 1),
    ('CORPORATE_EVIDENCE', '기업·사업 근거', 'DISCLOSURE', 2),
    ('CORPORATE_EVIDENCE', '기업·사업 근거', 'OFFICIAL_FILING', 2),
    ('CORPORATE_EVIDENCE', '기업·사업 근거', 'PRESS_RELEASE', 2),
    ('MARKET_EVIDENCE', '시장동향 근거', 'RSS_ITEM', 3),
    ('MARKET_EVIDENCE', '시장동향 근거', 'ARTICLE', 3),
    ('MARKET_EVIDENCE', '시장동향 근거', 'RESEARCH_REPORT', 3),
    ('PROCESS_EVIDENCE', '절차·공고 근거', 'BID_NOTICE', 4),
    ('PROCESS_EVIDENCE', '절차·공고 근거', 'NOTICE', 4)
), archive_rows AS (
  SELECT asi.*
  FROM market_intelligence.archived_serving_index asi
  JOIN market_intelligence.archive_snapshots ars
    ON ars.archive_snapshot_id=asi.archive_snapshot_id
   AND ars.is_current=1 AND ars.integrity_status='VALIDATED'
), latest_document_versions AS (
  SELECT DISTINCT ON (document_id) document_id, document_version_id
  FROM market_intelligence.document_versions
  ORDER BY document_id, version_no DESC, document_version_id DESC
), current_cre_scope AS (
  SELECT document_version_id, classifier_version, status_code
  FROM market_intelligence.document_scope_assessments
  WHERE scope_code='CRE' AND classifier_version IN (
    'DART_CRE_SCOPE_RULE_V1','NEWS_CRE_SCOPE_RULE_V1','MOLIT_SCOPE_TIERED_V2'
  )
), serving_targets AS (
  SELECT 'EVENT'::text AS target_kind,e.event_id AS target_id FROM market_intelligence.events e
  UNION SELECT 'ASSET',a.asset_id FROM market_intelligence.assets a
  UNION SELECT 'ORGANIZATION',o.organization_id
    FROM market_intelligence.organizations o
    JOIN market_intelligence.organization_scope_assessments osa
      ON osa.organization_id=o.organization_id
     AND osa.scope_code='CRE' AND osa.classifier_version='ORG_CRE_SCOPE_RULE_V1'
     AND osa.status_code='CRE_CONFIRMED'
  UNION SELECT 'DOCUMENT',sd.document_id
    FROM market_intelligence.source_documents sd
    LEFT JOIN market_intelligence.collection_sources cs ON cs.source_id=sd.source_id
    LEFT JOIN latest_document_versions ldv ON ldv.document_id=sd.document_id
    LEFT JOIN current_cre_scope dsa ON dsa.document_version_id=ldv.document_version_id
      AND dsa.classifier_version=CASE cs.source_code
        WHEN 'OPENDART' THEN 'DART_CRE_SCOPE_RULE_V1'
        WHEN 'GOOGLE_NEWS_RSS' THEN 'NEWS_CRE_SCOPE_RULE_V1'
        WHEN 'MOLIT_REAL_TRANSACTION' THEN 'MOLIT_SCOPE_TIERED_V2'
      END
    WHERE cs.source_code IS NULL
       OR cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION')
       OR dsa.status_code='CRE_CONFIRMED'
  UNION SELECT 'LP_MANDATE',m.mandate_id FROM market_intelligence.lp_mandates m
  UNION SELECT 'SALE_PROCESS',s.sale_process_id FROM market_intelligence.sale_processes s
  UNION SELECT ar.record_kind,ar.record_id FROM archive_rows ar
    WHERE (ar.record_kind='EVENT' AND NOT EXISTS (SELECT 1 FROM market_intelligence.events e WHERE e.event_id=ar.record_id))
       OR (ar.record_kind='DOCUMENT' AND NOT EXISTS (SELECT 1 FROM market_intelligence.source_documents sd WHERE sd.document_id=ar.record_id))
       OR (ar.record_kind='LP_MANDATE' AND NOT EXISTS (SELECT 1 FROM market_intelligence.lp_mandates m WHERE m.mandate_id=ar.record_id))
       OR (ar.record_kind='SALE_PROCESS' AND NOT EXISTS (SELECT 1 FROM market_intelligence.sale_processes s WHERE s.sale_process_id=ar.record_id))
), taxonomy_groups AS (
  SELECT s.classification_scheme_id,s.scheme_code,s.scheme_name_ko,
         s.target_kinds_json::jsonb AS target_kinds,s.vocabulary_version
  FROM market_intelligence.classification_schemes s
  CROSS JOIN runtime rt
  WHERE s.scheme_code IN ('MARKET_CATEGORY','DOCUMENT_PURPOSE','ASSET_CLASS','EVIDENCE_GRADE')
    AND s.governance_status='ACTIVE'
    AND (s.valid_from IS NULL OR s.valid_from<=rt.now_utc)
    AND (s.valid_to IS NULL OR s.valid_to>rt.now_utc)
), taxonomy_counts AS (
  SELECT rc.classification_scheme_id,rc.classification_term_id,rc.target_kind,
         count(DISTINCT rc.target_id)::int AS item_count
  FROM market_intelligence.record_classifications rc
  JOIN serving_targets st ON st.target_kind=rc.target_kind AND st.target_id=rc.target_id
  JOIN taxonomy_groups tg ON tg.classification_scheme_id=rc.classification_scheme_id
  CROSS JOIN runtime rt
  WHERE rc.review_status NOT IN ('REJECTED','SUPERSEDED')
    AND (rc.valid_from IS NULL OR rc.valid_from<=rt.now_utc)
    AND (rc.valid_to IS NULL OR rc.valid_to>rt.now_utc)
  GROUP BY rc.classification_scheme_id,rc.classification_term_id,rc.target_kind
), taxonomy_items AS (
  SELECT tg.scheme_code AS group_key,tg.scheme_name_ko AS group_label,
         tg.target_kinds,tg.vocabulary_version,
         t.term_code AS key,t.term_name_ko AS label,
         parent.term_code AS parent_key,parent.term_name_ko AS parent_label,t.sort_order,
         coalesce(sum(tc.item_count),0)::int AS item_count,
         coalesce(
           jsonb_object_agg(tc.target_kind,tc.item_count ORDER BY tc.target_kind)
             FILTER (WHERE tc.target_kind IS NOT NULL),
           '{}'::jsonb
         ) AS counts_by_kind
  FROM taxonomy_groups tg
  JOIN market_intelligence.classification_terms t
    ON t.classification_scheme_id=tg.classification_scheme_id
  LEFT JOIN market_intelligence.classification_terms parent
    ON parent.classification_scheme_id=t.classification_scheme_id
   AND parent.classification_term_id=t.parent_term_id
  LEFT JOIN taxonomy_counts tc
    ON tc.classification_scheme_id=t.classification_scheme_id
   AND tc.classification_term_id=t.classification_term_id
  CROSS JOIN runtime rt
  WHERE t.governance_status='ACTIVE' AND t.is_assignable=1
    AND (t.valid_from IS NULL OR t.valid_from<=rt.now_utc)
    AND (t.valid_to IS NULL OR t.valid_to>rt.now_utc)
  GROUP BY tg.scheme_code,tg.scheme_name_ko,tg.target_kinds,tg.vocabulary_version,
           t.term_code,t.term_name_ko,parent.term_code,parent.term_name_ko,t.sort_order
), event_mention_counts AS (
  SELECT event_category_id, count(*)::int AS item_count
  FROM market_intelligence.event_mentions GROUP BY event_category_id
), event_canonical_counts AS (
  SELECT ec.event_category_id, count(*)::int AS canonical_count
  FROM market_intelligence.event_categories ec
  JOIN (
    SELECT e.primary_category_id AS event_category_id
    FROM market_intelligence.events e
    UNION ALL
    SELECT ec2.event_category_id
    FROM archive_rows ar JOIN market_intelligence.event_categories ec2 ON ec2.code=ar.category_code
    WHERE ar.record_kind='EVENT'
      AND NOT EXISTS (SELECT 1 FROM market_intelligence.events e WHERE e.event_id=ar.record_id)
  ) x ON x.event_category_id=ec.event_category_id
  GROUP BY ec.event_category_id
), event_items AS (
  SELECT ec.code AS key, ec.name_ko AS label,
         coalesce(em.item_count, 0)::int AS item_count,
         coalesce(e.canonical_count, 0)::int AS canonical_count
  FROM market_intelligence.event_categories ec
  LEFT JOIN event_mention_counts em ON em.event_category_id = ec.event_category_id
  LEFT JOIN event_canonical_counts e ON e.event_category_id = ec.event_category_id
), asset_items AS (
  SELECT ac.code AS key, ac.name_ko AS label, count(a.asset_id)::int AS item_count
  FROM market_intelligence.asset_classes ac
  LEFT JOIN market_intelligence.assets a ON a.asset_class_id = ac.asset_class_id
  GROUP BY ac.code, ac.name_ko
), live_document_items AS (
  SELECT dtg.group_key AS key, dtg.group_label AS label,
         count(sd.document_id)::int AS item_count,
         min(dtg.sort_order)::int AS sort_order
  FROM document_type_groups dtg
  LEFT JOIN market_intelligence.source_documents sd ON sd.document_type=dtg.document_type
  LEFT JOIN market_intelligence.collection_sources cs ON cs.source_id=sd.source_id
  LEFT JOIN latest_document_versions ldv ON ldv.document_id=sd.document_id
  LEFT JOIN current_cre_scope dsa ON dsa.document_version_id=ldv.document_version_id
    AND dsa.classifier_version=CASE cs.source_code
      WHEN 'OPENDART' THEN 'DART_CRE_SCOPE_RULE_V1'
      WHEN 'GOOGLE_NEWS_RSS' THEN 'NEWS_CRE_SCOPE_RULE_V1'
      WHEN 'MOLIT_REAL_TRANSACTION' THEN 'MOLIT_SCOPE_TIERED_V2'
    END
  WHERE (
       sd.document_id IS NULL OR cs.source_code IS NULL
       OR cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION')
       OR dsa.status_code='CRE_CONFIRMED'
  )
  GROUP BY dtg.group_key, dtg.group_label
), archived_document_items AS (
  SELECT dtg.group_key AS key, count(*)::int AS item_count
  FROM archive_rows ar
  JOIN document_type_groups dtg ON dtg.document_type=(ar.metadata_json::jsonb)->>'documentType'
  WHERE ar.record_kind='DOCUMENT'
    AND NOT EXISTS (SELECT 1 FROM market_intelligence.source_documents sd WHERE sd.document_id=ar.record_id)
  GROUP BY dtg.group_key
), document_items AS (
  SELECT l.key,l.label,(l.item_count+coalesce(a.item_count,0))::int AS item_count,l.sort_order
  FROM live_document_items l LEFT JOIN archived_document_items a ON a.key=l.key
), organization_items AS (
  SELECT coalesce(organization_type, '미분류') AS key,
         coalesce(organization_type, '미분류') AS label,
         count(*)::int AS item_count
  FROM market_intelligence.organizations o
  JOIN market_intelligence.organization_scope_assessments osa
    ON osa.organization_id=o.organization_id
   AND osa.scope_code='CRE'
   AND osa.classifier_version='ORG_CRE_SCOPE_RULE_V1'
   AND osa.status_code='CRE_CONFIRMED'
  GROUP BY o.organization_type
), lp_items AS (
  SELECT key,key AS label,count(*)::int AS item_count FROM (
    SELECT coalesce(m.mandate_status,'미분류') AS key FROM market_intelligence.lp_mandates m
    UNION ALL SELECT coalesce(ar.lifecycle_status,'미분류') FROM archive_rows ar
    WHERE ar.record_kind='LP_MANDATE'
      AND NOT EXISTS (SELECT 1 FROM market_intelligence.lp_mandates m WHERE m.mandate_id=ar.record_id)
  ) x GROUP BY key
), sale_items AS (
  SELECT key,key AS label,count(*)::int AS item_count FROM (
    SELECT coalesce(s.process_status,'미분류') AS key FROM market_intelligence.sale_processes s
    UNION ALL SELECT coalesce(ar.lifecycle_status,'미분류') FROM archive_rows ar
    WHERE ar.record_kind='SALE_PROCESS'
      AND NOT EXISTS (SELECT 1 FROM market_intelligence.sale_processes s WHERE s.sale_process_id=ar.record_id)
  ) x GROUP BY key
)
SELECT jsonb_build_object('groups', jsonb_build_array(
  jsonb_build_object(
    'group','MARKET_CATEGORY','classificationScheme','MARKET_CATEGORY',
    'label',(SELECT scheme_name_ko FROM taxonomy_groups WHERE scheme_code='MARKET_CATEGORY'),
    'kind','ALL','targetKinds',coalesce((SELECT target_kinds FROM taxonomy_groups WHERE scheme_code='MARKET_CATEGORY'),'[]'::jsonb),
    'countSemantics','SERVING_TARGETS','vocabularyVersion',(SELECT vocabulary_version FROM taxonomy_groups WHERE scheme_code='MARKET_CATEGORY'),
    'items',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'key',key,'label',label,'itemCount',item_count,'parentKey',parent_key,
      'parentLabel',parent_label,'countsByKind',counts_by_kind
    ) ORDER BY sort_order,label), '[]'::jsonb) FROM taxonomy_items WHERE group_key='MARKET_CATEGORY')
  ),
  jsonb_build_object(
    'group','DOCUMENT_PURPOSE','classificationScheme','DOCUMENT_PURPOSE',
    'label',(SELECT scheme_name_ko FROM taxonomy_groups WHERE scheme_code='DOCUMENT_PURPOSE'),
    'kind','DOCUMENT','targetKinds',coalesce((SELECT target_kinds FROM taxonomy_groups WHERE scheme_code='DOCUMENT_PURPOSE'),'[]'::jsonb),
    'countSemantics','SERVING_TARGETS','vocabularyVersion',(SELECT vocabulary_version FROM taxonomy_groups WHERE scheme_code='DOCUMENT_PURPOSE'),
    'items',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'key',key,'label',label,'itemCount',item_count,'parentKey',parent_key,
      'parentLabel',parent_label,'countsByKind',counts_by_kind
    ) ORDER BY sort_order,label), '[]'::jsonb) FROM taxonomy_items WHERE group_key='DOCUMENT_PURPOSE')
  ),
  jsonb_build_object(
    'group','ASSET_CLASS','classificationScheme','ASSET_CLASS',
    'label',(SELECT scheme_name_ko FROM taxonomy_groups WHERE scheme_code='ASSET_CLASS'),
    'kind','ASSET','targetKinds',coalesce((SELECT target_kinds FROM taxonomy_groups WHERE scheme_code='ASSET_CLASS'),'[]'::jsonb),
    'countSemantics','SERVING_TARGETS','vocabularyVersion',(SELECT vocabulary_version FROM taxonomy_groups WHERE scheme_code='ASSET_CLASS'),
    'items',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'key',key,'label',label,'itemCount',item_count,'parentKey',parent_key,
      'parentLabel',parent_label,'countsByKind',counts_by_kind
    ) ORDER BY sort_order,label), '[]'::jsonb) FROM taxonomy_items WHERE group_key='ASSET_CLASS')
  ),
  jsonb_build_object(
    'group','EVIDENCE_GRADE','classificationScheme','EVIDENCE_GRADE',
    'label',(SELECT scheme_name_ko FROM taxonomy_groups WHERE scheme_code='EVIDENCE_GRADE'),
    'kind','ALL','targetKinds',coalesce((SELECT target_kinds FROM taxonomy_groups WHERE scheme_code='EVIDENCE_GRADE'),'[]'::jsonb),
    'countSemantics','SERVING_TARGETS','vocabularyVersion',(SELECT vocabulary_version FROM taxonomy_groups WHERE scheme_code='EVIDENCE_GRADE'),
    'items',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'key',key,'label',label,'itemCount',item_count,'parentKey',parent_key,
      'parentLabel',parent_label,'countsByKind',counts_by_kind
    ) ORDER BY sort_order,label), '[]'::jsonb) FROM taxonomy_items WHERE group_key='EVIDENCE_GRADE')
  ),
  jsonb_build_object('group','EVENT_CATEGORY','label','이벤트 카테고리','kind','EVENT','items',
    (SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'label',label,'itemCount',item_count,'canonicalCount',canonical_count) ORDER BY label), '[]'::jsonb) FROM event_items)),
  jsonb_build_object('group','DOCUMENT_TYPE','label','근거 목적','kind','DOCUMENT','items',
    (SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'label',label,'itemCount',item_count) ORDER BY sort_order), '[]'::jsonb) FROM document_items)),
  jsonb_build_object('group','ORGANIZATION_TYPE','label','기관 유형','kind','ORGANIZATION','items',
    (SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'label',label,'itemCount',item_count) ORDER BY item_count DESC, label), '[]'::jsonb) FROM organization_items)),
  jsonb_build_object('group','LP_STATUS','label','LP Mandate 상태','kind','LP_MANDATE','items',
    (SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'label',label,'itemCount',item_count) ORDER BY item_count DESC, label), '[]'::jsonb) FROM lp_items)),
  jsonb_build_object('group','SALE_STATUS','label','매각 절차 상태','kind','SALE_PROCESS','items',
    (SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'label',label,'itemCount',item_count) ORDER BY item_count DESC, label), '[]'::jsonb) FROM sale_items))
)) AS payload`;

export async function getCategoryIndex(execute: CategorySqlExecutor): Promise<CategoryIndexResponse> {
  const started = performance.now();
  const query = await execute(categoryIndexSql, []);
  const payload = query.rows[0]?.payload as { groups?: CategoryIndexGroup[] } | undefined;
  if (!payload?.groups) throw new Error("Invalid category index response");
  return {
    groups: payload.groups,
    generatedAt: new Date().toISOString(),
    elapsedMs: Math.round(performance.now() - started),
    database: "supabase-postgresql",
  };
}
