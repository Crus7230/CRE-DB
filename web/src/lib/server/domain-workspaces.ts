import type { InstitutionalCapitalResponse, SaleProcessResponse } from "@/lib/intelligence-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

const capitalSql = `
WITH latest_documents AS (
  SELECT DISTINCT ON (document_id) document_id,document_version_id,title,published_at
  FROM market_intelligence.document_versions
  ORDER BY document_id,version_no DESC,document_version_id DESC
), mandate_rows AS (
  SELECT m.mandate_id,m.mandate_name,lp.canonical_name AS lp_name,m.mandate_status,m.mandate_scope,
         m.announced_at,m.selected_at,m.evidence_status,
         (SELECT count(*)::int FROM market_intelligence.lp_mandate_tracks t WHERE t.mandate_id=m.mandate_id) AS track_count,
         (SELECT count(*)::int FROM market_intelligence.lp_mandate_selections s JOIN market_intelligence.lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id WHERE t.mandate_id=m.mandate_id) AS selection_count,
         (SELECT count(*)::int FROM market_intelligence.lp_mandate_amounts a LEFT JOIN market_intelligence.lp_mandate_tracks t ON t.mandate_track_id=a.mandate_track_id LEFT JOIN market_intelligence.lp_mandate_selections s ON s.mandate_selection_id=a.mandate_selection_id LEFT JOIN market_intelligence.lp_mandate_tracks st ON st.mandate_track_id=s.mandate_track_id WHERE coalesce(a.mandate_id,t.mandate_id,st.mandate_id)=m.mandate_id AND a.is_current=1) AS amount_count,
         (SELECT count(*)::int FROM market_intelligence.lp_mandate_guidelines g JOIN market_intelligence.lp_mandate_tracks t ON t.mandate_track_id=g.mandate_track_id WHERE t.mandate_id=m.mandate_id) AS guideline_count,
         (SELECT count(*)::int FROM market_intelligence.lp_mandate_deployments d JOIN market_intelligence.lp_mandate_selections s ON s.mandate_selection_id=d.mandate_selection_id JOIN market_intelligence.lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id WHERE t.mandate_id=m.mandate_id AND d.is_current=1) AS deployment_count,
         coalesce((SELECT jsonb_agg(jsonb_build_object(
           'trackId',t.mandate_track_id,'code',t.track_code,'name',t.track_name,'strategy',t.strategy_code,
           'geography',t.geography_code,'targetManagerCount',t.target_manager_count,'evidenceStatus',t.evidence_status,
           'guidelines',(SELECT coalesce(jsonb_agg(jsonb_build_object('termType',g.term_type,'requirement',g.requirement_level,'rawText',g.raw_text,'value',coalesce(g.text_value,g.value_decimal_text),'unit',g.unit_code,'returnBasis',g.return_basis) ORDER BY g.term_type),'[]'::jsonb) FROM market_intelligence.lp_mandate_guidelines g WHERE g.mandate_track_id=t.mandate_track_id)
         ) ORDER BY t.track_code) FROM market_intelligence.lp_mandate_tracks t WHERE t.mandate_id=m.mandate_id),'[]'::jsonb) AS tracks,
         coalesce((SELECT jsonb_agg(jsonb_build_object(
           'amountId',a.mandate_amount_id,'basis',a.amount_basis,'amount',a.amount_decimal,
           'lowerAmount',a.lower_amount_decimal,'upperAmount',a.upper_amount_decimal,'currency',a.currency_code,
           'comparator',a.comparator_code,'status',a.amount_status,'rawValue',a.raw_value,'evidenceStatus',a.evidence_status
         ) ORDER BY a.amount_basis) FROM market_intelligence.lp_mandate_amounts a LEFT JOIN market_intelligence.lp_mandate_tracks t ON t.mandate_track_id=a.mandate_track_id LEFT JOIN market_intelligence.lp_mandate_selections s ON s.mandate_selection_id=a.mandate_selection_id LEFT JOIN market_intelligence.lp_mandate_tracks st ON st.mandate_track_id=s.mandate_track_id WHERE coalesce(a.mandate_id,t.mandate_id,st.mandate_id)=m.mandate_id AND a.is_current=1),'[]'::jsonb) AS amounts,
         coalesce((SELECT jsonb_agg(jsonb_build_object(
           'selectionId',s.mandate_selection_id,'managerId',o.organization_id,'managerName',o.canonical_name,
           'status',s.selection_status,'selectedAt',s.selected_at,'rank',s.rank_no,'evidenceStatus',s.evidence_status,'confidence',s.confidence
         ) ORDER BY s.selected_at,o.canonical_name) FROM market_intelligence.lp_mandate_selections s JOIN market_intelligence.lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id JOIN market_intelligence.organizations o ON o.organization_id=s.manager_organization_id WHERE t.mandate_id=m.mandate_id),'[]'::jsonb) AS selections,
         coalesce((SELECT jsonb_agg(DISTINCT jsonb_build_object(
           'documentId',sd.document_id,'title',ld.title,'documentType',sd.document_type,
           'publishedAt',ld.published_at,'publisher',sd.publisher_name,'href',sd.canonical_url,'relationBasis','CANONICAL_EVENT'
         )) FROM market_intelligence.event_mention_links eml JOIN market_intelligence.event_mentions em ON em.event_mention_id=eml.event_mention_id JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id JOIN latest_documents ld ON ld.document_version_id=er.document_version_id JOIN market_intelligence.source_documents sd ON sd.document_id=ld.document_id WHERE eml.event_id=m.event_id),'[]'::jsonb) AS documents
  FROM market_intelligence.lp_mandates m
  JOIN market_intelligence.organizations lp ON lp.organization_id=m.lp_organization_id
)
SELECT jsonb_build_object(
 'items',coalesce((SELECT jsonb_agg(jsonb_build_object(
   'mandateId',mandate_id,'mandateName',mandate_name,'lpName',lp_name,'status',mandate_status,'scope',mandate_scope,
   'announcedAt',announced_at,'selectedAt',selected_at,'evidenceStatus',evidence_status,'trackCount',track_count,
   'selectionCount',selection_count,'amountCount',amount_count,'guidelineCount',guideline_count,'deploymentCount',deployment_count,
   'tracks',tracks,'amounts',amounts,'selections',selections,'documents',documents
 ) ORDER BY coalesce(selected_at,announced_at) DESC NULLS LAST,lp_name) FROM mandate_rows),'[]'::jsonb),
 'coverage',jsonb_build_object(
   'mandates',(SELECT count(*)::int FROM market_intelligence.lp_mandates),
   'selections',(SELECT count(*)::int FROM market_intelligence.lp_mandate_selections),
   'amounts',(SELECT count(*)::int FROM market_intelligence.lp_mandate_amounts WHERE is_current=1),
   'deployments',(SELECT count(*)::int FROM market_intelligence.lp_mandate_deployments WHERE is_current=1)
 )) AS payload`;

