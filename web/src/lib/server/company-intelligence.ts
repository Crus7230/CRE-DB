import type { CompanyDetailResponse, CompanyListRequest, CompanyListResponse } from "@/lib/intelligence-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

const companyListSql = `
WITH universe AS (
  SELECT organization_id, organization_name, industry_name, overall_rank, industry_rank,
         market_cap_decimal, universe_code, snapshot_date
  FROM market_intelligence.v_company_universe_current
), selected_universe AS (
  SELECT organization_id, max(organization_name) AS organization_name,
         max(industry_name) AS industry_name,
         min(overall_rank) AS overall_rank, min(industry_rank) AS industry_rank,
         max(market_cap_decimal::numeric) AS market_cap, max(snapshot_date) AS snapshot_date
  FROM universe
  WHERE ($1::text='OVERALL' AND universe_code='KRX_MARKET_CAP_TOP_50')
     OR ($1::text='INDUSTRY' AND universe_code='KRX_INDUSTRY_MARKET_CAP_TOP_10')
     OR ($1::text='TENANT_SIGNALS')
  GROUP BY organization_id
), lease_documents AS (
  SELECT DISTINCT dv.document_id,
         lower(concat_ws(' ', dv.title, dv.snippet_text)) AS haystack
  FROM market_intelligence.event_mentions em
  JOIN market_intelligence.event_categories ec ON ec.event_category_id=em.event_category_id
  JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id
  JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
  WHERE ec.code='LEASE' AND em.status_code<>'REJECTED'
), occupancy_counts AS (
  SELECT organization_id,count(*)::int AS count
  FROM market_intelligence.organization_property_occupancies
  WHERE tenure_type='TENANT' AND review_status='APPROVED'
  GROUP BY organization_id
), event_counts AS (
  SELECT organization_id,count(DISTINCT event_id)::int AS count
  FROM market_intelligence.event_participants GROUP BY organization_id
), asset_counts AS (
  SELECT ep.organization_id,count(DISTINCT ea.asset_id)::int AS count
  FROM market_intelligence.event_participants ep
  JOIN market_intelligence.event_assets ea ON ea.event_id=ep.event_id
  GROUP BY ep.organization_id
), signal_counts AS (
  SELECT u.organization_id,count(DISTINCT ld.document_id)::int AS count
  FROM selected_universe u
  JOIN lease_documents ld ON length(u.organization_name)>=3
   AND strpos(ld.haystack,lower(u.organization_name))>0
  GROUP BY u.organization_id
), company_rows AS (
  SELECT u.organization_id, u.organization_name, o.stock_code, u.industry_name,
         u.market_cap::text AS market_cap_decimal, u.overall_rank, u.industry_rank,
         coalesce(occ.count,0)::int AS confirmed_occupancy_count,
         coalesce(ev.count,0)::int AS canonical_event_count,
         coalesce(ast.count,0)::int AS related_asset_count,
         coalesce(sig.count,0)::int AS lease_document_signal_count,
         u.snapshot_date
  FROM selected_universe u
  JOIN market_intelligence.organizations o ON o.organization_id=u.organization_id
  LEFT JOIN occupancy_counts occ ON occ.organization_id=u.organization_id
  LEFT JOIN event_counts ev ON ev.organization_id=u.organization_id
  LEFT JOIN asset_counts ast ON ast.organization_id=u.organization_id
  LEFT JOIN signal_counts sig ON sig.organization_id=u.organization_id
), filtered AS (
  SELECT * FROM company_rows
  WHERE ($2::text='' OR industry_name=$2)
    AND ($3::text='' OR organization_name ILIKE '%' || $3 || '%' OR coalesce(stock_code,'') ILIKE '%' || $3 || '%')
    AND ($1::text<>'TENANT_SIGNALS' OR confirmed_occupancy_count>0 OR lease_document_signal_count>0)
), industries AS (
  SELECT industry_name AS name, count(DISTINCT organization_id)::int AS count
  FROM universe WHERE universe_code='KRX_INDUSTRY_MARKET_CAP_TOP_10'
  GROUP BY industry_name
)
SELECT jsonb_build_object(
  'snapshotDate',(SELECT max(snapshot_date) FROM universe),
  'items',coalesce((SELECT jsonb_agg(jsonb_build_object(
    'organizationId',organization_id,'name',organization_name,'stockCode',stock_code,
    'industry',industry_name,'marketCap',market_cap_decimal,'overallRank',overall_rank,
    'industryRank',industry_rank,'confirmedOccupancyCount',confirmed_occupancy_count,
    'canonicalEventCount',canonical_event_count,'relatedAssetCount',related_asset_count,
    'leaseDocumentSignalCount',lease_document_signal_count
  ) ORDER BY market_cap_decimal::numeric DESC NULLS LAST, organization_name) FROM (SELECT * FROM filtered LIMIT $4) x),'[]'::jsonb),
  'industries',coalesce((SELECT jsonb_agg(jsonb_build_object('name',name,'count',count) ORDER BY name) FROM industries),'[]'::jsonb),
  'coverage',jsonb_build_object(
    'verifiedOccupancies',(SELECT count(*)::int FROM market_intelligence.organization_property_occupancies WHERE tenure_type='TENANT' AND review_status='APPROVED'),
    'companiesWithLeaseDocumentSignals',(SELECT count(*)::int FROM company_rows WHERE lease_document_signal_count>0),
    'signalNote','LEASE category 문서의 제목·snippet에 회사명이 직접 포함된 discovery signal이며 임차계약 확정값이 아닙니다.'
  )
) AS payload`;

