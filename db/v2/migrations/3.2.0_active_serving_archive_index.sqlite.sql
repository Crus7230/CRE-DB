-- SQLite V3.2.0: compact archive index for the local full archive.
BEGIN IMMEDIATE;

CREATE TEMP TABLE _v32_guard(value TEXT NOT NULL CHECK(value='3.1.0'));
INSERT INTO _v32_guard(value)
SELECT schema_value FROM schema_meta WHERE schema_key='schema_version';

CREATE TABLE archive_snapshots (
    archive_snapshot_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    archive_format TEXT NOT NULL CHECK(archive_format IN ('SQLITE')),
    archive_location TEXT NOT NULL,
    archive_snapshot_sha256 TEXT NOT NULL CHECK(length(archive_snapshot_sha256)=64),
    table_count INTEGER NOT NULL CHECK(table_count>=0),
    row_count INTEGER NOT NULL CHECK(row_count>=0),
    integrity_status TEXT NOT NULL CHECK(integrity_status IN ('VALIDATED','RETIRED')),
    foreign_key_violations INTEGER NOT NULL DEFAULT 0 CHECK(foreign_key_violations>=0),
    is_current INTEGER NOT NULL DEFAULT 0 CHECK(is_current IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX ux_archive_snapshots_current ON archive_snapshots(is_current) WHERE is_current=1;

CREATE TABLE archived_serving_index (
    archive_index_id TEXT PRIMARY KEY,
    archive_snapshot_id TEXT NOT NULL REFERENCES archive_snapshots(archive_snapshot_id) ON DELETE RESTRICT,
    record_kind TEXT NOT NULL CHECK(record_kind IN ('DOCUMENT','EVENT','SALE_PROCESS','LP_MANDATE','MACRO_OBSERVATION')),
    record_id TEXT NOT NULL,
    canonical_title TEXT NOT NULL,
    lifecycle_status TEXT,
    category_code TEXT,
    event_date_start TEXT,
    event_date_end TEXT,
    publisher_name TEXT,
    canonical_url TEXT,
    summary_text TEXT,
    source_document_id TEXT,
    source_document_version_id TEXT,
    archive_locator TEXT NOT NULL,
    archive_snapshot_sha256 TEXT NOT NULL CHECK(length(archive_snapshot_sha256)=64),
    indexed_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(record_kind, record_id)
);
CREATE INDEX ix_archived_serving_index_kind_status ON archived_serving_index(record_kind,lifecycle_status);
CREATE INDEX ix_archived_serving_index_category_date ON archived_serving_index(category_code,event_date_start);
CREATE INDEX ix_archived_serving_index_title ON archived_serving_index(canonical_title);

UPDATE schema_meta SET schema_value='3.2.0'
WHERE schema_key='schema_version' AND schema_value='3.1.0';
DROP TABLE _v32_guard;
COMMIT;
