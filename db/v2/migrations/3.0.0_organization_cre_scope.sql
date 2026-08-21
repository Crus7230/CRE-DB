-- V3.0.0: versioned CRE scope assessment for organization identity masters.

DO $$
DECLARE
    current_version TEXT;
BEGIN
    SELECT schema_value INTO current_version
      FROM market_intelligence.schema_meta
     WHERE schema_key='schema_version';
    IF current_version IS DISTINCT FROM '2.9.0' THEN
        RAISE EXCEPTION 'Expected schema 2.9.0, found %', COALESCE(current_version, 'missing');
    END IF;
END $$;

CREATE TABLE market_intelligence.organization_scope_assessments (
    organization_scope_assessment_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES market_intelligence.organizations(organization_id) ON DELETE CASCADE,
    scope_code TEXT NOT NULL CHECK (scope_code='CRE'),
    classifier_version TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK (status_code IN (
        'CRE_CONFIRMED','CRE_CONTEXT_ONLY','CRE_REVIEW'
    )),
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    assessed_at TEXT NOT NULL,
    UNIQUE(organization_id, scope_code, classifier_version)
);

CREATE INDEX ix_organization_scope_assessments_scope_status
ON market_intelligence.organization_scope_assessments(
    scope_code, status_code, classifier_version, organization_id
);

UPDATE market_intelligence.schema_meta
SET schema_value = '3.0.0'
WHERE schema_key='schema_version' AND schema_value='2.9.0';
