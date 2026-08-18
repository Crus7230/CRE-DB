import type { SqlExecutor } from "@/lib/server/market-search";

export type EntityDetail = {
  kind: "EVENT" | "ASSET";
  id: string;
  title: string;
  subtitle: string | null;
  status: string | null;
  overview: Array<{ label: string; value: string }>;
  assets: Array<{ id: string; title: string; meta: string | null }>;
  events: Array<{ id: string; title: string; meta: string | null }>;
  organizations: Array<{ id: string; title: string; meta: string | null }>;
  documents: Array<{ id: string; title: string; meta: string | null; href: string | null }>;
};

const eventSql = `
SELECT jsonb_build_object(
  'kind','EVENT','id',e.event_id,'title',e.canonical_title,
  'subtitle',concat_ws(' · ',ec.name_ko,e.current_stage_code),'status',e.lifecycle_status,
  'overview',jsonb_build_array(
    jsonb_build_object('label','카테고리','value',coalesce(ec.name_ko,'미분류')),
    jsonb_build_object('label','현재 단계','value',coalesce(e.current_stage_code,'미상')),
    jsonb_build_object('label','이벤트 일자','value',coalesce(e.event_date_start,'미상')),
    jsonb_build_object('label','검증 수준','value',coalesce(e.verification_level,'미상')),
    jsonb_build_object('label','신뢰도','value',coalesce(round(e.overall_confidence::numeric*100)::text || '%','미상'))
  ),
  'assets',coalesce(a.items,'[]'::jsonb),'events','[]'::jsonb,
  'organizations',coalesce(o.items,'[]'::jsonb),'documents',coalesce(d.items,'[]'::jsonb)
) AS payload
FROM market_intelligence.events e
LEFT JOIN market_intelligence.event_categories ec ON ec.event_category_id=e.primary_category_id
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',a.asset_id,'title',a.canonical_name,'meta',concat_ws(' · ',ac.name_ko,ea.role_code)) ORDER BY a.canonical_name) AS items
  FROM market_intelligence.event_assets ea JOIN market_intelligence.assets a ON a.asset_id=ea.asset_id
  LEFT JOIN market_intelligence.asset_classes ac ON ac.asset_class_id=a.asset_class_id WHERE ea.event_id=e.event_id
) a ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',o.organization_id,'title',o.canonical_name,'meta',ep.role_code) ORDER BY o.canonical_name) AS items
  FROM market_intelligence.event_participants ep JOIN market_intelligence.organizations o ON o.organization_id=ep.organization_id WHERE ep.event_id=e.event_id
) o ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',x.document_id,'title',x.title,'meta',concat_ws(' · ',x.publisher_name,x.document_type),'href',x.canonical_url) ORDER BY x.published_at DESC NULLS LAST) AS items
  FROM (
    SELECT DISTINCT ON (sd.document_id) sd.document_id,dv.title,sd.publisher_name,sd.document_type,sd.canonical_url,dv.published_at
    FROM market_intelligence.event_mention_links eml
    JOIN market_intelligence.event_mentions em ON em.event_mention_id=eml.event_mention_id
    JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
    JOIN market_intelligence.source_documents sd ON sd.document_id=dv.document_id
    WHERE eml.event_id=e.event_id ORDER BY sd.document_id,dv.version_no DESC
  ) x
) d ON true
WHERE e.event_id=$1
`;

const assetSql = `
SELECT jsonb_build_object(
  'kind','ASSET','id',a.asset_id,'title',a.canonical_name,
  'subtitle',concat_ws(' · ',ac.name_ko,r.canonical_name),'status',a.status_code,
  'overview',jsonb_build_array(
    jsonb_build_object('label','자산유형','value',coalesce(ac.name_ko,'미분류')),
    jsonb_build_object('label','지역','value',coalesce(r.canonical_name,'미상')),
    jsonb_build_object('label','도로명주소','value',coalesce(a.road_address,'미상')),
    jsonb_build_object('label','지번주소','value',coalesce(a.jibun_address,'미상')),
    jsonb_build_object('label','좌표','value',coalesce(concat_ws(', ',a.latitude::text,a.longitude::text),'미상'))
  ),
  'assets','[]'::jsonb,'events',coalesce(e.items,'[]'::jsonb),
  'organizations',coalesce(o.items,'[]'::jsonb),'documents',coalesce(d.items,'[]'::jsonb)
) AS payload
FROM market_intelligence.assets a
LEFT JOIN market_intelligence.asset_classes ac ON ac.asset_class_id=a.asset_class_id
LEFT JOIN market_intelligence.regions r ON r.region_id=a.region_id
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',e.event_id,'title',e.canonical_title,'meta',concat_ws(' · ',ec.name_ko,e.current_stage_code)) ORDER BY e.event_date_start DESC NULLS LAST) AS items
  FROM market_intelligence.event_assets ea JOIN market_intelligence.events e ON e.event_id=ea.event_id
  LEFT JOIN market_intelligence.event_categories ec ON ec.event_category_id=e.primary_category_id WHERE ea.asset_id=a.asset_id
) e ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',o.organization_id,'title',o.canonical_name,'meta',concat_ws(' · ',op.occupancy_type,op.verification_status)) ORDER BY o.canonical_name) AS items
  FROM market_intelligence.organization_property_occupancies op JOIN market_intelligence.organizations o ON o.organization_id=op.organization_id WHERE op.asset_id=a.asset_id
) o ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',x.document_id,'title',x.title,'meta',concat_ws(' · ',x.publisher_name,x.document_type),'href',x.canonical_url) ORDER BY x.published_at DESC NULLS LAST) AS items
  FROM (
    SELECT DISTINCT ON (sd.document_id) sd.document_id,dv.title,sd.publisher_name,sd.document_type,sd.canonical_url,dv.published_at
    FROM market_intelligence.event_assets ea
    JOIN market_intelligence.event_mention_links eml ON eml.event_id=ea.event_id
    JOIN market_intelligence.event_mentions em ON em.event_mention_id=eml.event_mention_id
    JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
    JOIN market_intelligence.source_documents sd ON sd.document_id=dv.document_id
    WHERE ea.asset_id=a.asset_id ORDER BY sd.document_id,dv.version_no DESC
  ) x
) d ON true
WHERE a.asset_id=$1
`;

export async function getEntityDetail(execute: SqlExecutor, kind: "EVENT" | "ASSET", id: string): Promise<EntityDetail | null> {
  const result = await execute(kind === "EVENT" ? eventSql : assetSql, [id]);
  return (result.rows[0]?.payload as EntityDetail | undefined) ?? null;
}
