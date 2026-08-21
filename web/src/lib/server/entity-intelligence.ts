import type { SqlExecutor } from "@/lib/server/market-search";
import type { RecordClassification } from "@/lib/search-contract";

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
  projects: Array<{ id: string; title: string; meta: string | null }>;
  capital: Array<{ id: string; title: string; meta: string | null }>;
  processes: Array<{ id: string; title: string; meta: string | null }>;
  documents: Array<{ id: string; title: string; meta: string | null; href: string | null }>;
  classifications: RecordClassification[];
};

const eventSql = `
WITH runtime AS (
  SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS now_utc
)
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
  'organizations',coalesce(o.items,'[]'::jsonb),'projects',coalesce(p.items,'[]'::jsonb),
  'capital',coalesce(cap.items,'[]'::jsonb),'processes',coalesce(proc.items,'[]'::jsonb),
  'documents',coalesce(d.items,'[]'::jsonb),'classifications',coalesce(cls.items,'[]'::jsonb)
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
  SELECT jsonb_agg(jsonb_build_object('id',p.project_id,'title',p.canonical_name,'meta',ep.role_code) ORDER BY p.canonical_name) AS items
  FROM market_intelligence.event_projects ep JOIN market_intelligence.projects p ON p.project_id=ep.project_id WHERE ep.event_id=e.event_id
) p ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',lm.mandate_id,'title',lm.mandate_name,'meta',concat_ws(' · ',lm.mandate_status,lm.evidence_status)) ORDER BY lm.announced_at DESC NULLS LAST) AS items
  FROM market_intelligence.lp_mandates lm WHERE lm.event_id=e.event_id AND lm.review_status<>'REJECTED'
) cap ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',sp.sale_process_id,'title',sp.process_code,'meta',concat_ws(' · ',sp.sale_method,sp.process_status)) ORDER BY sp.launched_at DESC NULLS LAST) AS items
  FROM market_intelligence.sale_processes sp WHERE sp.event_id=e.event_id AND sp.review_status<>'REJECTED'
) proc ON true
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
  WHERE rc.target_kind='EVENT' AND rc.target_id=e.event_id
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
  SELECT jsonb_agg(jsonb_build_object('id',x.document_id,'title',x.title,'meta',concat_ws(' · ',x.publisher_name,x.document_type,x.relation_basis,x.evidence_status),'href',x.canonical_url) ORDER BY x.published_at DESC NULLS LAST) AS items
  FROM (
    SELECT DISTINCT ON (sd.document_id) sd.document_id,dv.title,sd.publisher_name,sd.document_type,sd.canonical_url,dv.published_at,r.relation_basis,r.evidence_status
    FROM market_intelligence.v_document_entity_relations r
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=r.document_version_id
    JOIN market_intelligence.source_documents sd ON sd.document_id=dv.document_id
    WHERE r.entity_kind='EVENT' AND r.entity_id=e.event_id
    ORDER BY sd.document_id,CASE r.relation_basis WHEN 'CANONICAL_EVENT' THEN 1 WHEN 'RESOLVED_MENTION' THEN 2 ELSE 3 END,dv.version_no DESC
  ) x
) d ON true
WHERE e.event_id=$1
`;

const assetSql = `
WITH runtime AS (
  SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS now_utc
)
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
  'organizations',coalesce(o.items,'[]'::jsonb),'projects',coalesce(p.items,'[]'::jsonb),
  'capital',coalesce(cap.items,'[]'::jsonb),'processes',coalesce(proc.items,'[]'::jsonb),
  'documents',coalesce(d.items,'[]'::jsonb),'classifications',coalesce(cls.items,'[]'::jsonb)
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
  SELECT jsonb_agg(DISTINCT jsonb_build_object('id',p.project_id,'title',p.canonical_name,'meta',ep.role_code)) AS items
  FROM market_intelligence.event_assets ea JOIN market_intelligence.event_projects ep ON ep.event_id=ea.event_id
  JOIN market_intelligence.projects p ON p.project_id=ep.project_id WHERE ea.asset_id=a.asset_id
) p ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(DISTINCT jsonb_build_object('id',x.mandate_id,'title',x.mandate_name,'meta',x.meta)) AS items
  FROM (
    SELECT lm.mandate_id,lm.mandate_name,concat_ws(' · ',lm.mandate_status,lm.evidence_status) AS meta
    FROM market_intelligence.lp_mandate_deployments md
    JOIN market_intelligence.lp_mandate_selections ms ON ms.mandate_selection_id=md.mandate_selection_id
    JOIN market_intelligence.lp_mandate_tracks mt ON mt.mandate_track_id=ms.mandate_track_id
    JOIN market_intelligence.lp_mandates lm ON lm.mandate_id=mt.mandate_id
    WHERE md.asset_id=a.asset_id AND md.review_status<>'REJECTED'
    UNION
    SELECT lm.mandate_id,lm.mandate_name,concat_ws(' · ',lm.mandate_status,lm.evidence_status)
    FROM market_intelligence.event_assets ea JOIN market_intelligence.lp_mandates lm ON lm.event_id=ea.event_id
    WHERE ea.asset_id=a.asset_id AND lm.review_status<>'REJECTED'
  ) x
) cap ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(DISTINCT jsonb_build_object('id',sp.sale_process_id,'title',sp.process_code,'meta',concat_ws(' · ',sp.sale_method,sp.process_status))) AS items
  FROM market_intelligence.event_assets ea JOIN market_intelligence.sale_processes sp ON sp.event_id=ea.event_id
  WHERE ea.asset_id=a.asset_id AND sp.review_status<>'REJECTED'
) proc ON true
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
  WHERE rc.target_kind='ASSET' AND rc.target_id=a.asset_id
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
  SELECT jsonb_agg(jsonb_build_object('id',x.document_id,'title',x.title,'meta',concat_ws(' · ',x.publisher_name,x.document_type,x.relation_basis,x.evidence_status),'href',x.canonical_url) ORDER BY x.published_at DESC NULLS LAST) AS items
  FROM (
    SELECT DISTINCT ON (sd.document_id) sd.document_id,dv.title,sd.publisher_name,sd.document_type,sd.canonical_url,dv.published_at,r.relation_basis,r.evidence_status
    FROM market_intelligence.v_document_entity_relations r
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=r.document_version_id
    JOIN market_intelligence.source_documents sd ON sd.document_id=dv.document_id
    WHERE r.entity_kind='ASSET' AND r.entity_id=a.asset_id
    ORDER BY sd.document_id,CASE r.relation_basis WHEN 'CANONICAL_EVENT' THEN 1 WHEN 'RESOLVED_MENTION' THEN 2 ELSE 3 END,dv.version_no DESC
  ) x
) d ON true
WHERE a.asset_id=$1
`;

export async function getEntityDetail(execute: SqlExecutor, kind: "EVENT" | "ASSET", id: string): Promise<EntityDetail | null> {
  const result = await execute(kind === "EVENT" ? eventSql : assetSql, [id]);
  return (result.rows[0]?.payload as EntityDetail | undefined) ?? null;
}
