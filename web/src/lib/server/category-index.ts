import type { CategoryIndexGroup, CategoryIndexResponse } from "@/lib/search-contract";

export type CategorySqlExecutor = (
  text: string,
  values: readonly (string | number | null)[],
) => Promise<{ rows: Array<{ payload: unknown }> }>;

const categoryIndexSql = `
WITH event_mention_counts AS (
  SELECT event_category_id, count(*)::int AS item_count
  FROM market_intelligence.event_mentions GROUP BY event_category_id
), event_canonical_counts AS (
  SELECT primary_category_id AS event_category_id, count(*)::int AS canonical_count
  FROM market_intelligence.events GROUP BY primary_category_id
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
), document_items AS (
  SELECT coalesce(document_type, '미분류') AS key,
         coalesce(document_type, '미분류') AS label,
         count(*)::int AS item_count
  FROM market_intelligence.source_documents GROUP BY document_type
), organization_items AS (
  SELECT coalesce(organization_type, '미분류') AS key,
         coalesce(organization_type, '미분류') AS label,
         count(*)::int AS item_count
  FROM market_intelligence.organizations GROUP BY organization_type
), lp_items AS (
  SELECT coalesce(mandate_status, '미분류') AS key,
         coalesce(mandate_status, '미분류') AS label,
         count(*)::int AS item_count
  FROM market_intelligence.lp_mandates GROUP BY mandate_status
), sale_items AS (
  SELECT coalesce(process_status, '미분류') AS key,
         coalesce(process_status, '미분류') AS label,
         count(*)::int AS item_count
  FROM market_intelligence.sale_processes GROUP BY process_status
)
SELECT jsonb_build_object('groups', jsonb_build_array(
  jsonb_build_object('group','EVENT_CATEGORY','label','이벤트 카테고리','kind','EVENT','items',
    (SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'label',label,'itemCount',item_count,'canonicalCount',canonical_count) ORDER BY label), '[]'::jsonb) FROM event_items)),
  jsonb_build_object('group','ASSET_CLASS','label','자산 유형','kind','ASSET','items',
    (SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'label',label,'itemCount',item_count) ORDER BY label), '[]'::jsonb) FROM asset_items)),
  jsonb_build_object('group','DOCUMENT_TYPE','label','문서 유형','kind','DOCUMENT','items',
    (SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'label',label,'itemCount',item_count) ORDER BY item_count DESC, label), '[]'::jsonb) FROM document_items)),
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
