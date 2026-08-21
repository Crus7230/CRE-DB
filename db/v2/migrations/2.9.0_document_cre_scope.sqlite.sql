-- SQLite V2.8.0 -> V2.9.0: version-bound CRE scope assessment.

CREATE TABLE document_scope_assessments (
    document_scope_assessment_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE CASCADE,
    scope_code TEXT NOT NULL CHECK (scope_code IN ('CRE')),
    classifier_version TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK (status_code IN (
        'CRE_CONFIRMED','CRE_REVIEW','CRE_REVIEW_MIXED','CRE_REVIEW_PARSE_FAILED',
        'OUT_OF_SCOPE_NON_CRE','OUT_OF_SCOPE_RESIDENTIAL'
    )),
    reason_codes_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(reason_codes_json)),
    evidence_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(evidence_json)),
    assessed_at TEXT NOT NULL,
    UNIQUE(document_version_id, scope_code, classifier_version)
) STRICT;

CREATE INDEX ix_document_scope_assessments_scope_status
    ON document_scope_assessments(scope_code, status_code, classifier_version, document_version_id);

UPDATE schema_meta SET schema_value='2.9.0' WHERE schema_key='schema_version';
