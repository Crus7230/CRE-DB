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
  SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now') AS now_utc
)
SELECT json_object(
  'kind','EVENT','id',e.event_id,'title',e.canonical_title,
  'subtitle',concat_ws(' · ',ec.name_ko,e.current_stage_code),'status',e.lifecycle_status,
  'overview',json_array(
    json_object('label','카테고리','value',coalesce(ec.name_ko,'미분류')),
    json_object('label','현재 단계','value',coalesce(e.current_stage_code,'미상')),
    json_object('label','이벤트 일자','value',coalesce(e.event_date_start,'미상')),
    json_object('label','검증 수준','value',coalesce(e.verification_level,'미상')),
    json_object('label','신뢰도','value',CASE WHEN e.overall_confidence IS NULL THEN '미상'
      ELSE printf('%.0f%%',e.overall_confidence*100) END)
  ),
  'assets',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',a.asset_id,'title',a.canonical_name,'meta',concat_ws(' · ',ac.name_ko,ea.role_code)
    ) AS item
    FROM event_assets ea JOIN assets a ON a.asset_id=ea.asset_id
    LEFT JOIN asset_classes ac ON ac.asset_class_id=a.asset_class_id
    WHERE ea.event_id=e.event_id
    ORDER BY a.canonical_name,a.asset_id
  ) ordered_assets),'[]')),
  'events',json('[]'),
  'organizations',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',o.organization_id,'title',o.canonical_name,'meta',ep.role_code
    ) AS item
    FROM event_participants ep JOIN organizations o ON o.organization_id=ep.organization_id
    WHERE ep.event_id=e.event_id
    ORDER BY o.canonical_name,o.organization_id
  ) ordered_organizations),'[]')),
  'projects',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',p.project_id,'title',p.canonical_name,'meta',ep.role_code
    ) AS item
    FROM event_projects ep JOIN projects p ON p.project_id=ep.project_id
    WHERE ep.event_id=e.event_id
    ORDER BY p.canonical_name,p.project_id
  ) ordered_projects),'[]')),
  'capital',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',lm.mandate_id,'title',lm.mandate_name,
      'meta',concat_ws(' · ',lm.mandate_status,lm.evidence_status)
    ) AS item
    FROM lp_mandates lm
    WHERE lm.event_id=e.event_id AND lm.review_status<>'REJECTED'
    ORDER BY lm.announced_at IS NULL,lm.announced_at DESC,lm.mandate_id
  ) ordered_capital),'[]')),
  'processes',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',sp.sale_process_id,'title',sp.process_code,
      'meta',concat_ws(' · ',sp.sale_method,sp.process_status)
    ) AS item
    FROM sale_processes sp
    WHERE sp.event_id=e.event_id AND sp.review_status<>'REJECTED'
    ORDER BY sp.launched_at IS NULL,sp.launched_at DESC,sp.sale_process_id
  ) ordered_processes),'[]')),
  'documents',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',x.document_id,'title',x.title,
      'meta',concat_ws(' · ',x.publisher_name,x.document_type,x.relation_basis,x.evidence_status),
      'href',x.canonical_url
    ) AS item
    FROM (
      SELECT ranked.* FROM (
        SELECT sd.document_id,dv.title,sd.publisher_name,sd.document_type,sd.canonical_url,
               dv.published_at,r.relation_basis,r.evidence_status,
               row_number() OVER (PARTITION BY sd.document_id ORDER BY
                 CASE r.relation_basis WHEN 'CANONICAL_EVENT' THEN 1 WHEN 'RESOLVED_MENTION' THEN 2 ELSE 3 END,
                 dv.version_no DESC,dv.document_version_id DESC) AS item_rank
        FROM v_document_entity_relations r
        JOIN document_versions dv ON dv.document_version_id=r.document_version_id
        JOIN source_documents sd ON sd.document_id=dv.document_id
        WHERE r.entity_kind='EVENT' AND r.entity_id=e.event_id
      ) ranked WHERE item_rank=1
    ) x
    ORDER BY x.published_at IS NULL,x.published_at DESC,x.document_id
  ) ordered_documents),'[]')),
  'classifications',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'schemeCode',s.scheme_code,'schemeLabel',s.scheme_name_ko,
      'termCode',t.term_code,'termLabel',t.term_name_ko,
      'parentCode',parent.term_code,'parentLabel',parent.term_name_ko,
      'isPrimary',json(CASE WHEN rc.is_primary=1 THEN 'true' ELSE 'false' END),
      'assignmentRole',rc.assignment_role,'evidenceStatus',rc.evidence_status,
      'reviewStatus',rc.review_status,'confidence',rc.confidence
    ) AS item
    FROM record_classifications rc
    JOIN classification_schemes s ON s.classification_scheme_id=rc.classification_scheme_id
    JOIN classification_terms t ON t.classification_scheme_id=rc.classification_scheme_id
      AND t.classification_term_id=rc.classification_term_id
    LEFT JOIN classification_terms parent ON parent.classification_scheme_id=t.classification_scheme_id
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
    ORDER BY s.scheme_code,rc.is_primary DESC,t.sort_order,t.term_code,rc.record_classification_id
  ) ordered_classifications),'[]'))
) AS payload
FROM events e
LEFT JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
WHERE e.event_id=$1`;

const assetSql = `
WITH runtime AS (
  SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now') AS now_utc
)
SELECT json_object(
  'kind','ASSET','id',a.asset_id,'title',a.canonical_name,
  'subtitle',concat_ws(' · ',ac.name_ko,r.canonical_name),'status',a.status_code,
  'overview',json_array(
    json_object('label','자산 유형','value',coalesce(ac.name_ko,'미분류')),
    json_object('label','지역','value',coalesce(r.canonical_name,'미상')),
    json_object('label','도로명주소','value',coalesce(a.road_address,'미상')),
    json_object('label','지번주소','value',coalesce(a.jibun_address,'미상')),
    json_object('label','좌표','value',coalesce(concat_ws(', ',a.latitude,a.longitude),'미상'))
  ),
  'assets',json('[]'),
  'events',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',e.event_id,'title',e.canonical_title,'meta',concat_ws(' · ',ec.name_ko,e.current_stage_code)
    ) AS item
    FROM event_assets ea JOIN events e ON e.event_id=ea.event_id
    LEFT JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
    WHERE ea.asset_id=a.asset_id
    ORDER BY e.event_date_start IS NULL,e.event_date_start DESC,e.event_id
  ) ordered_events),'[]')),
  'organizations',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',o.organization_id,'title',o.canonical_name,
      'meta',concat_ws(' · ',op.occupancy_type,op.verification_status)
    ) AS item
    FROM organization_property_occupancies op
    JOIN organizations o ON o.organization_id=op.organization_id
    WHERE op.asset_id=a.asset_id
    ORDER BY o.canonical_name,o.organization_id
  ) ordered_organizations),'[]')),
  'projects',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object('id',x.project_id,'title',x.canonical_name,'meta',x.role_code) AS item
    FROM (
      SELECT DISTINCT p.project_id,p.canonical_name,ep.role_code
      FROM event_assets ea JOIN event_projects ep ON ep.event_id=ea.event_id
      JOIN projects p ON p.project_id=ep.project_id WHERE ea.asset_id=a.asset_id
    ) x
    ORDER BY x.canonical_name,x.project_id,x.role_code
  ) ordered_projects),'[]')),
  'capital',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object('id',x.mandate_id,'title',x.mandate_name,'meta',x.meta) AS item
    FROM (
      SELECT lm.mandate_id,lm.mandate_name,concat_ws(' · ',lm.mandate_status,lm.evidence_status) AS meta
      FROM lp_mandate_deployments md
      JOIN lp_mandate_selections ms ON ms.mandate_selection_id=md.mandate_selection_id
      JOIN lp_mandate_tracks mt ON mt.mandate_track_id=ms.mandate_track_id
      JOIN lp_mandates lm ON lm.mandate_id=mt.mandate_id
      WHERE md.asset_id=a.asset_id AND md.review_status<>'REJECTED'
      UNION
      SELECT lm.mandate_id,lm.mandate_name,concat_ws(' · ',lm.mandate_status,lm.evidence_status)
      FROM event_assets ea JOIN lp_mandates lm ON lm.event_id=ea.event_id
      WHERE ea.asset_id=a.asset_id AND lm.review_status<>'REJECTED'
    ) x
    ORDER BY x.mandate_name,x.mandate_id
  ) ordered_capital),'[]')),
  'processes',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',x.sale_process_id,'title',x.process_code,'meta',concat_ws(' · ',x.sale_method,x.process_status)
    ) AS item
    FROM (
      SELECT DISTINCT sp.sale_process_id,sp.process_code,sp.sale_method,sp.process_status
      FROM event_assets ea JOIN sale_processes sp ON sp.event_id=ea.event_id
      WHERE ea.asset_id=a.asset_id AND sp.review_status<>'REJECTED'
    ) x
    ORDER BY x.process_code,x.sale_process_id
  ) ordered_processes),'[]')),
  'documents',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'id',x.document_id,'title',x.title,
      'meta',concat_ws(' · ',x.publisher_name,x.document_type,x.relation_basis,x.evidence_status),
      'href',x.canonical_url
    ) AS item
    FROM (
      SELECT ranked.* FROM (
        SELECT sd.document_id,dv.title,sd.publisher_name,sd.document_type,sd.canonical_url,
               dv.published_at,r.relation_basis,r.evidence_status,
               row_number() OVER (PARTITION BY sd.document_id ORDER BY
                 CASE r.relation_basis WHEN 'CANONICAL_EVENT' THEN 1 WHEN 'RESOLVED_MENTION' THEN 2 ELSE 3 END,
                 dv.version_no DESC,dv.document_version_id DESC) AS item_rank
        FROM v_document_entity_relations r
        JOIN document_versions dv ON dv.document_version_id=r.document_version_id
        JOIN source_documents sd ON sd.document_id=dv.document_id
        WHERE r.entity_kind='ASSET' AND r.entity_id=a.asset_id
      ) ranked WHERE item_rank=1
    ) x
    ORDER BY x.published_at IS NULL,x.published_at DESC,x.document_id
  ) ordered_documents),'[]')),
  'classifications',json(COALESCE((SELECT json_group_array(json(item)) FROM (
    SELECT json_object(
      'schemeCode',s.scheme_code,'schemeLabel',s.scheme_name_ko,
      'termCode',t.term_code,'termLabel',t.term_name_ko,
      'parentCode',parent.term_code,'parentLabel',parent.term_name_ko,
      'isPrimary',json(CASE WHEN rc.is_primary=1 THEN 'true' ELSE 'false' END),
      'assignmentRole',rc.assignment_role,'evidenceStatus',rc.evidence_status,
      'reviewStatus',rc.review_status,'confidence',rc.confidence
    ) AS item
    FROM record_classifications rc
    JOIN classification_schemes s ON s.classification_scheme_id=rc.classification_scheme_id
    JOIN classification_terms t ON t.classification_scheme_id=rc.classification_scheme_id
      AND t.classification_term_id=rc.classification_term_id
    LEFT JOIN classification_terms parent ON parent.classification_scheme_id=t.classification_scheme_id
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
    ORDER BY s.scheme_code,rc.is_primary DESC,t.sort_order,t.term_code,rc.record_classification_id
  ) ordered_classifications),'[]'))
) AS payload
FROM assets a
LEFT JOIN asset_classes ac ON ac.asset_class_id=a.asset_class_id
LEFT JOIN regions r ON r.region_id=a.region_id
WHERE a.asset_id=$1`;

export async function getEntityDetail(execute: SqlExecutor, kind: "EVENT" | "ASSET", id: string): Promise<EntityDetail | null> {
  const result = await execute(kind === "EVENT" ? eventSql : assetSql, [id]);
  const payload = result.rows[0]?.payload;
  return (typeof payload === "string" ? JSON.parse(payload) : payload) as EntityDetail | null;
}