const companyDetailSql = `
WITH target AS (
  SELECT o.organization_id,o.canonical_name,o.organization_type,o.stock_code
  FROM market_intelligence.organizations o WHERE o.organization_id=$1
), universe AS (
  SELECT industry_name,market_cap_decimal,overall_rank
  FROM market_intelligence.v_company_universe_current WHERE organization_id=$1
  ORDER BY overall_rank NULLS LAST,industry_rank NULLS LAST LIMIT 1
), events AS (
  SELECT DISTINCT e.event_id,e.canonical_title AS title,ec.name_ko AS category,
         ep.role_code,e.current_stage_code AS stage,e.event_date_start AS date,
         e.lifecycle_status AS status,e.verification_level AS verification
  FROM market_intelligence.event_participants ep
  JOIN market_intelligence.events e ON e.event_id=ep.event_id
  LEFT JOIN market_intelligence.event_categories ec ON ec.event_category_id=e.primary_category_id
  WHERE ep.organization_id=$1
  ORDER BY e.event_date_start DESC NULLS LAST
), assets AS (
  SELECT DISTINCT a.asset_id,a.canonical_name AS name,ac.name_ko AS asset_class,
         coalesce(a.road_address,a.jibun_address) AS address
  FROM market_intelligence.event_participants ep
  JOIN market_intelligence.event_assets ea ON ea.event_id=ep.event_id
  JOIN market_intelligence.assets a ON a.asset_id=ea.asset_id
  LEFT JOIN market_intelligence.asset_classes ac ON ac.asset_class_id=a.asset_class_id
  WHERE ep.organization_id=$1
  UNION
  SELECT DISTINCT a.asset_id,a.canonical_name,ac.name_ko,coalesce(a.road_address,a.jibun_address)
  FROM market_intelligence.organization_property_occupancies op
  JOIN market_intelligence.assets a ON a.asset_id=op.asset_id
  LEFT JOIN market_intelligence.asset_classes ac ON ac.asset_class_id=a.asset_class_id
  WHERE op.organization_id=$1
), occupancies AS (
  SELECT occupancy_id,occupancy_type,tenure_type,occupancy_status,valid_from,valid_to,
         verification_status,review_status,confidence
  FROM market_intelligence.organization_property_occupancies WHERE organization_id=$1
  ORDER BY valid_from DESC NULLS LAST
), latest_documents AS (
  SELECT DISTINCT ON (document_id) document_id,document_version_id,title,published_at,snippet_text
  FROM market_intelligence.document_versions
  ORDER BY document_id,version_no DESC,document_version_id DESC
), canonical_docs AS (
  SELECT DISTINCT ON (sd.document_id)
         sd.document_id,dv.title,sd.document_type,dv.published_at,sd.publisher_name AS publisher,
         sd.canonical_url AS href,r.relation_basis
  FROM market_intelligence.v_document_entity_relations r
  JOIN market_intelligence.document_versions dv ON dv.document_version_id=r.document_version_id
  JOIN market_intelligence.source_documents sd ON sd.document_id=dv.document_id
  WHERE r.entity_kind='ORGANIZATION' AND r.entity_id=$1
  ORDER BY sd.document_id,
    CASE r.relation_basis WHEN 'CANONICAL_EVENT' THEN 1 WHEN 'RESOLVED_MENTION' THEN 2
         WHEN 'VERIFIED_CLAIM' THEN 3 ELSE 4 END,
    r.confidence DESC NULLS LAST,dv.version_no DESC
), signal_docs AS (
  SELECT sd.document_id,ld.title,sd.document_type,ld.published_at,sd.publisher_name AS publisher,
         sd.canonical_url AS href,'EXACT_NAME_SIGNAL'::text AS relation_basis
  FROM target t CROSS JOIN latest_documents ld
  JOIN market_intelligence.source_documents sd ON sd.document_id=ld.document_id
  WHERE length(t.canonical_name)>=3
    AND strpos(lower(concat_ws(' ',ld.title,ld.snippet_text)),lower(t.canonical_name))>0
    AND NOT EXISTS (SELECT 1 FROM canonical_docs c WHERE c.document_id=sd.document_id)
  ORDER BY ld.published_at DESC NULLS LAST LIMIT 30
), docs AS (
  SELECT * FROM canonical_docs UNION ALL SELECT * FROM signal_docs
)
SELECT jsonb_build_object(
  'organization',(SELECT jsonb_build_object(
    'organizationId',t.organization_id,'name',t.canonical_name,'organizationType',t.organization_type,
    'stockCode',t.stock_code,'industry',u.industry_name,'marketCap',u.market_cap_decimal,'overallRank',u.overall_rank
  ) FROM target t LEFT JOIN universe u ON true),
  'counts',jsonb_build_object('events',(SELECT count(*)::int FROM events),'assets',(SELECT count(*)::int FROM assets),
    'documents',(SELECT count(*)::int FROM docs),'occupancies',(SELECT count(*)::int FROM occupancies)),
  'events',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM events x),'[]'::jsonb),
  'assets',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM assets x),'[]'::jsonb),
  'documents',coalesce((SELECT jsonb_agg(jsonb_build_object(
    'documentId',document_id,'title',title,'documentType',document_type,'publishedAt',published_at,
    'publisher',publisher,'href',href,'relationBasis',relation_basis
  ) ORDER BY published_at DESC NULLS LAST) FROM docs),'[]'::jsonb),
  'occupancies',coalesce((SELECT jsonb_agg(to_jsonb(x)) FROM occupancies x),'[]'::jsonb)
) AS payload`;

export async function getCompanies(execute: SqlExecutor, request: CompanyListRequest): Promise<CompanyListResponse> {
  const query = await execute(companyListSql, [request.view, request.industry, request.q, request.limit]);
  const payload = query.rows[0]?.payload as Omit<CompanyListResponse, "request" | "generatedAt" | "database"> | undefined;
  if (!payload?.items) throw new Error("Invalid company intelligence response");
  return { request, ...payload, generatedAt: new Date().toISOString(), database: "supabase-postgresql" };
}

export async function getCompanyDetail(execute: SqlExecutor, organizationId: string): Promise<CompanyDetailResponse> {
  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(organizationId)) throw new Error("Invalid organization id");
  const query = await execute(companyDetailSql, [organizationId]);
  const payload = query.rows[0]?.payload as Omit<CompanyDetailResponse, "generatedAt" | "database"> | undefined;
  if (!payload?.organization) throw new Error("Company not found");
  return { ...payload, generatedAt: new Date().toISOString(), database: "supabase-postgresql" };
}
