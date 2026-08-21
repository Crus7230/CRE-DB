-- V2.9.0: version-bound CRE scope assessment.

DO $$
DECLARE
    current_version TEXT;
BEGIN
    SELECT schema_value INTO current_version
      FROM market_intelligence.schema_meta
     WHERE schema_key='schema_version';
    IF current_version IS DISTINCT FROM '2.8.0' THEN
        RAISE EXCEPTION 'Expected schema 2.8.0, found %', COALESCE(current_version, 'missing');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS market_intelligence.document_scope_assessments (
    document_scope_assessment_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES market_intelligence.document_versions(document_version_id) ON DELETE CASCADE,
    scope_code TEXT NOT NULL CHECK (scope_code IN ('CRE')),
    classifier_version TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK (status_code IN (
        'CRE_CONFIRMED','CRE_REVIEW','CRE_REVIEW_MIXED','CRE_REVIEW_PARSE_FAILED',
        'OUT_OF_SCOPE_NON_CRE','OUT_OF_SCOPE_RESIDENTIAL'
    )),
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    assessed_at TEXT NOT NULL,
    UNIQUE(document_version_id, scope_code, classifier_version)
);

CREATE INDEX IF NOT EXISTS ix_document_scope_assessments_scope_status
ON market_intelligence.document_scope_assessments(
    scope_code, status_code, classifier_version, document_version_id
);

UPDATE market_intelligence.schema_meta
SET schema_value = '2.9.0'
WHERE schema_key = 'schema_version' AND schema_value = '2.8.0';