const saleSql = `
WITH latest_documents AS (
  SELECT DISTINCT ON (document_id) document_id,document_version_id,title,published_at
  FROM market_intelligence.document_versions
  ORDER BY document_id,version_no DESC,document_version_id DESC
), process_rows AS (
 SELECT sp.sale_process_id,sp.process_code,e.canonical_title AS title,sp.process_status,sp.sale_method,
        sp.launched_at,sp.closed_at,sp.evidence_status,
        coalesce((SELECT jsonb_agg(jsonb_build_object('assetId',a.asset_id,'name',a.canonical_name,'address',coalesce(a.road_address,a.jibun_address)) ORDER BY a.canonical_name) FROM market_intelligence.event_assets ea JOIN market_intelligence.assets a ON a.asset_id=ea.asset_id WHERE ea.event_id=sp.event_id),'[]'::jsonb) AS assets,
        coalesce((SELECT jsonb_agg(jsonb_build_object(
          'roundId',r.bid_round_id,'roundNo',r.round_no,'roundCode',r.round_code,'roundType',r.round_type,
          'deadlineAt',r.deadline_at,'status',r.round_status,'evidenceStatus',r.evidence_status,
          'bidders',(SELECT coalesce(jsonb_agg(jsonb_build_object('organizationId',o.organization_id,'name',o.canonical_name,'status',p.participation_status,'confidence',p.confidence) ORDER BY o.canonical_name),'[]'::jsonb) FROM market_intelligence.bidder_participations p JOIN market_intelligence.organizations o ON o.organization_id=p.bidder_organization_id WHERE p.bid_round_id=r.bid_round_id),
          'submissions',(SELECT coalesce(jsonb_agg(jsonb_build_object('submissionId',s.bid_submission_id,'amount',s.bid_amount_decimal,'currency',s.currency_code,'priceBasis',s.price_basis,'rank',s.reported_rank,'confidence',s.confidence)),'[]'::jsonb) FROM market_intelligence.bid_submissions s JOIN market_intelligence.bidder_participations p ON p.participation_id=s.participation_id WHERE p.bid_round_id=r.bid_round_id),
          'decisions',(SELECT coalesce(jsonb_agg(jsonb_build_object('type',d.decision_type,'date',d.decision_date,'status',d.decision_status,'reason',d.source_reason,'confidence',d.confidence)),'[]'::jsonb) FROM market_intelligence.bid_decisions d WHERE d.bid_round_id=r.bid_round_id)
        ) ORDER BY r.round_no) FROM market_intelligence.bid_rounds r WHERE r.sale_process_id=sp.sale_process_id),'[]'::jsonb) AS rounds,
        coalesce((SELECT jsonb_agg(jsonb_build_object('code',tm.milestone_code,'status',tm.milestone_status,'announcedAt',tm.announced_at,'effectiveDate',tm.effective_date,'expectedDate',tm.expected_date,'note',tm.source_note,'evidenceStatus',tm.evidence_status) ORDER BY coalesce(tm.effective_date,tm.announced_at,tm.expected_date)) FROM market_intelligence.transaction_milestones tm WHERE tm.sale_process_id=sp.sale_process_id),'[]'::jsonb) AS milestones,
        coalesce((SELECT jsonb_agg(jsonb_build_object('type',fc.funding_type,'provider',o.canonical_name,'amount',fc.amount_decimal,'currency',fc.currency_code,'status',fc.commitment_status,'evidenceStatus',fc.evidence_status,'confidence',fc.confidence)) FROM market_intelligence.bid_funding_components fc JOIN market_intelligence.bid_submissions bs ON bs.bid_submission_id=fc.bid_submission_id JOIN market_intelligence.bidder_participations bp ON bp.participation_id=bs.participation_id JOIN market_intelligence.bid_rounds br ON br.bid_round_id=bp.bid_round_id LEFT JOIN market_intelligence.organizations o ON o.organization_id=fc.provider_organization_id WHERE br.sale_process_id=sp.sale_process_id),'[]'::jsonb) AS funding,
        coalesce((SELECT jsonb_agg(DISTINCT jsonb_build_object('documentId',sd.document_id,'title',ld.title,'documentType',sd.document_type,'publishedAt',ld.published_at,'publisher',sd.publisher_name,'href',sd.canonical_url,'relationBasis','CANONICAL_EVENT')) FROM market_intelligence.event_mention_links eml JOIN market_intelligence.event_mentions em ON em.event_mention_id=eml.event_mention_id JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id JOIN latest_documents ld ON ld.document_version_id=er.document_version_id JOIN market_intelligence.source_documents sd ON sd.document_id=ld.document_id WHERE eml.event_id=sp.event_id),'[]'::jsonb) AS documents
 FROM market_intelligence.sale_processes sp JOIN market_intelligence.events e ON e.event_id=sp.event_id
)
SELECT jsonb_build_object(
 'items',coalesce((SELECT jsonb_agg(jsonb_build_object('saleProcessId',sale_process_id,'processCode',process_code,'title',title,'status',process_status,'saleMethod',sale_method,'launchedAt',launched_at,'closedAt',closed_at,'evidenceStatus',evidence_status,'assets',assets,'rounds',rounds,'milestones',milestones,'funding',funding,'documents',documents) ORDER BY coalesce(closed_at,launched_at) DESC NULLS LAST,title) FROM process_rows),'[]'::jsonb),
 'coverage',jsonb_build_object(
  'processes',(SELECT count(*)::int FROM market_intelligence.sale_processes),
  'rounds',(SELECT count(*)::int FROM market_intelligence.bid_rounds),
  'bidders',(SELECT count(*)::int FROM market_intelligence.bidder_participations),
  'submissions',(SELECT count(*)::int FROM market_intelligence.bid_submissions),
  'decisions',(SELECT count(*)::int FROM market_intelligence.bid_decisions),
  'fundingComponents',(SELECT count(*)::int FROM market_intelligence.bid_funding_components),
  'milestones',(SELECT count(*)::int FROM market_intelligence.transaction_milestones)
 )) AS payload`;

export async function getInstitutionalCapital(execute: SqlExecutor): Promise<InstitutionalCapitalResponse> {
  const query = await execute(capitalSql, []);
  const payload = query.rows[0]?.payload as Omit<InstitutionalCapitalResponse, "generatedAt" | "database"> | undefined;
  if (!payload?.items) throw new Error("Invalid institutional-capital response");
  return { ...payload, generatedAt: new Date().toISOString(), database: "supabase-postgresql" };
}

export async function getSaleProcesses(execute: SqlExecutor): Promise<SaleProcessResponse> {
  const query = await execute(saleSql, []);
  const payload = query.rows[0]?.payload as Omit<SaleProcessResponse, "generatedAt" | "database"> | undefined;
  if (!payload?.items) throw new Error("Invalid sale-process response");
  return { ...payload, generatedAt: new Date().toISOString(), database: "supabase-postgresql" };
}
