import type { InstitutionalCapitalResponse, SaleProcessResponse } from "@/lib/intelligence-contract";
import type { SqlExecutor } from "@/lib/server/market-search";
import {
  buildInstitutionalSelectionAssessments,
  type RawInstitutionalDeployment,
  type RawInstitutionalManagerSignal,
} from "@/lib/server/institutional-capital-assessment";

const capitalSql = `
WITH latest_document_candidates AS (
  SELECT document_id,document_version_id,title,published_at,
         row_number() OVER (
           PARTITION BY document_id
           ORDER BY version_no DESC,document_version_id DESC
         ) AS version_rank
  FROM document_versions
), latest_documents AS (
  SELECT document_id,document_version_id,title,published_at
  FROM latest_document_candidates
  WHERE version_rank=1
), relevant_claims AS (
  SELECT source_claim_id AS claim_id FROM lp_mandate_selections WHERE source_claim_id IS NOT NULL
  UNION SELECT source_claim_id FROM lp_mandate_deployments WHERE source_claim_id IS NOT NULL
  UNION SELECT source_claim_id FROM v_lp_manager_best_available WHERE source_claim_id IS NOT NULL AND canonical_eligible=0
  UNION SELECT claim_id FROM claims
        WHERE predicate_code IN ('LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT','LP_MANDATE_MANAGER_BID_PARTICIPANT')
), claim_document_candidates AS (
  SELECT c.claim_id,
         json_object(
           'documentId',sd.document_id,'title',dv.title,'documentType',sd.document_type,
           'publishedAt',dv.published_at,'publisher',sd.publisher_name,'href',sd.canonical_url,
           'relationBasis','SOURCE_CLAIM'
         ) AS source_document,
         row_number() OVER (
           PARTITION BY c.claim_id
           ORDER BY dv.version_no DESC,dv.document_version_id DESC
         ) AS document_rank
  FROM relevant_claims rc
  JOIN claims c ON c.claim_id=rc.claim_id
  JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
  JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
  JOIN document_versions dv ON dv.document_version_id=er.document_version_id
  JOIN source_documents sd ON sd.document_id=dv.document_id
), claim_documents AS (
  SELECT claim_id,source_document
  FROM claim_document_candidates
  WHERE document_rank=1
), official_document_candidates AS (
  SELECT s.mandate_selection_id,
         json_object(
           'documentId',sd.document_id,'title',ld.title,'documentType',sd.document_type,
           'publishedAt',ld.published_at,'publisher',sd.publisher_name,'href',sd.canonical_url,
           'relationBasis','OFFICIAL_SELECTION_EVIDENCE'
         ) AS source_document,
         row_number() OVER (
           PARTITION BY s.mandate_selection_id
           ORDER BY CASE WHEN sd.publisher_name=lp.canonical_name THEN 0 ELSE 1 END,
                    (ld.published_at IS NULL),ld.published_at DESC,sd.document_id
         ) AS official_rank
  FROM lp_mandate_selections s
  JOIN lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id
  JOIN lp_mandates m ON m.mandate_id=t.mandate_id
  JOIN organizations lp ON lp.organization_id=m.lp_organization_id
  LEFT JOIN claim_documents cd ON cd.claim_id=s.source_claim_id
  JOIN source_documents sd
    ON upper(sd.document_type) IN ('PRESS_RELEASE','DISCLOSURE','NOTICE','BID_NOTICE','REPORT','API_RECORD','LEGAL_DOCUMENT')
   AND (
     sd.document_id=json_extract(cd.source_document,'$.documentId')
     OR EXISTS (
       SELECT 1
       FROM json_each(
         CASE WHEN json_valid(coalesce(s.metadata_json,'')) THEN s.metadata_json ELSE '{}' END,
         '$.evidence.source_ids'
       ) AS source_id
       WHERE cast(source_id.value AS TEXT)=sd.document_id
     )
   )
  JOIN latest_documents ld ON ld.document_id=sd.document_id
  LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
  WHERE sd.publisher_name=lp.canonical_name
     OR (
       cs.source_kind IN ('OFFICIAL_API','OFFICIAL_SITE','PARTY_SITE')
       AND cs.authority_tier<=2
       AND EXISTS (
         SELECT 1
         FROM json_each(
           CASE WHEN json_valid(coalesce(s.metadata_json,'')) THEN s.metadata_json ELSE '{}' END,
           '$.evidence.official_source_contracts'
         ) AS contract
         WHERE json_extract(contract.value,'$.document_id')=sd.document_id
           AND upper(coalesce(json_extract(contract.value,'$.verification_status'),''))='VERIFIED'
           AND upper(coalesce(json_extract(contract.value,'$.publisher_role'),''))
               IN ('LP','OFFICIAL_AUTHORITY','PARTY_PRIMARY')
       )
     )
), official_documents AS (
  SELECT mandate_selection_id,source_document
  FROM official_document_candidates
  WHERE official_rank=1
), structured_manager_signals AS (
  SELECT m.mandate_id,s.mandate_selection_id AS signal_id,s.mandate_selection_id AS selection_id,
         CASE
           WHEN s.selection_status='SELECTED' AND s.review_status='APPROVED'
             AND s.evidence_status IN ('SOURCE_CLAIM','MANUAL_VERIFIED')
             AND official_doc.source_document IS NOT NULL THEN 'OFFICIAL_SELECTION'
           WHEN s.selection_status IN ('APPLIED','SHORTLISTED') THEN 'BID_PARTICIPATION'
           ELSE 'REVIEW_REQUIRED'
         END AS signal_kind,
         manager.organization_id AS manager_organization_id,manager.canonical_name AS manager_name,
         t.track_code,t.track_name,s.selection_status,s.selected_at,
         concat_ws(' · ',s.evidence_status,s.review_status) AS value_status,
         CASE WHEN s.selection_status='SELECTED' AND s.review_status='APPROVED'
                   AND s.evidence_status IN ('SOURCE_CLAIM','MANUAL_VERIFIED')
                   AND official_doc.source_document IS NOT NULL THEN 1 ELSE 0 END AS canonical_eligible,
         s.confidence,1 AS independent_family_count,1 AS occurrence_count,
         NULL AS reported_allocation,NULL AS allocation_currency,
         CASE WHEN s.selection_status='SELECTED' THEN '공식 선정 결과'
              WHEN s.selection_status='SHORTLISTED' THEN 'shortlist 참여'
              WHEN s.selection_status='APPLIED' THEN '입찰 지원'
              ELSE s.selection_status END AS action_label,
         NULL AS vehicle_name,NULL AS deal_label,NULL AS conflict_note,
         s.evidence_status,s.review_status,
         NULL AS certainty_code,NULL AS verification_status,NULL AS extraction_method,
         NULL AS rule_version,NULL AS funding_basis,official_doc.source_document
  FROM lp_mandate_selections s
  JOIN lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id
  JOIN lp_mandates m ON m.mandate_id=t.mandate_id
  JOIN organizations manager ON manager.organization_id=s.manager_organization_id
  LEFT JOIN official_documents official_doc ON official_doc.mandate_selection_id=s.mandate_selection_id
), reported_manager_signals AS (
  SELECT m.mandate_id,coalesce(b.source_claim_id,
           printf('reported:%s:%s:%s',m.mandate_id,b.manager_organization_id,b.track_code)) AS signal_id,
         NULL AS selection_id,'REPORTED_SELECTION' AS signal_kind,
         b.manager_organization_id,b.manager_name,b.track_code,t.track_name,b.selection_status,b.selected_at,
         b.value_status,0 AS canonical_eligible,b.confidence,b.independent_family_count,b.occurrence_count,
         b.reported_allocation_decimal AS reported_allocation,b.allocation_currency_code AS allocation_currency,
         '기사상 선정 보도' AS action_label,NULL AS vehicle_name,NULL AS deal_label,
         CASE WHEN b.value_status LIKE '%CONFLICT%' THEN b.value_status ELSE NULL END AS conflict_note,
         'SOURCE_CLAIM' AS evidence_status,'ACCEPTED' AS review_status,
         'REPORTED' AS certainty_code,'PENDING' AS verification_status,'MANUAL' AS extraction_method,
         NULL AS rule_version,NULL AS funding_basis,cd.source_document
  FROM v_lp_manager_best_available b
  JOIN lp_mandates m ON m.mandate_code=b.mandate_code
  LEFT JOIN lp_mandate_tracks t ON t.mandate_id=m.mandate_id AND t.track_code=b.track_code
  LEFT JOIN claim_documents cd ON cd.claim_id=b.source_claim_id
  WHERE b.canonical_eligible=0
), claim_argument_bundles AS (
  SELECT ca.claim_id,
         max(CASE WHEN ca.role_code='MANDATE_CODE' THEN ca.text_value END) AS mandate_code,
         max(CASE WHEN ca.role_code='MANDATE_TRACK' THEN ca.text_value END) AS track_code,
         max(CASE WHEN ca.role_code='FOLLOW_UP_ACTION' THEN ca.text_value END) AS action_label,
         max(CASE WHEN ca.role_code='FUNDING_BASIS' THEN ca.text_value END) AS funding_basis,
         (SELECT ca2.organization_id FROM claim_arguments ca2
           WHERE ca2.claim_id=ca.claim_id AND ca2.role_code='LINKED_VEHICLE'
           ORDER BY ca2.ordinal LIMIT 1) AS vehicle_organization_id,
         (SELECT ca2.asset_id FROM claim_arguments ca2
           WHERE ca2.claim_id=ca.claim_id AND ca2.role_code='LINKED_DEAL'
           ORDER BY ca2.ordinal LIMIT 1) AS deal_asset_id,
         (SELECT ca2.project_id FROM claim_arguments ca2
           WHERE ca2.claim_id=ca.claim_id AND ca2.role_code='LINKED_DEAL'
           ORDER BY ca2.ordinal LIMIT 1) AS deal_project_id,
         (SELECT group_concat(ordered_note.text_value,'; ')
          FROM (
            SELECT ca2.text_value
            FROM claim_arguments ca2
            WHERE ca2.claim_id=ca.claim_id AND ca2.role_code='CONTRADICTION_NOTE'
            ORDER BY ca2.ordinal,ca2.text_value
          ) ordered_note) AS conflict_note,
         max(CASE WHEN ca.role_code='INFERENCE_RULE_VERSION' THEN ca.text_value END) AS rule_version,
         sum(CASE WHEN ca.role_code='MANDATE_CODE' THEN 1 ELSE 0 END) AS mandate_count,
         sum(CASE WHEN ca.role_code='MANDATE_TRACK' THEN 1 ELSE 0 END) AS track_count,
         sum(CASE WHEN ca.role_code='FOLLOW_UP_ACTION' THEN 1 ELSE 0 END) AS action_count,
         sum(CASE WHEN ca.role_code='FUNDING_BASIS' THEN 1 ELSE 0 END) AS funding_count,
         sum(CASE WHEN ca.role_code='LINKED_VEHICLE' THEN 1 ELSE 0 END) AS vehicle_count,
         sum(CASE WHEN ca.role_code='LINKED_DEAL' THEN 1 ELSE 0 END) AS deal_count,
         sum(CASE WHEN ca.role_code='INFERENCE_RULE_VERSION' THEN 1 ELSE 0 END) AS rule_count
  FROM claim_arguments ca
  JOIN claims c ON c.claim_id=ca.claim_id
  WHERE c.predicate_code IN ('LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT','LP_MANDATE_MANAGER_BID_PARTICIPANT')
  GROUP BY ca.claim_id
), inferred_claim_signals AS (
  SELECT m.mandate_id,c.claim_id AS signal_id,NULL AS selection_id,
         CASE WHEN c.predicate_code='LP_MANDATE_MANAGER_BID_PARTICIPANT'
              THEN 'BID_PARTICIPATION' ELSE 'DEPLOYMENT_INFERENCE' END AS signal_kind,
         manager.organization_id AS manager_organization_id,manager.canonical_name AS manager_name,
         bundle.track_code,t.track_name,
         CASE WHEN c.predicate_code='LP_MANDATE_MANAGER_BID_PARTICIPANT' THEN 'APPLIED' ELSE 'INFERRED_SELECTED' END AS selection_status,
         c.date_start AS selected_at,concat_ws(' · ',c.certainty_code,c.verification_status,c.review_status) AS value_status,
         0 AS canonical_eligible,c.confidence,1 AS independent_family_count,1 AS occurrence_count,
         NULL AS reported_allocation,NULL AS allocation_currency,
         bundle.action_label,
         vehicle_org.canonical_name AS vehicle_name,
         coalesce(deal_asset.canonical_name,deal_project.canonical_name) AS deal_label,
         bundle.conflict_note,'SOURCE_CLAIM' AS evidence_status,
         c.review_status,c.certainty_code,c.verification_status,c.extraction_method,
         bundle.rule_version,bundle.funding_basis,cd.source_document
  FROM claims c
  JOIN claim_argument_bundles bundle ON bundle.claim_id=c.claim_id
  JOIN lp_mandates m ON m.mandate_code=bundle.mandate_code
  JOIN organizations manager ON manager.organization_id=c.object_organization_id
  JOIN lp_mandate_tracks t ON t.mandate_id=m.mandate_id AND t.track_code=bundle.track_code
  LEFT JOIN organizations vehicle_org ON vehicle_org.organization_id=bundle.vehicle_organization_id
  LEFT JOIN assets deal_asset ON deal_asset.asset_id=bundle.deal_asset_id
  LEFT JOIN projects deal_project ON deal_project.project_id=bundle.deal_project_id
  LEFT JOIN claim_documents cd ON cd.claim_id=c.claim_id
  WHERE c.predicate_code IN ('LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT','LP_MANDATE_MANAGER_BID_PARTICIPANT')
    AND c.review_status IN ('UNREVIEWED','ACCEPTED')
    AND bundle.mandate_count=1
    AND bundle.track_count=1
    AND bundle.action_count=1
    AND (
      c.predicate_code='LP_MANDATE_MANAGER_BID_PARTICIPANT'
      OR (
        bundle.funding_count=1
        AND bundle.rule_count=1
        AND bundle.vehicle_count<=1
        AND bundle.deal_count<=1
        AND bundle.vehicle_count+bundle.deal_count>=1
        AND (bundle.vehicle_count=0 OR vehicle_org.organization_id IS NOT NULL)
        AND (bundle.deal_count=0 OR deal_asset.asset_id IS NOT NULL OR deal_project.project_id IS NOT NULL)
      )
    )
), manager_signals AS (
  SELECT * FROM structured_manager_signals
  UNION ALL SELECT * FROM reported_manager_signals
  UNION ALL SELECT * FROM inferred_claim_signals
), deployment_rows AS (
  SELECT m.mandate_id,d.mandate_deployment_id AS deployment_id,s.mandate_selection_id AS selection_id,
         manager.organization_id AS manager_organization_id,manager.canonical_name AS manager_name,
         t.track_code,t.track_name,vehicle.canonical_name AS vehicle_name,
         coalesce(asset.canonical_name,project.canonical_name,event.canonical_title,sp.process_code) AS linked_target_label,
         d.deployment_basis AS basis,d.deployment_status AS status,d.deployed_at,
         d.amount_decimal AS amount,d.currency_code AS currency,d.evidence_status,d.review_status,d.confidence,
         d.source_claim_id,cd.source_document
  FROM lp_mandate_deployments d
  JOIN lp_mandate_selections s ON s.mandate_selection_id=d.mandate_selection_id
  JOIN lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id
  JOIN lp_mandates m ON m.mandate_id=t.mandate_id
  JOIN organizations manager ON manager.organization_id=s.manager_organization_id
  LEFT JOIN organizations vehicle ON vehicle.organization_id=d.fund_vehicle_organization_id
  LEFT JOIN assets asset ON asset.asset_id=d.asset_id
  LEFT JOIN projects project ON project.project_id=d.project_id
  LEFT JOIN events event ON event.event_id=d.event_id
  LEFT JOIN sale_processes sp ON sp.sale_process_id=d.sale_process_id
  LEFT JOIN claim_documents cd ON cd.claim_id=d.source_claim_id
  WHERE d.is_current=1
), mandate_rows AS (
  SELECT m.mandate_id,m.mandate_name,lp.canonical_name AS lp_name,m.mandate_status,m.mandate_scope,
         m.announced_at,m.selected_at,m.evidence_status,
         (SELECT count(*) FROM lp_mandate_tracks t WHERE t.mandate_id=m.mandate_id) AS track_count,
         (SELECT count(*) FROM structured_manager_signals s
           WHERE s.mandate_id=m.mandate_id AND s.signal_kind='OFFICIAL_SELECTION') AS selection_count,
         (SELECT count(*) FROM lp_mandate_amounts a
           LEFT JOIN lp_mandate_tracks t ON t.mandate_track_id=a.mandate_track_id
           LEFT JOIN lp_mandate_selections s ON s.mandate_selection_id=a.mandate_selection_id
           LEFT JOIN lp_mandate_tracks st ON st.mandate_track_id=s.mandate_track_id
           WHERE coalesce(a.mandate_id,t.mandate_id,st.mandate_id)=m.mandate_id AND a.is_current=1) AS amount_count,
         (SELECT count(*) FROM lp_mandate_guidelines g
           JOIN lp_mandate_tracks t ON t.mandate_track_id=g.mandate_track_id
           WHERE t.mandate_id=m.mandate_id) AS guideline_count,
         (SELECT count(*) FROM deployment_rows d
           WHERE d.mandate_id=m.mandate_id AND d.basis='LP_SOURCE_DEPLOYMENT'
             AND d.status IN ('COMMITTED','EXECUTED','REALISED') AND d.review_status='APPROVED') AS deployment_count,
         (SELECT json_group_array(json(track_item)) FROM (
           SELECT json_object(
             'trackId',t.mandate_track_id,'code',t.track_code,'name',t.track_name,'strategy',t.strategy_code,
             'geography',t.geography_code,'targetManagerCount',t.target_manager_count,'evidenceStatus',t.evidence_status,
             'guidelines',json((SELECT json_group_array(json(guideline_item)) FROM (
               SELECT json_object(
                 'termType',g.term_type,'requirement',g.requirement_level,'rawText',g.raw_text,
                 'value',coalesce(g.text_value,g.value_decimal_text),'unit',g.unit_code,'returnBasis',g.return_basis
               ) AS guideline_item
               FROM lp_mandate_guidelines g
               WHERE g.mandate_track_id=t.mandate_track_id
               ORDER BY g.term_type,g.requirement_level,g.raw_text
             ) ordered_guidelines))
           ) AS track_item
           FROM lp_mandate_tracks t
           WHERE t.mandate_id=m.mandate_id
           ORDER BY t.track_code,t.mandate_track_id
         ) ordered_tracks) AS tracks,
         (SELECT json_group_array(json(amount_item)) FROM (
           SELECT json_object(
             'amountId',a.mandate_amount_id,'basis',a.amount_basis,'amount',a.amount_decimal,
             'lowerAmount',a.lower_amount_decimal,'upperAmount',a.upper_amount_decimal,'currency',a.currency_code,
             'comparator',a.comparator_code,'status',a.amount_status,'rawValue',a.raw_value,'evidenceStatus',a.evidence_status
           ) AS amount_item
           FROM lp_mandate_amounts a
           LEFT JOIN lp_mandate_tracks t ON t.mandate_track_id=a.mandate_track_id
           LEFT JOIN lp_mandate_selections s ON s.mandate_selection_id=a.mandate_selection_id
           LEFT JOIN lp_mandate_tracks st ON st.mandate_track_id=s.mandate_track_id
           WHERE coalesce(a.mandate_id,t.mandate_id,st.mandate_id)=m.mandate_id AND a.is_current=1
           ORDER BY a.amount_basis,a.mandate_amount_id
         ) ordered_amounts) AS amounts,
         (SELECT json_group_array(json(selection_item)) FROM (
           SELECT json_object(
             'selectionId',s.selection_id,'managerId',s.manager_organization_id,'managerName',s.manager_name,
             'trackCode',s.track_code,'trackName',s.track_name,'status',s.selection_status,'selectedAt',s.selected_at,
             'evidenceStatus',s.evidence_status,'reviewStatus',s.review_status,'confidence',s.confidence
           ) AS selection_item
           FROM structured_manager_signals s
           WHERE s.mandate_id=m.mandate_id AND s.signal_kind='OFFICIAL_SELECTION'
           ORDER BY (s.selected_at IS NULL),s.selected_at,s.manager_name,s.selection_id
         ) ordered_selections) AS selections,
         (SELECT json_group_array(json(signal_item)) FROM (
           SELECT json_object(
             'signalId',s.signal_id,'selectionId',s.selection_id,'signalKind',s.signal_kind,
             'managerOrganizationId',s.manager_organization_id,'managerName',s.manager_name,
             'trackCode',s.track_code,'trackName',s.track_name,'selectionStatus',s.selection_status,
             'selectedAt',s.selected_at,'valueStatus',s.value_status,
             'canonicalEligible',json(CASE WHEN s.canonical_eligible<>0 THEN 'true' ELSE 'false' END),
             'confidence',s.confidence,'independentFamilyCount',s.independent_family_count,'occurrenceCount',s.occurrence_count,
             'reportedAllocation',s.reported_allocation,'allocationCurrency',s.allocation_currency,
             'actionLabel',s.action_label,'vehicleName',s.vehicle_name,'dealLabel',s.deal_label,
             'conflictNote',s.conflict_note,'evidenceStatus',s.evidence_status,'reviewStatus',s.review_status,
             'certaintyCode',s.certainty_code,'verificationStatus',s.verification_status,'extractionMethod',s.extraction_method,
             'ruleVersion',s.rule_version,'fundingBasis',s.funding_basis,
             'sourceDocument',CASE WHEN s.source_document IS NULL THEN NULL ELSE json(s.source_document) END
           ) AS signal_item
           FROM manager_signals s
           WHERE s.mandate_id=m.mandate_id
           ORDER BY (s.selected_at IS NULL),s.selected_at,s.manager_name,s.signal_id
         ) ordered_signals) AS manager_signals,
         (SELECT json_group_array(json(deployment_item)) FROM (
           SELECT json_object(
             'deploymentId',d.deployment_id,'selectionId',d.selection_id,
             'managerOrganizationId',d.manager_organization_id,'managerName',d.manager_name,
             'trackCode',d.track_code,'trackName',d.track_name,'vehicleName',d.vehicle_name,
             'linkedTargetLabel',d.linked_target_label,'basis',d.basis,'status',d.status,'deployedAt',d.deployed_at,
             'amount',d.amount,'currency',d.currency,'evidenceStatus',d.evidence_status,'reviewStatus',d.review_status,
             'confidence',d.confidence,'sourceClaimId',d.source_claim_id,
             'sourceDocument',CASE WHEN d.source_document IS NULL THEN NULL ELSE json(d.source_document) END
           ) AS deployment_item
           FROM deployment_rows d
           WHERE d.mandate_id=m.mandate_id
           ORDER BY (d.deployed_at IS NULL),d.deployed_at,d.deployment_id
         ) ordered_deployments) AS deployments,
         (SELECT json_group_array(DISTINCT json_object(
           'documentId',sd.document_id,'title',ld.title,'documentType',sd.document_type,
           'publishedAt',ld.published_at,'publisher',sd.publisher_name,'href',sd.canonical_url,
           'relationBasis',eml.relation_code
         ))
           FROM event_mention_links eml
           JOIN event_mentions em ON em.event_mention_id=eml.event_mention_id
           JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
           JOIN latest_documents ld ON ld.document_version_id=er.document_version_id
           JOIN source_documents sd ON sd.document_id=ld.document_id
           WHERE eml.event_id=m.event_id AND em.status_code='APPROVED'
             AND eml.relation_code IN ('PRIMARY','SUPPORTING','CORRECTION')) AS documents
  FROM lp_mandates m
  JOIN organizations lp ON lp.organization_id=m.lp_organization_id
)
SELECT json_object(
 'items',json((SELECT json_group_array(json(item)) FROM (
   SELECT json_object(
     'mandateId',mandate_id,'mandateName',mandate_name,'lpName',lp_name,'status',mandate_status,'scope',mandate_scope,
     'announcedAt',announced_at,'selectedAt',selected_at,'evidenceStatus',evidence_status,'trackCount',track_count,
     'selectionCount',selection_count,'amountCount',amount_count,'guidelineCount',guideline_count,'deploymentCount',deployment_count,
     'tracks',json(tracks),'amounts',json(amounts),'selections',json(selections),'managerSignals',json(manager_signals),
     'deployments',json(deployments),'documents',json(documents)
   ) AS item
   FROM mandate_rows
   ORDER BY (coalesce(selected_at,announced_at) IS NULL),coalesce(selected_at,announced_at) DESC,lp_name,mandate_id
 ) ordered_mandates)),
 'coverage',json_object(
   'mandates',(SELECT count(*) FROM lp_mandates),
   'selections',(SELECT count(*) FROM structured_manager_signals WHERE signal_kind='OFFICIAL_SELECTION'),
   'amounts',(SELECT count(*) FROM lp_mandate_amounts WHERE is_current=1),
   'deployments',(SELECT count(*) FROM deployment_rows
     WHERE basis='LP_SOURCE_DEPLOYMENT' AND status IN ('COMMITTED','EXECUTED','REALISED') AND review_status='APPROVED')
 )) AS payload`;

