-- V3.1.0: lineage-preserving document-to-canonical-entity relation projection.

DO $$
DECLARE current_version TEXT;
BEGIN
    SELECT schema_value INTO current_version
    FROM market_intelligence.schema_meta WHERE schema_key='schema_version';
    IF current_version IS DISTINCT FROM '3.0.0' THEN
        RAISE EXCEPTION 'Expected schema 3.0.0, found %', COALESCE(current_version,'missing');
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_extraction_runs_document_version
ON market_intelligence.extraction_runs(document_version_id);
CREATE INDEX IF NOT EXISTS ix_mentions_extraction_run
ON market_intelligence.mentions(extraction_run_id);
CREATE INDEX IF NOT EXISTS ix_mention_resolutions_selected
ON market_intelligence.mention_resolutions(mention_id,resolution_status,selected);
CREATE INDEX IF NOT EXISTS ix_event_mentions_extraction_run
ON market_intelligence.event_mentions(extraction_run_id);
CREATE INDEX IF NOT EXISTS ix_claims_event_verification
ON market_intelligence.claims(event_mention_id,verification_status,review_status);

CREATE VIEW market_intelligence.v_document_entity_relations AS
WITH event_evidence AS (
    SELECT DISTINCT dv.document_id,er.document_version_id,em.event_mention_id,
           eml.event_id,eml.relation_code,em.confidence
    FROM market_intelligence.extraction_runs er
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
    JOIN market_intelligence.event_mentions em ON em.extraction_run_id=er.extraction_run_id
    JOIN market_intelligence.event_mention_links eml ON eml.event_mention_id=em.event_mention_id
    WHERE em.status_code<>'REJECTED'
), relation_rows AS (
    SELECT ee.document_id,ee.document_version_id,'EVENT'::text AS entity_kind,
           ee.event_id AS entity_id,'CANONICAL_EVENT'::text AS relation_basis,
           ee.relation_code AS relation_role,e.verification_level AS evidence_status,
           ee.confidence,ee.event_id,NULL::text AS claim_id,NULL::text AS mention_id
    FROM event_evidence ee JOIN market_intelligence.events e ON e.event_id=ee.event_id
    WHERE e.lifecycle_status NOT IN ('REJECTED','MERGED')
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'ASSET',ea.asset_id,'CANONICAL_EVENT',
           ea.role_code,e.verification_level,coalesce(ea.confidence,ee.confidence),ee.event_id,
           ea.supporting_claim_id,NULL::text
    FROM event_evidence ee JOIN market_intelligence.events e ON e.event_id=ee.event_id
    JOIN market_intelligence.event_assets ea ON ea.event_id=ee.event_id
    WHERE e.lifecycle_status NOT IN ('REJECTED','MERGED')
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'ORGANIZATION',ep.organization_id,'CANONICAL_EVENT',
           ep.role_code,e.verification_level,coalesce(ep.confidence,ee.confidence),ee.event_id,
           ep.supporting_claim_id,NULL::text
    FROM event_evidence ee JOIN market_intelligence.events e ON e.event_id=ee.event_id
    JOIN market_intelligence.event_participants ep ON ep.event_id=ee.event_id
    WHERE e.lifecycle_status NOT IN ('REJECTED','MERGED')
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'PROJECT',ep.project_id,'CANONICAL_EVENT',
           ep.role_code,e.verification_level,coalesce(ep.confidence,ee.confidence),ee.event_id,
           ep.supporting_claim_id,NULL::text
    FROM event_evidence ee JOIN market_intelligence.events e ON e.event_id=ee.event_id
    JOIN market_intelligence.event_projects ep ON ep.event_id=ee.event_id
    WHERE e.lifecycle_status NOT IN ('REJECTED','MERGED')
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'SALE_PROCESS',sp.sale_process_id,'CANONICAL_EVENT',
           'EVENT_PROCESS',sp.evidence_status,ee.confidence,ee.event_id,sp.source_claim_id,NULL::text
    FROM event_evidence ee JOIN market_intelligence.sale_processes sp ON sp.event_id=ee.event_id
    WHERE sp.review_status<>'REJECTED'
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'LP_MANDATE',lm.mandate_id,'CANONICAL_EVENT',
           'EVENT_MANDATE',lm.evidence_status,ee.confidence,ee.event_id,lm.source_claim_id,NULL::text
    FROM event_evidence ee JOIN market_intelligence.lp_mandates lm ON lm.event_id=ee.event_id
    WHERE lm.review_status<>'REJECTED'
    UNION ALL
    SELECT dv.document_id,er.document_version_id,
           CASE WHEN mr.asset_id IS NOT NULL THEN 'ASSET'
                WHEN mr.project_id IS NOT NULL THEN 'PROJECT'
                WHEN mr.organization_id IS NOT NULL THEN 'ORGANIZATION' END,
           coalesce(mr.asset_id,mr.project_id,mr.organization_id),
           'RESOLVED_MENTION',mr.method_code,'RESOLVED',mr.match_score,NULL::text,NULL::text,m.mention_id
    FROM market_intelligence.extraction_runs er
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
    JOIN market_intelligence.mentions m ON m.extraction_run_id=er.extraction_run_id
    JOIN market_intelligence.mention_resolutions mr ON mr.mention_id=m.mention_id
    WHERE mr.resolution_status='RESOLVED' AND mr.selected=1
      AND m.review_status<>'REJECTED'
      AND (mr.asset_id IS NOT NULL OR mr.project_id IS NOT NULL OR mr.organization_id IS NOT NULL)
    UNION ALL
    SELECT dv.document_id,er.document_version_id,
           CASE WHEN c.object_asset_id IS NOT NULL THEN 'ASSET'
                WHEN c.object_project_id IS NOT NULL THEN 'PROJECT'
                WHEN c.object_organization_id IS NOT NULL THEN 'ORGANIZATION' END,
           coalesce(c.object_asset_id,c.object_project_id,c.object_organization_id),
           'VERIFIED_CLAIM',c.predicate_code,c.verification_status,c.confidence,NULL::text,c.claim_id,NULL::text
    FROM market_intelligence.claims c
    JOIN market_intelligence.event_mentions em ON em.event_mention_id=c.event_mention_id
    JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
    WHERE c.verification_status='VERIFIED' AND c.review_status<>'REJECTED'
      AND (c.object_asset_id IS NOT NULL OR c.object_project_id IS NOT NULL OR c.object_organization_id IS NOT NULL)
    UNION ALL
    SELECT dv.document_id,er.document_version_id,
           CASE WHEN ca.asset_id IS NOT NULL THEN 'ASSET'
                WHEN ca.project_id IS NOT NULL THEN 'PROJECT'
                WHEN ca.organization_id IS NOT NULL THEN 'ORGANIZATION' END,
           coalesce(ca.asset_id,ca.project_id,ca.organization_id),
           'VERIFIED_CLAIM',ca.role_code,c.verification_status,
           coalesce(ca.confidence,c.confidence),NULL::text,c.claim_id,NULL::text
    FROM market_intelligence.claims c
    JOIN market_intelligence.claim_arguments ca ON ca.claim_id=c.claim_id
    JOIN market_intelligence.event_mentions em ON em.event_mention_id=c.event_mention_id
    JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
    WHERE c.verification_status='VERIFIED' AND c.review_status<>'REJECTED'
      AND ca.argument_kind='ENTITY'
      AND (ca.asset_id IS NOT NULL OR ca.project_id IS NOT NULL OR ca.organization_id IS NOT NULL)
    UNION ALL
    SELECT dv.document_id,er.document_version_id,'LP_MANDATE',lm.mandate_id,'SOURCE_CLAIM',
           'MANDATE_SOURCE',lm.evidence_status,c.confidence,lm.event_id,c.claim_id,NULL::text
    FROM market_intelligence.lp_mandates lm
    JOIN market_intelligence.claims c ON c.claim_id=lm.source_claim_id
    JOIN market_intelligence.event_mentions em ON em.event_mention_id=c.event_mention_id
    JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
    WHERE lm.review_status<>'REJECTED' AND c.review_status<>'REJECTED'
    UNION ALL
    SELECT dv.document_id,er.document_version_id,'SALE_PROCESS',sp.sale_process_id,'SOURCE_CLAIM',
           'PROCESS_SOURCE',sp.evidence_status,c.confidence,sp.event_id,c.claim_id,NULL::text
    FROM market_intelligence.sale_processes sp
    JOIN market_intelligence.claims c ON c.claim_id=sp.source_claim_id
    JOIN market_intelligence.event_mentions em ON em.event_mention_id=c.event_mention_id
    JOIN market_intelligence.extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN market_intelligence.document_versions dv ON dv.document_version_id=er.document_version_id
    WHERE sp.review_status<>'REJECTED' AND c.review_status<>'REJECTED'
)
SELECT DISTINCT document_id,document_version_id,entity_kind,entity_id,relation_basis,
       relation_role,evidence_status,confidence,event_id,claim_id,mention_id
FROM relation_rows WHERE entity_kind IS NOT NULL AND entity_id IS NOT NULL;

UPDATE market_intelligence.schema_meta
SET schema_value = '3.1.0'
WHERE schema_key='schema_version' AND schema_value='3.0.0';
