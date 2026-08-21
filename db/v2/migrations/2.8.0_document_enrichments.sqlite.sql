-- SQLite V2.7.0 -> V2.8.0: version-bound document content enrichment.

CREATE TABLE document_enrichments (
    document_enrichment_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE CASCADE,
    enrichment_kind TEXT NOT NULL CHECK (enrichment_kind IN ('CONTENT_SUMMARY')),
    pipeline_version TEXT NOT NULL,
    source_content_sha256 TEXT,
    resolved_url TEXT,
    content_mode TEXT NOT NULL CHECK (content_mode IN ('FULL_TEXT','SAFE_EXCERPT','SNIPPET','METADATA')),
    summary_method TEXT NOT NULL CHECK (summary_method IN ('EXTRACTIVE','MODEL','SOURCE','NONE')),
    summary_text TEXT,
    safe_excerpt TEXT,
    parser_name TEXT,
    parser_version TEXT,
    fetched_at TEXT,
    generated_at TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK (status_code IN ('COMPLETED','PARTIAL','FAILED')),
    review_status TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN ('UNREVIEWED','APPROVED','REJECTED')),
    error_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE (document_version_id, enrichment_kind, pipeline_version),
    CHECK (status_code <> 'COMPLETED' OR summary_text IS NOT NULL),
    CHECK (safe_excerpt IS NULL OR content_mode IN ('FULL_TEXT','SAFE_EXCERPT'))
) STRICT;

CREATE INDEX IF NOT EXISTS ix_document_enrichments_version_status
    ON document_enrichments(document_version_id, status_code, review_status);

UPDATE schema_meta SET schema_value='2.8.0' WHERE schema_key='schema_version';