const saleSql = `
WITH latest_document_candidates AS (
  SELECT document_id,document_version_id,title,published_at,
         row_number() OVER (
           PARTITION BY document_id
           ORDER BY version_no DESC,document_version_id DESC
         ) AS version_rank
  FROM document_versions
), latest_documents AS (
  SELECT document_id,document_version_id,title,published_at
  FROM latest_document_candidates
  WHERE version_rank=1
), process_rows AS (
 SELECT sp.sale_process_id,sp.process_code,e.canonical_title AS title,sp.process_status,sp.sale_method,e.event_date_start,
        sp.launched_at,sp.closed_at,sp.evidence_status,
        (SELECT json_group_array(json(asset_item)) FROM (
           SELECT json_object(
             'assetId',a.asset_id,'name',a.canonical_name,'address',coalesce(a.road_address,a.jibun_address)
           ) AS asset_item
           FROM event_assets ea JOIN assets a ON a.asset_id=ea.asset_id
           WHERE ea.event_id=sp.event_id
           ORDER BY a.canonical_name,a.asset_id
         ) ordered_assets) AS assets,
        (SELECT json_group_array(json(round_item)) FROM (
           SELECT json_object(
             'roundId',r.bid_round_id,'roundNo',r.round_no,'roundCode',r.round_code,'roundType',r.round_type,
             'deadlineAt',r.deadline_at,'status',r.round_status,'evidenceStatus',r.evidence_status,
             'bidders',json((SELECT json_group_array(json(bidder_item)) FROM (
               SELECT json_object(
                 'organizationId',o.organization_id,'name',o.canonical_name,
                 'status',p.participation_status,'confidence',p.confidence
               ) AS bidder_item
               FROM bidder_participations p JOIN organizations o ON o.organization_id=p.bidder_organization_id
               WHERE p.bid_round_id=r.bid_round_id
               ORDER BY o.canonical_name,o.organization_id,p.participation_id
             ) ordered_bidders)),
          'submissions',json((SELECT json_group_array(json_object(
            'submissionId',s.bid_submission_id,'amount',s.bid_amount_decimal,'currency',s.currency_code,
            'priceBasis',s.price_basis,'rank',s.reported_rank,'confidence',s.confidence
          )) FROM bid_submissions s
            JOIN bidder_participations p ON p.participation_id=s.participation_id
            WHERE p.bid_round_id=r.bid_round_id)),
            'decisions',json((SELECT json_group_array(json(decision_item)) FROM (
              SELECT json_object(
                'type',d.decision_type,'date',d.decision_date,'status',d.decision_status,
                'reason',d.source_reason,'confidence',d.confidence
              ) AS decision_item
              FROM bid_decisions d
              WHERE d.bid_round_id=r.bid_round_id
              ORDER BY (d.decision_date IS NULL),d.decision_date,d.decision_type,d.decision_status,d.source_reason
            ) ordered_decisions))
          ) AS round_item
          FROM bid_rounds r
          WHERE r.sale_process_id=sp.sale_process_id
          ORDER BY r.round_no,r.bid_round_id
        ) ordered_rounds) AS rounds,
        (SELECT json_group_array(json(milestone_item)) FROM (
          SELECT json_object(
            'code',tm.milestone_code,'status',tm.milestone_status,'announcedAt',tm.announced_at,
            'effectiveDate',tm.effective_date,'expectedDate',tm.expected_date,'note',tm.source_note,
            'evidenceStatus',tm.evidence_status
          ) AS milestone_item
          FROM transaction_milestones tm
          WHERE tm.sale_process_id=sp.sale_process_id
          ORDER BY (coalesce(tm.effective_date,tm.announced_at,tm.expected_date) IS NULL),
                   coalesce(tm.effective_date,tm.announced_at,tm.expected_date),tm.milestone_code,tm.source_note
        ) ordered_milestones) AS milestones,
        (SELECT json_group_array(json_object(
          'type',fc.funding_type,'provider',o.canonical_name,'amount',fc.amount_decimal,
          'currency',fc.currency_code,'status',fc.commitment_status,
          'evidenceStatus',fc.evidence_status,'confidence',fc.confidence
        )) FROM bid_funding_components fc
          JOIN bid_submissions bs ON bs.bid_submission_id=fc.bid_submission_id
          JOIN bidder_participations bp ON bp.participation_id=bs.participation_id
          JOIN bid_rounds br ON br.bid_round_id=bp.bid_round_id
          LEFT JOIN organizations o ON o.organization_id=fc.provider_organization_id
          WHERE br.sale_process_id=sp.sale_process_id) AS funding,
        (SELECT json_group_array(DISTINCT json_object(
          'documentId',sd.document_id,'title',ld.title,'documentType',sd.document_type,
          'publishedAt',ld.published_at,'publisher',sd.publisher_name,'href',sd.canonical_url,
          'relationBasis','CANONICAL_EVENT'
        )) FROM event_mention_links eml
          JOIN event_mentions em ON em.event_mention_id=eml.event_mention_id
          JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
          JOIN latest_documents ld ON ld.document_version_id=er.document_version_id
          JOIN source_documents sd ON sd.document_id=ld.document_id
          WHERE eml.event_id=sp.event_id) AS documents
 FROM sale_processes sp JOIN events e ON e.event_id=sp.event_id
), research_sale_mentions AS (
 SELECT em.event_mention_id,em.extraction_key,em.title_raw,em.stage_code_hint,em.confidence,
        CASE WHEN substr(ltrim(coalesce(em.summary_raw,'')),1,1)='{'
                   AND json_valid(trim(coalesce(em.summary_raw,'')))
             THEN trim(em.summary_raw) ELSE '{}' END AS details
 FROM event_mentions em
 JOIN event_categories ec ON ec.event_category_id=em.event_category_id
 JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
 WHERE er.pipeline_version='cutoff-research-ledger-20260819-v1'
   AND ec.code='SALE'
   AND em.status_code='REVIEW_READY'
   AND substr(ltrim(coalesce(em.summary_raw,'')),1,1)='{'
   AND json_valid(trim(coalesce(em.summary_raw,'')))
), candidate_process_candidates AS (
 SELECT extraction_key AS candidate_id,title_raw AS title,stage_code_hint AS stage_code,
        confidence,details,
        row_number() OVER (
          PARTITION BY extraction_key
          ORDER BY (confidence IS NULL),confidence DESC,event_mention_id
        ) AS candidate_rank
 FROM research_sale_mentions
), candidate_process_rows AS (
 SELECT candidate_id,title,stage_code,confidence,details
 FROM candidate_process_candidates
 WHERE candidate_rank=1
), article_candidate_rows AS (
 SELECT em.event_mention_id AS candidate_id,rt.priority,
        coalesce(em.stage_code_hint,'MULTI_OR_UNRESOLVED') AS stage_code,
        coalesce(dv.published_at,dv.collected_at) AS published_at,
        sd.document_id,er.pipeline_version
 FROM review_tasks rt
 JOIN event_mentions em ON em.event_mention_id=rt.target_id
 JOIN event_categories ec ON ec.event_category_id=em.event_category_id
 JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
 JOIN document_versions dv ON dv.document_version_id=er.document_version_id
 JOIN source_documents sd ON sd.document_id=dv.document_id
 WHERE rt.target_kind='EVENT_MENTION'
   AND rt.review_type='SALE_PROCESS_EVIDENCE_REVIEW'
   AND rt.status_code IN ('PENDING','IN_PROGRESS')
   AND em.status_code='REVIEW_READY'
   AND ec.code='SALE'
   AND er.pipeline_version LIKE 'BID_PROCESS_TITLE_SNIPPET_V%'
   AND substr(coalesce(dv.published_at,dv.collected_at,''),1,4)=strftime('%Y','now')
), current_year_article_candidate_candidates AS (
 SELECT a.*,
        row_number() OVER (
          PARTITION BY document_id
          ORDER BY pipeline_version DESC,priority,(published_at IS NULL),published_at DESC,candidate_id
        ) AS document_rank
 FROM article_candidate_rows a
), current_year_article_candidate_rows AS (
 SELECT candidate_id,priority,stage_code,published_at,document_id,pipeline_version
 FROM current_year_article_candidate_candidates
 WHERE document_rank=1
)
SELECT json_object(
 'items',json((SELECT json_group_array(json(item)) FROM (
   SELECT json_object(
     'saleProcessId',sale_process_id,'processCode',process_code,'title',title,
     'status',process_status,'saleMethod',sale_method,'launchedAt',launched_at,'closedAt',closed_at,
     'evidenceStatus',evidence_status,'assets',json(assets),'rounds',json(rounds),
     'milestones',json(milestones),'funding',json(funding),'documents',json(documents)
   ) AS item
   FROM process_rows
   ORDER BY (coalesce(closed_at,launched_at) IS NULL),coalesce(closed_at,launched_at) DESC,title,sale_process_id
 ) ordered_processes)),
 'candidateProcesses',json((SELECT json_group_array(json(item)) FROM (
   SELECT json_object(
     'candidateId',candidate_id,
     'processCode',coalesce(json_extract(details,'$.process_code'),candidate_id),
     'title',coalesce(json_extract(details,'$.asset'),title),
     'assetType',coalesce(json_extract(details,'$.asset_type'),'UNKNOWN'),
     'method',coalesce(json_extract(details,'$.method'),'UNKNOWN'),
     'status',coalesce(json_extract(details,'$.current_status'),'REVIEW_READY'),
     'stageCode',coalesce(stage_code,'MULTI_OR_UNRESOLVED'),
     'evidenceGrade',coalesce(json_extract(details,'$.evidence_grade'),'C'),
     'confidence',confidence,
     'roles',json(coalesce(json_extract(details,'$.roles'),'{}')),
     'rounds',json(coalesce(json_extract(details,'$.rounds'),'[]')),
     'milestones',json(coalesce(json_extract(details,'$.milestones'),'[]')),
     'amounts',json(coalesce(json_extract(details,'$.amounts'),'[]')),
     'financing',json(coalesce(json_extract(details,'$.financing'),'[]')),
     'sources',json(coalesce(json_extract(details,'$.source_refs'),'[]'))
   ) AS item
   FROM candidate_process_rows
   ORDER BY candidate_id
 ) ordered_candidates)),
 'coverage',json_object(
  'processes',(SELECT count(*) FROM sale_processes),
  'rounds',(SELECT count(*) FROM bid_rounds),
  'bidders',(SELECT count(*) FROM bidder_participations),
  'submissions',(SELECT count(*) FROM bid_submissions),
  'decisions',(SELECT count(*) FROM bid_decisions),
  'fundingComponents',(SELECT count(*) FROM bid_funding_components),
  'milestones',(SELECT count(*) FROM transaction_milestones),
  'signalYear',cast(strftime('%Y','now') AS INTEGER),
  'candidateCutoffDate','2026-08-19',
  'currentYearProcesses',(SELECT count(*) FROM process_rows
    WHERE substr(coalesce(closed_at,launched_at,event_date_start,''),1,4)=strftime('%Y','now')),
  'currentYearCandidateProcesses',(SELECT count(*) FROM candidate_process_rows),
  'currentYearArticleSignals',(SELECT count(*) FROM current_year_article_candidate_rows),
  'currentYearPriorityArticleSignals',(SELECT count(*) FROM current_year_article_candidate_rows WHERE priority=1),
  'currentYearResolvedStageArticleSignals',(SELECT count(*) FROM current_year_article_candidate_rows
    WHERE stage_code<>'MULTI_OR_UNRESOLVED')
 )) AS payload`;

function parsePayload<T>(value: unknown): T | undefined {
  if (typeof value === "string") {
    try {
      return JSON.parse(value) as T;
    } catch {
      return undefined;
    }
  }
  return value && typeof value === "object" ? value as T : undefined;
}

export async function getInstitutionalCapital(execute: SqlExecutor): Promise<InstitutionalCapitalResponse> {
  const query = await execute(capitalSql, []);
  type RawItem = Omit<
    InstitutionalCapitalResponse["items"][number],
    "assessments" | "deployments" | "officialSelectionCount" | "inferredSelectionCount" | "bidParticipationCount" | "reviewRequiredCount"
  > & { managerSignals: RawInstitutionalManagerSignal[]; deployments: RawInstitutionalDeployment[] };
  type RawPayload = {
    items: RawItem[];
    coverage: Pick<InstitutionalCapitalResponse["coverage"], "mandates" | "selections" | "amounts" | "deployments">;
  };
  const payload = parsePayload<RawPayload>(query.rows[0]?.payload);
  if (!payload?.items) throw new Error("Invalid institutional-capital response");
  const items = payload.items.map((rawItem) => {
    const { managerSignals, deployments, ...item } = rawItem;
    const assessments = buildInstitutionalSelectionAssessments({
      mandateId: item.mandateId,
      mandateName: item.mandateName,
      lpName: item.lpName,
      tracks: item.tracks,
      documents: item.documents,
      managerSignals,
      deployments,
    });
    const count = (verdict: InstitutionalCapitalResponse["items"][number]["assessments"][number]["verdict"]) => (
      assessments.filter((assessment) => assessment.verdict === verdict).length
    );
    return {
      ...item,
      deployments: deployments as unknown as Array<Record<string, unknown>>,
      assessments,
      officialSelectionCount: count("OFFICIAL_SELECTION"),
      inferredSelectionCount: count("INFERRED_SELECTION"),
      bidParticipationCount: count("BID_PARTICIPATION"),
      reviewRequiredCount: count("REVIEW_REQUIRED"),
    };
  });
  const verdictCount = (verdict: InstitutionalCapitalResponse["items"][number]["assessments"][number]["verdict"]) => (
    items.reduce((total, item) => total + item.assessments.filter((assessment) => assessment.verdict === verdict).length, 0)
  );
  return {
    items,
    coverage: {
      ...payload.coverage,
      officialSelections: verdictCount("OFFICIAL_SELECTION"),
      inferredSelections: verdictCount("INFERRED_SELECTION"),
      bidParticipations: verdictCount("BID_PARTICIPATION"),
      reviewRequired: verdictCount("REVIEW_REQUIRED"),
    },
    generatedAt: new Date().toISOString(),
    database: "turso-libsql",
  };
}

export async function getSaleProcesses(execute: SqlExecutor): Promise<SaleProcessResponse> {
  const query = await execute(saleSql, []);
  const payload = parsePayload<Omit<SaleProcessResponse, "generatedAt" | "database">>(query.rows[0]?.payload);
  if (!payload?.items) throw new Error("Invalid sale-process response");
  return { ...payload, generatedAt: new Date().toISOString(), database: "turso-libsql" };
}
