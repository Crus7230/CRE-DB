-- Commercial Real Estate Intelligence V2
-- SQLite 3 authority schema for serverless local accumulation
-- Application-generated IDs may be supplied; defaults generate 32-char random hex IDs.

PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;

BEGIN IMMEDIATE;

-- ============================================================================
-- 0. Schema metadata and controlled vocabularies
-- ============================================================================

CREATE TABLE schema_meta (
    schema_key      TEXT PRIMARY KEY,
    schema_value    TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE units (
    unit_code       TEXT PRIMARY KEY,
    dimension_code  TEXT NOT NULL,
    name_ko         TEXT NOT NULL,
    symbol          TEXT,
    si_multiplier   REAL,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE TABLE asset_classes (
    asset_class_id  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    code            TEXT NOT NULL UNIQUE,
    name_ko         TEXT NOT NULL,
    parent_id       TEXT REFERENCES asset_classes(asset_class_id),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
) STRICT;

CREATE TABLE event_categories (
    event_category_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    code              TEXT NOT NULL UNIQUE,
    name_ko           TEXT NOT NULL,
    parent_id         TEXT REFERENCES event_categories(event_category_id),
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
) STRICT;

CREATE TABLE event_stages (
    stage_code        TEXT PRIMARY KEY,
    event_category_id TEXT REFERENCES event_categories(event_category_id),
    name_ko           TEXT NOT NULL,
    stage_rank        INTEGER,
    is_terminal       INTEGER NOT NULL DEFAULT 0 CHECK (is_terminal IN (0,1)),
    metadata_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE predicate_definitions (
    predicate_code   TEXT PRIMARY KEY,
    name_ko          TEXT NOT NULL,
    subject_scope    TEXT NOT NULL CHECK (subject_scope IN (
                         'EVENT','ASSET','PROJECT','ORGANIZATION','REGION','ANY'
                       )),
    value_kind       TEXT NOT NULL CHECK (value_kind IN (
                         'TEXT','NUMBER','MONEY','AREA','DATE','DATETIME','PERCENT',
                         'COUNT','DURATION','BOOLEAN','ASSET_REF','ASSET_CLASS_REF','PROJECT_REF',
                         'ORGANIZATION_REF','REGION_REF','JSON'
                       )),
    default_unit_code TEXT REFERENCES units(unit_code),
    is_multivalued   INTEGER NOT NULL DEFAULT 0 CHECK (is_multivalued IN (0,1)),
    description      TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
) STRICT;

CREATE TABLE mention_type_definitions (
    mention_type     TEXT PRIMARY KEY,
    name_ko          TEXT NOT NULL,
    resolution_target TEXT NOT NULL CHECK (resolution_target IN (
                           'NONE','ASSET','PROJECT','ORGANIZATION','REGION','ASSET_CLASS'
                         )),
    is_quantitative  INTEGER NOT NULL DEFAULT 0 CHECK (is_quantitative IN (0,1))
) STRICT;

-- Extensible measurement taxonomy. New metric kinds are data, not columns.
CREATE TABLE measurement_definitions (
    measurement_definition_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    code                TEXT NOT NULL UNIQUE,
    name_ko             TEXT NOT NULL,
    name_en             TEXT,
    parent_definition_id TEXT REFERENCES measurement_definitions(measurement_definition_id),
    dimension_code      TEXT NOT NULL,
    measurement_family  TEXT NOT NULL,
    canonical_unit_code TEXT REFERENCES units(unit_code),
    aggregation_behavior TEXT NOT NULL CHECK (aggregation_behavior IN (
                          'ADDITIVE','SEMI_ADDITIVE','NON_ADDITIVE','RATIO','SNAPSHOT'
                        )),
    sector_scope        TEXT NOT NULL DEFAULT 'CROSS_SECTOR' CHECK (sector_scope IN (
                          'CROSS_SECTOR','SECTOR_SPECIFIC'
                        )),
    definition_text     TEXT NOT NULL,
    inclusion_text      TEXT,
    exclusion_text      TEXT,
    is_abstract         INTEGER NOT NULL DEFAULT 0 CHECK (is_abstract IN (0,1)),
    definition_version  INTEGER NOT NULL DEFAULT 1 CHECK (definition_version >= 1),
    valid_from          TEXT,
    valid_to            TEXT,
    status_code         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN (
                          'DRAFT','ACTIVE','DEPRECATED','MERGED'
                        )),
    replaced_by_id      TEXT REFERENCES measurement_definitions(measurement_definition_id),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK ((status_code IN ('DEPRECATED','MERGED') AND replaced_by_id IS NOT NULL)
        OR (status_code NOT IN ('DEPRECATED','MERGED') AND replaced_by_id IS NULL)),
    CHECK (replaced_by_id IS NULL OR replaced_by_id <> measurement_definition_id)
) STRICT;

CREATE TABLE measurement_definition_aliases (
    measurement_alias_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    measurement_definition_id TEXT NOT NULL REFERENCES measurement_definitions(measurement_definition_id),
    alias_text          TEXT NOT NULL,
    normalized_alias    TEXT NOT NULL,
    language_code      TEXT NOT NULL DEFAULT 'ko',
    asset_class_id     TEXT REFERENCES asset_classes(asset_class_id),
    source_context     TEXT,
    mapping_confidence REAL CHECK (mapping_confidence IS NULL OR mapping_confidence BETWEEN 0 AND 1),
    requires_review    INTEGER NOT NULL DEFAULT 0 CHECK (requires_review IN (0,1)),
    valid_from         TEXT,
    valid_to           TEXT,
    example_text       TEXT,
    UNIQUE(measurement_definition_id, normalized_alias, asset_class_id, source_context),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE measurement_definition_relations (
    subject_definition_id TEXT NOT NULL REFERENCES measurement_definitions(measurement_definition_id),
    relation_code       TEXT NOT NULL CHECK (relation_code IN (
                          'SAME_AS','CLOSE_TO','COMPONENT_OF','OVERLAPS','EXCLUDES',
                          'DERIVED_FROM','REPLACES'
                        )),
    object_definition_id TEXT NOT NULL REFERENCES measurement_definitions(measurement_definition_id),
    relation_note       TEXT,
    confidence          REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    PRIMARY KEY(subject_definition_id, relation_code, object_definition_id),
    CHECK (subject_definition_id <> object_definition_id)
) STRICT;

CREATE TABLE measurement_applicability (
    measurement_definition_id TEXT NOT NULL REFERENCES measurement_definitions(measurement_definition_id),
    asset_class_id      TEXT NOT NULL REFERENCES asset_classes(asset_class_id),
    applicability_code TEXT NOT NULL CHECK (applicability_code IN (
                          'CORE','COMMON','OPTIONAL','RARE','NOT_APPLICABLE'
                        )),
    note_text           TEXT,
    PRIMARY KEY(measurement_definition_id, asset_class_id)
) STRICT;

CREATE TABLE spatial_unit_types (
    spatial_unit_type_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    code                TEXT NOT NULL UNIQUE,
    name_ko             TEXT NOT NULL,
    parent_type_id      TEXT REFERENCES spatial_unit_types(spatial_unit_type_id),
    is_physical         INTEGER NOT NULL DEFAULT 1 CHECK (is_physical IN (0,1)),
    is_repeatable       INTEGER NOT NULL DEFAULT 1 CHECK (is_repeatable IN (0,1)),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE measurement_dimension_definitions (
    measurement_dimension_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    code                TEXT NOT NULL UNIQUE,
    name_ko             TEXT NOT NULL,
    value_kind          TEXT NOT NULL CHECK (value_kind IN (
                          'OPTION','TEXT','DECIMAL','INTEGER','BOOLEAN','DATE','SPATIAL_UNIT'
                        )),
    dimension_group     TEXT NOT NULL,
    description         TEXT NOT NULL,
    is_multivalued      INTEGER NOT NULL DEFAULT 0 CHECK (is_multivalued IN (0,1)),
    status_code         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN (
                          'ACTIVE','DEPRECATED'
                        ))
) STRICT;

CREATE TABLE measurement_dimension_options (
    measurement_dimension_option_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    measurement_dimension_id TEXT NOT NULL REFERENCES measurement_dimension_definitions(measurement_dimension_id),
    code                TEXT NOT NULL,
    name_ko             TEXT NOT NULL,
    parent_option_id    TEXT REFERENCES measurement_dimension_options(measurement_dimension_option_id),
    sort_order          INTEGER NOT NULL DEFAULT 0,
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(measurement_dimension_id, code),
    UNIQUE(measurement_dimension_id, measurement_dimension_option_id)
) STRICT;

-- ============================================================================
-- 1. Canonical geography, organizations, assets and projects
-- ============================================================================

CREATE TABLE regions (
    region_id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    region_type       TEXT NOT NULL CHECK (region_type IN (
                          'COUNTRY','SIDO','SIGUNGU','EUPMYEONDONG','LEGAL_DONG',
                          'MARKET_DISTRICT','CUSTOM'
                        )),
    canonical_name    TEXT NOT NULL,
    parent_region_id  TEXT REFERENCES regions(region_id),
    legal_dong_code   TEXT,
    country_code      TEXT NOT NULL DEFAULT 'KR',
    valid_from        TEXT,
    valid_to          TEXT,
    metadata_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(region_type, canonical_name, parent_region_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE region_aliases (
    region_alias_id   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    region_id         TEXT NOT NULL REFERENCES regions(region_id) ON DELETE CASCADE,
    alias_text        TEXT NOT NULL,
    normalized_alias  TEXT NOT NULL,
    alias_type        TEXT NOT NULL DEFAULT 'OTHER',
    UNIQUE(region_id, normalized_alias)
) STRICT;

CREATE TABLE organizations (
    organization_id   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    organization_type TEXT NOT NULL CHECK (organization_type IN (
                          'COMPANY','SPC','FUND','REIT','FINANCIAL_INSTITUTION',
                          'GOVERNMENT','ASSOCIATION','PERSON','OTHER'
                        )),
    canonical_name    TEXT NOT NULL,
    corporate_no      TEXT,
    business_no       TEXT,
    dart_corp_code    TEXT,
    stock_code        TEXT,
    country_code      TEXT NOT NULL DEFAULT 'KR',
    status_code       TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN (
                          'ACTIVE','INACTIVE','MERGED'
                        )),
    merged_into_id    TEXT REFERENCES organizations(organization_id),
    metadata_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((status_code = 'MERGED' AND merged_into_id IS NOT NULL)
        OR (status_code <> 'MERGED' AND merged_into_id IS NULL)),
    CHECK (merged_into_id IS NULL OR merged_into_id <> organization_id)
) STRICT;

CREATE UNIQUE INDEX uq_organizations_corporate_no
    ON organizations(corporate_no) WHERE corporate_no IS NOT NULL;
CREATE UNIQUE INDEX uq_organizations_dart_code
    ON organizations(dart_corp_code) WHERE dart_corp_code IS NOT NULL;

CREATE TABLE organization_aliases (
    organization_alias_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    organization_id       TEXT NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    alias_text             TEXT NOT NULL,
    normalized_alias       TEXT NOT NULL,
    alias_type             TEXT NOT NULL DEFAULT 'OTHER',
    valid_from             TEXT,
    valid_to               TEXT,
    UNIQUE(organization_id, normalized_alias),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE assets (
    asset_id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    canonical_name      TEXT NOT NULL,
    asset_class_id      TEXT REFERENCES asset_classes(asset_class_id),
    region_id           TEXT REFERENCES regions(region_id),
    road_address        TEXT,
    jibun_address       TEXT,
    postal_code         TEXT,
    legal_dong_code     TEXT,
    latitude            REAL CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    longitude           REAL CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),
    building_mgmt_no    TEXT,
    parcel_key          TEXT,
    status_code         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN (
                          'CANDIDATE','ACTIVE','DEMOLISHED','INACTIVE','MERGED'
                        )),
    merged_into_id      TEXT REFERENCES assets(asset_id),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    CHECK ((status_code = 'MERGED' AND merged_into_id IS NOT NULL)
        OR (status_code <> 'MERGED' AND merged_into_id IS NULL)),
    CHECK (merged_into_id IS NULL OR merged_into_id <> asset_id)
) STRICT;

CREATE UNIQUE INDEX uq_assets_building_mgmt_no
    ON assets(building_mgmt_no) WHERE building_mgmt_no IS NOT NULL;
CREATE INDEX ix_assets_region_class ON assets(region_id, asset_class_id);

CREATE TABLE asset_aliases (
    asset_alias_id      TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    asset_id            TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    alias_text          TEXT NOT NULL,
    normalized_alias    TEXT NOT NULL,
    alias_type          TEXT NOT NULL DEFAULT 'OTHER',
    valid_from          TEXT,
    valid_to            TEXT,
    UNIQUE(asset_id, normalized_alias),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE projects (
    project_id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    canonical_name      TEXT NOT NULL,
    project_type        TEXT,
    asset_class_id      TEXT REFERENCES asset_classes(asset_class_id),
    region_id           TEXT REFERENCES regions(region_id),
    representative_address TEXT,
    status_code         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN (
                          'CANDIDATE','ACTIVE','COMPLETED','CANCELLED','MERGED'
                        )),
    merged_into_id      TEXT REFERENCES projects(project_id),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    CHECK ((status_code = 'MERGED' AND merged_into_id IS NOT NULL)
        OR (status_code <> 'MERGED' AND merged_into_id IS NULL)),
    CHECK (merged_into_id IS NULL OR merged_into_id <> project_id)
) STRICT;

CREATE TABLE project_aliases (
    project_alias_id    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    project_id          TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    alias_text          TEXT NOT NULL,
    normalized_alias    TEXT NOT NULL,
    alias_type          TEXT NOT NULL DEFAULT 'OTHER',
    UNIQUE(project_id, normalized_alias)
) STRICT;

CREATE TABLE project_assets (
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    asset_id            TEXT NOT NULL REFERENCES assets(asset_id),
    relation_code       TEXT NOT NULL CHECK (relation_code IN (
                          'SITE','CONTAINS','PHASE','RESULTING_ASSET','PORTFOLIO_MEMBER','RELATED'
                        )),
    valid_from          TEXT,
    valid_to            TEXT,
    evidence_claim_id   TEXT REFERENCES claims(claim_id),
    PRIMARY KEY(project_id, asset_id, relation_code),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE spatial_units (
    spatial_unit_id     TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    spatial_unit_type_id TEXT NOT NULL REFERENCES spatial_unit_types(spatial_unit_type_id),
    parent_spatial_unit_id TEXT REFERENCES spatial_units(spatial_unit_id),
    asset_id            TEXT REFERENCES assets(asset_id),
    project_id          TEXT REFERENCES projects(project_id),
    canonical_name      TEXT NOT NULL,
    unit_code           TEXT,
    floor_label         TEXT,
    floor_number        INTEGER,
    floor_number_end    INTEGER,
    is_basement         INTEGER CHECK (is_basement IS NULL OR is_basement IN (0,1)),
    phase_code          TEXT,
    sort_path           TEXT,
    valid_from          TEXT,
    valid_to            TEXT,
    status_code         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN (
                          'PLANNED','ACTIVE','INACTIVE','MERGED'
                        )),
    merged_into_id      TEXT REFERENCES spatial_units(spatial_unit_id),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((asset_id IS NOT NULL) + (project_id IS NOT NULL) <= 1),
    CHECK (parent_spatial_unit_id IS NOT NULL OR asset_id IS NOT NULL OR project_id IS NOT NULL),
    CHECK (parent_spatial_unit_id IS NULL OR parent_spatial_unit_id <> spatial_unit_id),
    CHECK (floor_number_end IS NULL OR floor_number IS NULL OR floor_number_end >= floor_number),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK ((status_code = 'MERGED' AND merged_into_id IS NOT NULL)
        OR (status_code <> 'MERGED' AND merged_into_id IS NULL)),
    CHECK (merged_into_id IS NULL OR merged_into_id <> spatial_unit_id)
) STRICT;

CREATE TABLE spatial_unit_aliases (
    spatial_unit_alias_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    spatial_unit_id     TEXT NOT NULL REFERENCES spatial_units(spatial_unit_id) ON DELETE CASCADE,
    alias_text          TEXT NOT NULL,
    normalized_alias    TEXT NOT NULL,
    alias_type          TEXT NOT NULL DEFAULT 'OTHER',
    valid_from          TEXT,
    valid_to            TEXT,
    UNIQUE(spatial_unit_id, normalized_alias),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE INDEX ix_spatial_units_parent ON spatial_units(parent_spatial_unit_id, sort_path);
CREATE INDEX ix_spatial_units_asset ON spatial_units(asset_id, spatial_unit_type_id);
CREATE INDEX ix_spatial_units_project ON spatial_units(project_id, spatial_unit_type_id);

-- ============================================================================
-- 2. Collection sources, jobs and runs
-- ============================================================================

CREATE TABLE collection_sources (
    source_id           TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_code         TEXT NOT NULL UNIQUE,
    source_name         TEXT NOT NULL,
    source_kind         TEXT NOT NULL CHECK (source_kind IN (
                          'SEARCH_API','RSS','MEDIA','OFFICIAL_API','OFFICIAL_SITE',
                          'PARTY_SITE','STATISTICS','MANUAL'
                        )),
    base_url            TEXT,
    authority_tier      INTEGER NOT NULL DEFAULT 4 CHECK (authority_tier BETWEEN 1 AND 5),
    collection_policy   TEXT NOT NULL CHECK (collection_policy IN (
                          'API_ALLOWED','RSS_ONLY','PUBLIC_LOW_RATE','METADATA_ONLY',
                          'MANUAL_ONLY','PROHIBITED'
                        )),
    policy_checked_at   TEXT,
    config_json         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(config_json)),
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE collection_jobs (
    job_id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    job_code            TEXT NOT NULL,
    job_version         INTEGER NOT NULL,
    job_kind            TEXT NOT NULL CHECK (job_kind IN (
                          'CATEGORY_SEARCH','MACRO_SERIES','OFFICIAL_VERIFICATION','MANUAL_IMPORT'
                        )),
    source_id           TEXT REFERENCES collection_sources(source_id),
    query_template      TEXT,
    cadence_code        TEXT CHECK (cadence_code IS NULL OR cadence_code IN (
                          'HOURLY','DAILY','WEEKLY','MONTHLY','QUARTERLY','EVENT_DRIVEN','MANUAL'
                        )),
    config_json         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(config_json)),
    valid_from          TEXT NOT NULL,
    valid_to            TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    UNIQUE(job_code, job_version),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
) STRICT;

CREATE TABLE collection_job_categories (
    job_id              TEXT NOT NULL REFERENCES collection_jobs(job_id) ON DELETE CASCADE,
    event_category_id   TEXT NOT NULL REFERENCES event_categories(event_category_id),
    is_primary          INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    PRIMARY KEY(job_id, event_category_id)
) STRICT;

CREATE TABLE collection_runs (
    run_id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    job_id              TEXT NOT NULL REFERENCES collection_jobs(job_id),
    scheduled_for       TEXT,
    started_at          TEXT,
    completed_at        TEXT,
    status_code         TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status_code IN (
                          'QUEUED','RUNNING','COMPLETED','PARTIAL','FAILED','CANCELLED'
                        )),
    query_rendered      TEXT,
    cursor_in           TEXT,
    cursor_out          TEXT,
    discovered_count    INTEGER CHECK (discovered_count IS NULL OR discovered_count >= 0),
    inserted_count      INTEGER CHECK (inserted_count IS NULL OR inserted_count >= 0),
    updated_count       INTEGER CHECK (updated_count IS NULL OR updated_count >= 0),
    rejected_count      INTEGER CHECK (rejected_count IS NULL OR rejected_count >= 0),
    error_code          TEXT,
    error_message       TEXT,
    runner_version      TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
) STRICT;

-- ============================================================================
-- 3. Source document identity and immutable versions
-- ============================================================================

CREATE TABLE source_documents (
    document_id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_id           TEXT REFERENCES collection_sources(source_id),
    canonical_url       TEXT NOT NULL,
    publisher_name      TEXT,
    document_type       TEXT NOT NULL CHECK (document_type IN (
                          'ARTICLE','PRESS_RELEASE','DISCLOSURE','NOTICE','BID_NOTICE',
                          'REPORT','RSS_ITEM','API_RECORD','LEGAL_DOCUMENT','OTHER'
                        )),
    external_document_key TEXT,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    access_status       TEXT NOT NULL DEFAULT 'ACCESSIBLE' CHECK (access_status IN (
                          'ACCESSIBLE','LOGIN_REQUIRED','PAYWALLED','BLOCKED',
                          'REMOVED','ERROR','MANUAL_ONLY'
                        )),
    UNIQUE(source_id, canonical_url)
) STRICT;

CREATE TABLE document_versions (
    document_version_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    document_id         TEXT NOT NULL REFERENCES source_documents(document_id) ON DELETE CASCADE,
    version_no          INTEGER NOT NULL CHECK (version_no >= 1),
    title               TEXT,
    author_name         TEXT,
    published_at        TEXT,
    modified_at         TEXT,

    collected_at        TEXT NOT NULL,
    language_code       TEXT NOT NULL DEFAULT 'ko',
    content_sha256      TEXT NOT NULL,
    snippet_text        TEXT,
    stored_text         TEXT,
    raw_payload_uri     TEXT,
    rights_status       TEXT NOT NULL CHECK (rights_status IN (
                          'FULL_STORAGE_ALLOWED','EXCERPT_ALLOWED','METADATA_ONLY',
                          'MANUAL_ACCESS','UNKNOWN'
                        )),
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    UNIQUE(document_id, version_no),
    UNIQUE(document_id, content_sha256),
    CHECK (stored_text IS NULL OR rights_status = 'FULL_STORAGE_ALLOWED')
) STRICT;

CREATE TRIGGER document_version_no_update
BEFORE UPDATE ON document_versions
BEGIN SELECT RAISE(ABORT, 'document version is immutable; insert a new version'); END;
CREATE TRIGGER document_version_no_delete
BEFORE DELETE ON document_versions
BEGIN SELECT RAISE(ABORT, 'document version is immutable'); END;

CREATE TABLE run_documents (
    run_id              TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
    result_rank         INTEGER CHECK (result_rank IS NULL OR result_rank > 0),
    search_snippet      TEXT,
    discovered_at       TEXT NOT NULL,
    PRIMARY KEY(run_id, document_version_id)
) STRICT;

CREATE TABLE document_families (
    family_id           TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    family_type         TEXT NOT NULL CHECK (family_type IN (
                          'VERSION','SYNDICATED','PRESS_RELEASE_COPY','OTHER'
                        )),
    representative_document_id TEXT REFERENCES source_documents(document_id),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE document_family_members (
    family_id           TEXT NOT NULL REFERENCES document_families(family_id) ON DELETE CASCADE,
    document_id         TEXT NOT NULL REFERENCES source_documents(document_id),
    relation_confidence REAL CHECK (relation_confidence IS NULL OR relation_confidence BETWEEN 0 AND 1),
    PRIMARY KEY(family_id, document_id)
) STRICT;

-- Contentless FTS is maintained explicitly by the ingestion application.
CREATE VIRTUAL TABLE document_fts USING fts5(
    document_version_id UNINDEXED,
    title,
    body,
    tokenize='unicode61'
);

-- ============================================================================
-- 4. NLP extraction, optional tokens, mention spans and resolution
-- ============================================================================

CREATE TABLE extraction_runs (
    extraction_run_id   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
    pipeline_version    TEXT NOT NULL,
    tokenizer_name      TEXT,
    tokenizer_version   TEXT,
    offset_basis        TEXT NOT NULL DEFAULT 'UNICODE_CODEPOINT' CHECK (offset_basis IN (
                          'UNICODE_CODEPOINT','UTF8_BYTE','UTF16_CODE_UNIT'
                        )),
    model_name          TEXT,
    model_version       TEXT,
    prompt_or_rule_hash TEXT,
    started_at          TEXT,
    completed_at        TEXT,
    status_code         TEXT NOT NULL CHECK (status_code IN (
                          'RUNNING','COMPLETED','PARTIAL','FAILED'
                        )),
    error_message       TEXT,
    UNIQUE(document_version_id, pipeline_version)
) STRICT;

-- Optional reproducibility layer. Mentions, not all tokens, are the authority layer.
CREATE TABLE document_tokens (
    extraction_run_id   TEXT NOT NULL REFERENCES extraction_runs(extraction_run_id) ON DELETE CASCADE,
    token_index         INTEGER NOT NULL,
    sentence_index      INTEGER NOT NULL,
    char_start          INTEGER NOT NULL,
    char_end            INTEGER NOT NULL,
    surface_text        TEXT NOT NULL,
    lemma_text          TEXT,
    pos_tag             TEXT,
    PRIMARY KEY(extraction_run_id, token_index),
    CHECK (char_start >= 0 AND char_end > char_start)
) STRICT;

CREATE TABLE mentions (
    mention_id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    extraction_run_id   TEXT NOT NULL REFERENCES extraction_runs(extraction_run_id) ON DELETE CASCADE,
    mention_type        TEXT NOT NULL REFERENCES mention_type_definitions(mention_type),
    sentence_index      INTEGER,
    char_start          INTEGER NOT NULL,
    char_end            INTEGER NOT NULL,
    token_start         INTEGER,
    token_end           INTEGER,
    surface_text        TEXT NOT NULL,
    surface_sha256      TEXT CHECK (surface_sha256 IS NULL OR length(surface_sha256) = 64),
    normalized_text     TEXT,
    parser_payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(parser_payload_json)),
    confidence          REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                          'UNREVIEWED','ACCEPTED','REJECTED','CORRECTED'
                        )),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(extraction_run_id, char_start, char_end, mention_type),
    CHECK (char_start >= 0 AND char_end > char_start),
    CHECK (token_end IS NULL OR token_start IS NULL OR token_end >= token_start)
) STRICT;

-- Optional discontinuous span fragments; fragment 0 may duplicate the main span.
CREATE TABLE mention_fragments (
    mention_id          TEXT NOT NULL REFERENCES mentions(mention_id) ON DELETE CASCADE,
    fragment_no         INTEGER NOT NULL CHECK (fragment_no >= 0),
    char_start          INTEGER NOT NULL,
    char_end            INTEGER NOT NULL,
    surface_text        TEXT NOT NULL,
    PRIMARY KEY(mention_id, fragment_no),
    CHECK (char_start >= 0 AND char_end > char_start)
) STRICT;

CREATE TABLE mention_values (
    mention_id          TEXT PRIMARY KEY REFERENCES mentions(mention_id) ON DELETE CASCADE,
    value_kind          TEXT NOT NULL CHECK (value_kind IN (
                          'TEXT','NUMBER','MONEY','AREA','DATE','DATETIME','PERCENT',
                          'COUNT','DURATION','BOOLEAN','JSON'
                        )),
    raw_value           TEXT NOT NULL,
    text_value          TEXT,
    numeric_value       REAL,
    value_decimal_text  TEXT,
    lower_decimal_text  TEXT,
    upper_decimal_text  TEXT,
    comparator_code     TEXT NOT NULL DEFAULT 'EXACT' CHECK (comparator_code IN (
                          'EXACT','ABOUT','AT_LEAST','AT_MOST','GREATER_THAN','LESS_THAN','RANGE'
                        )),
    integer_value       INTEGER,
    date_start          TEXT,
    date_end            TEXT,
    date_precision      TEXT CHECK (date_precision IS NULL OR date_precision IN (
                          'DAY','MONTH','QUARTER','HALF_YEAR','YEAR','RANGE','RELATIVE','UNKNOWN'
                        )),
    currency_code       TEXT,
    unit_code           TEXT REFERENCES units(unit_code),
    normalized_unit_code TEXT REFERENCES units(unit_code),
    normalization_version TEXT,
    normalized_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(normalized_json)),
    CHECK (comparator_code <> 'RANGE' OR
           (lower_decimal_text IS NOT NULL AND upper_decimal_text IS NOT NULL)),
    CHECK (date_end IS NULL OR date_start IS NULL OR date_end >= date_start)
) STRICT;

CREATE TABLE mention_relations (
    mention_relation_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    extraction_run_id   TEXT NOT NULL REFERENCES extraction_runs(extraction_run_id) ON DELETE CASCADE,
    subject_mention_id  TEXT NOT NULL REFERENCES mentions(mention_id),
    relation_code       TEXT NOT NULL,
    object_mention_id   TEXT NOT NULL REFERENCES mentions(mention_id),
    evidence_start      INTEGER,
    evidence_end        INTEGER,
    confidence          REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    extraction_method   TEXT NOT NULL CHECK (extraction_method IN (
                          'RULE','MODEL','API','MANUAL'
                        )),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                          'UNREVIEWED','ACCEPTED','REJECTED','CORRECTED'
                        )),
    UNIQUE(extraction_run_id, subject_mention_id, relation_code, object_mention_id),
    CHECK (subject_mention_id <> object_mention_id),
    CHECK (evidence_end IS NULL OR evidence_start IS NULL OR evidence_end > evidence_start)
) STRICT;

CREATE TABLE mention_resolutions (
    mention_resolution_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    mention_id          TEXT NOT NULL REFERENCES mentions(mention_id) ON DELETE CASCADE,
    target_kind        TEXT NOT NULL CHECK (target_kind IN (
                          'ASSET','PROJECT','ORGANIZATION','REGION','ASSET_CLASS'
                        )),
    asset_id           TEXT REFERENCES assets(asset_id),
    project_id         TEXT REFERENCES projects(project_id),
    organization_id    TEXT REFERENCES organizations(organization_id),
    region_id          TEXT REFERENCES regions(region_id),
    asset_class_id     TEXT REFERENCES asset_classes(asset_class_id),
    resolution_status  TEXT NOT NULL CHECK (resolution_status IN (
                          'CANDIDATE','RESOLVED','AMBIGUOUS','REJECTED'
                        )),
    match_score        REAL CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 1),
    match_features_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(match_features_json)),
    method_code        TEXT NOT NULL CHECK (method_code IN (
                          'EXACT_ID','ADDRESS','ALIAS','SPATIAL','COMPOSITE','MANUAL'
                        )),
    selected           INTEGER NOT NULL DEFAULT 0 CHECK (selected IN (0,1)),
    reviewed_by        TEXT,
    reviewed_at        TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((asset_id IS NOT NULL) + (project_id IS NOT NULL) +
           (organization_id IS NOT NULL) + (region_id IS NOT NULL) +
           (asset_class_id IS NOT NULL) = 1)
) STRICT;

CREATE UNIQUE INDEX uq_selected_mention_resolution
    ON mention_resolutions(mention_id) WHERE selected = 1;

-- ============================================================================
-- 5. Document event mentions, typed claims and canonical events
-- ============================================================================

CREATE TABLE event_mentions (
    event_mention_id    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    extraction_run_id   TEXT NOT NULL REFERENCES extraction_runs(extraction_run_id) ON DELETE CASCADE,
    extraction_key      TEXT NOT NULL,
    event_category_id   TEXT REFERENCES event_categories(event_category_id),
    stage_code_hint     TEXT REFERENCES event_stages(stage_code),
    title_raw           TEXT,
    summary_raw         TEXT,
    evidence_start      INTEGER,
    evidence_end        INTEGER,
    event_date_start    TEXT,
    event_date_end      TEXT,
    date_precision      TEXT CHECK (date_precision IS NULL OR date_precision IN (
                          'DAY','MONTH','QUARTER','HALF_YEAR','YEAR','RANGE','RELATIVE','UNKNOWN'
                        )),
    confidence          REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status_code         TEXT NOT NULL DEFAULT 'EXTRACTED' CHECK (status_code IN (
                          'EXTRACTED','RESOLUTION_REQUIRED','REVIEW_READY',
                          'APPROVED','REJECTED','MERGED'
                        )),
    rejection_code      TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(extraction_run_id, extraction_key),
    CHECK (evidence_end IS NULL OR evidence_start IS NULL OR evidence_end > evidence_start),
    CHECK (event_date_end IS NULL OR event_date_start IS NULL OR event_date_end >= event_date_start)
) STRICT;

CREATE TABLE event_mention_members (
    event_mention_id    TEXT NOT NULL REFERENCES event_mentions(event_mention_id) ON DELETE CASCADE,
    mention_id          TEXT NOT NULL REFERENCES mentions(mention_id),
    semantic_role       TEXT NOT NULL,
    is_primary          INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    PRIMARY KEY(event_mention_id, mention_id, semantic_role)
) STRICT;

CREATE TABLE claims (
    claim_id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    event_mention_id    TEXT NOT NULL REFERENCES event_mentions(event_mention_id) ON DELETE CASCADE,
    predicate_code      TEXT NOT NULL REFERENCES predicate_definitions(predicate_code),
    subject_mention_id  TEXT REFERENCES mentions(mention_id),
    object_mention_id   TEXT REFERENCES mentions(mention_id),
    value_kind          TEXT NOT NULL CHECK (value_kind IN (
                          'TEXT','NUMBER','MONEY','AREA','DATE','DATETIME','PERCENT',
                          'COUNT','DURATION','BOOLEAN','ASSET_REF','ASSET_CLASS_REF','PROJECT_REF',
                          'ORGANIZATION_REF','REGION_REF','JSON'
                        )),
    raw_value           TEXT NOT NULL,
    text_value          TEXT,
    numeric_value       REAL,
    value_decimal_text  TEXT,
    lower_decimal_text  TEXT,
    upper_decimal_text  TEXT,
    comparator_code     TEXT NOT NULL DEFAULT 'EXACT' CHECK (comparator_code IN (
                          'EXACT','ABOUT','AT_LEAST','AT_MOST','GREATER_THAN','LESS_THAN','RANGE'
                        )),
    integer_value       INTEGER,
    date_start          TEXT,
    date_end            TEXT,
    date_precision      TEXT CHECK (date_precision IS NULL OR date_precision IN (
                          'DAY','MONTH','QUARTER','HALF_YEAR','YEAR','RANGE','RELATIVE','UNKNOWN'
                        )),
    currency_code       TEXT,
    unit_code           TEXT REFERENCES units(unit_code),
    normalized_unit_code TEXT REFERENCES units(unit_code),
    normalization_version TEXT,
    object_asset_id     TEXT REFERENCES assets(asset_id),
    object_asset_class_id TEXT REFERENCES asset_classes(asset_class_id),
    object_project_id   TEXT REFERENCES projects(project_id),
    object_organization_id TEXT REFERENCES organizations(organization_id),
    object_region_id    TEXT REFERENCES regions(region_id),
    value_qualifier     TEXT,
    certainty_code      TEXT NOT NULL DEFAULT 'REPORTED' CHECK (certainty_code IN (
                          'ACTUAL','OFFICIAL_PLAN','PARTY_PLAN','REPORTED','ESTIMATED','INFERRED'
                        )),
    valid_time_start    TEXT,
    valid_time_end      TEXT,
    evidence_start      INTEGER,
    evidence_end        INTEGER,
    confidence          REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (verification_status IN (
                          'UNVERIFIED','PENDING','VERIFIED','CONTRADICTED','INCONCLUSIVE'
                        )),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                          'UNREVIEWED','ACCEPTED','REJECTED','SUPERSEDED','CORRECTED'
                        )),
    extraction_method   TEXT NOT NULL CHECK (extraction_method IN (
                          'RULE','MODEL','API','MANUAL','CALCULATED'
                        )),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (date_end IS NULL OR date_start IS NULL OR date_end >= date_start),
    CHECK (comparator_code <> 'RANGE' OR
           (lower_decimal_text IS NOT NULL AND upper_decimal_text IS NOT NULL)),
    CHECK (valid_time_end IS NULL OR valid_time_start IS NULL OR valid_time_end >= valid_time_start),
    CHECK (evidence_end IS NULL OR evidence_start IS NULL OR evidence_end > evidence_start),
    CHECK ((object_asset_id IS NOT NULL) + (object_asset_class_id IS NOT NULL) +
           (object_project_id IS NOT NULL) + (object_organization_id IS NOT NULL) +
           (object_region_id IS NOT NULL) <= 1)
) STRICT;

-- N-ary semantic arguments prevent a transaction claim from collapsing into a
-- single subject/object pair. Source mentions remain the preferred arguments.
CREATE TABLE claim_role_definitions (
    role_code           TEXT PRIMARY KEY,
    name_ko             TEXT NOT NULL,
    allowed_kind        TEXT NOT NULL CHECK (allowed_kind IN (
                          'MENTION','ENTITY','TEXT','NUMBER','DATE','EVENT_MENTION','ANY'
                        )),
    description         TEXT
) STRICT;

CREATE TABLE claim_arguments (
    claim_argument_id   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    claim_id            TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    role_code           TEXT NOT NULL REFERENCES claim_role_definitions(role_code),
    ordinal             INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    argument_kind       TEXT NOT NULL CHECK (argument_kind IN (
                          'MENTION','ENTITY','TEXT','NUMBER','DATE','EVENT_MENTION'
                        )),
    mention_id          TEXT REFERENCES mentions(mention_id),
    event_mention_argument_id TEXT REFERENCES event_mentions(event_mention_id),
    asset_id            TEXT REFERENCES assets(asset_id),
    asset_class_id      TEXT REFERENCES asset_classes(asset_class_id),
    project_id          TEXT REFERENCES projects(project_id),
    organization_id     TEXT REFERENCES organizations(organization_id),
    region_id           TEXT REFERENCES regions(region_id),
    text_value          TEXT,
    value_decimal_text  TEXT,
    date_start          TEXT,
    date_end            TEXT,
    unit_code           TEXT REFERENCES units(unit_code),
    confidence          REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    UNIQUE(claim_id, role_code, ordinal),
    CHECK (date_end IS NULL OR date_start IS NULL OR date_end >= date_start),
    CHECK (
      (argument_kind = 'MENTION' AND mention_id IS NOT NULL AND
       event_mention_argument_id IS NULL AND asset_id IS NULL AND asset_class_id IS NULL AND
       project_id IS NULL AND organization_id IS NULL AND region_id IS NULL AND
       text_value IS NULL AND value_decimal_text IS NULL AND date_start IS NULL)
      OR
      (argument_kind = 'EVENT_MENTION' AND event_mention_argument_id IS NOT NULL AND
       mention_id IS NULL AND asset_id IS NULL AND asset_class_id IS NULL AND
       project_id IS NULL AND organization_id IS NULL AND region_id IS NULL AND
       text_value IS NULL AND value_decimal_text IS NULL AND date_start IS NULL)
      OR
      (argument_kind = 'ENTITY' AND mention_id IS NULL AND event_mention_argument_id IS NULL AND
       ((asset_id IS NOT NULL) + (asset_class_id IS NOT NULL) + (project_id IS NOT NULL) +
        (organization_id IS NOT NULL) + (region_id IS NOT NULL) = 1) AND
       text_value IS NULL AND value_decimal_text IS NULL AND date_start IS NULL)
      OR
      (argument_kind = 'TEXT' AND text_value IS NOT NULL AND mention_id IS NULL AND
       event_mention_argument_id IS NULL AND asset_id IS NULL AND asset_class_id IS NULL AND
       project_id IS NULL AND organization_id IS NULL AND region_id IS NULL AND
       value_decimal_text IS NULL AND date_start IS NULL)
      OR
      (argument_kind = 'NUMBER' AND value_decimal_text IS NOT NULL AND mention_id IS NULL AND
       event_mention_argument_id IS NULL AND asset_id IS NULL AND asset_class_id IS NULL AND
       project_id IS NULL AND organization_id IS NULL AND region_id IS NULL AND
       text_value IS NULL AND date_start IS NULL)
      OR
      (argument_kind = 'DATE' AND date_start IS NOT NULL AND mention_id IS NULL AND
       event_mention_argument_id IS NULL AND asset_id IS NULL AND asset_class_id IS NULL AND
       project_id IS NULL AND organization_id IS NULL AND region_id IS NULL AND
       text_value IS NULL AND value_decimal_text IS NULL)
    )
) STRICT;

CREATE TABLE claim_evidence (
    claim_id            TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    mention_id          TEXT NOT NULL REFERENCES mentions(mention_id),
    evidence_role       TEXT NOT NULL CHECK (evidence_role IN (
                          'DIRECT','CONTEXT','ATTRIBUTION','CONTRADICTION','QUALIFIER'
                        )),
    PRIMARY KEY(claim_id, mention_id, evidence_role)
) STRICT;

CREATE INDEX ix_claims_lp_manager_assessment
    ON claims(predicate_code,review_status,verification_status)
    WHERE predicate_code IN (
      'LP_MANDATE_MANAGER_BID_PARTICIPANT',
      'LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT'
    );

CREATE INDEX ix_claim_arguments_mandate_assessment
    ON claim_arguments(role_code,text_value,claim_id)
    WHERE role_code IN ('MANDATE_CODE','MANDATE_TRACK','FOLLOW_UP_ACTION','FUNDING_BASIS');

CREATE TABLE events (
    event_id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    canonical_title     TEXT NOT NULL,
    primary_category_id TEXT REFERENCES event_categories(event_category_id),
    current_stage_code  TEXT REFERENCES event_stages(stage_code),
    event_date_start    TEXT,
    event_date_end      TEXT,
    date_precision      TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (date_precision IN (
                          'DAY','MONTH','QUARTER','HALF_YEAR','YEAR','RANGE','RELATIVE','UNKNOWN'
                        )),
    lifecycle_status    TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (lifecycle_status IN (
                          'DRAFT','ACTIVE','COMPLETED','WITHDRAWN','REJECTED','MERGED'
                        )),
    verification_level  TEXT NOT NULL DEFAULT 'V0' CHECK (verification_level IN (
                          'V0','V1','V2','V3','V4'
                        )),
    overall_confidence  REAL CHECK (overall_confidence IS NULL OR overall_confidence BETWEEN 0 AND 1),
    merged_into_id      TEXT REFERENCES events(event_id),
    approved_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (event_date_end IS NULL OR event_date_start IS NULL OR event_date_end >= event_date_start),
    CHECK ((lifecycle_status = 'MERGED' AND merged_into_id IS NOT NULL)
        OR (lifecycle_status <> 'MERGED' AND merged_into_id IS NULL)),
    CHECK (merged_into_id IS NULL OR merged_into_id <> event_id)
) STRICT;

CREATE TABLE event_mention_links (
    event_mention_id    TEXT NOT NULL REFERENCES event_mentions(event_mention_id),
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    relation_code       TEXT NOT NULL CHECK (relation_code IN (
                          'PRIMARY','SUPPORTING','DUPLICATE','CORRECTION','SPLIT_SOURCE'
                        )),
    linked_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(event_mention_id, event_id, relation_code)
) STRICT;

CREATE UNIQUE INDEX uq_event_mention_primary_link
    ON event_mention_links(event_mention_id) WHERE relation_code = 'PRIMARY';

CREATE TABLE event_assets (
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    asset_id            TEXT NOT NULL REFERENCES assets(asset_id),
    role_code           TEXT NOT NULL CHECK (role_code IN (
                          'SUBJECT','PORTFOLIO_MEMBER','COLLATERAL','LEASED_ASSET',
                          'DEVELOPMENT_SITE','RESULTING_ASSET','RELATED'
                        )),
    confidence          REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    supporting_claim_id TEXT REFERENCES claims(claim_id),
    PRIMARY KEY(event_id, asset_id, role_code)
) STRICT;

CREATE TABLE event_projects (
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    role_code           TEXT NOT NULL CHECK (role_code IN (
                          'SUBJECT','FINANCED_PROJECT','PERMITTED_PROJECT','SUPPLY_PROJECT','RELATED'
                        )),
    confidence          REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    supporting_claim_id TEXT REFERENCES claims(claim_id),
    PRIMARY KEY(event_id, project_id, role_code)
) STRICT;

CREATE TABLE event_participants (
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    organization_id     TEXT NOT NULL REFERENCES organizations(organization_id),
    role_code           TEXT NOT NULL,
    valid_from          TEXT,
    valid_to            TEXT,
    confidence          REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    supporting_claim_id TEXT REFERENCES claims(claim_id),
    PRIMARY KEY(event_id, organization_id, role_code),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE event_transitions (
    event_transition_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    from_stage_code     TEXT REFERENCES event_stages(stage_code),
    to_stage_code       TEXT NOT NULL REFERENCES event_stages(stage_code),
    source_event_mention_id TEXT NOT NULL REFERENCES event_mentions(event_mention_id),
    announced_at        TEXT,
    effective_date      TEXT,
    expected_date       TEXT,
    date_precision      TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (date_precision IN (
                          'DAY','MONTH','QUARTER','HALF_YEAR','YEAR','RANGE','RELATIVE','UNKNOWN'
                        )),
    transition_status   TEXT NOT NULL DEFAULT 'REPORTED' CHECK (transition_status IN (
                          'REPORTED','VERIFIED','CONTRADICTED','SUPERSEDED','REVOKED'
                        )),
    confidence          REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                          'UNREVIEWED','APPROVED','REJECTED','CHANGES_REQUESTED'
                        )),
    approved_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(event_id, to_stage_code, source_event_mention_id, effective_date)
) STRICT;

-- ============================================================================
-- 5A. Competitive sale process, bid and acquisition-funding evidence (V2.3)
-- ============================================================================

-- A canonical SALE event may have one competitive sale-process extension.
-- Source mentions and claims remain the evidence authority; these tables organize
-- round-specific competition without collapsing reported claims into selected facts.
CREATE TABLE sale_processes (
    sale_process_id    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    event_id           TEXT NOT NULL UNIQUE REFERENCES events(event_id),
    process_code       TEXT NOT NULL UNIQUE,

    sale_method        TEXT NOT NULL CHECK (sale_method IN (
                         'COMPETITIVE_BID','PRIVATE_TREATY','PUBLIC_AUCTION',
                         'COURT_AUCTION','SHARE_SALE','OTHER'
                       )),
    process_status     TEXT NOT NULL DEFAULT 'DISCOVERY' CHECK (process_status IN (
                         'DISCOVERY','MANDATE','MARKETING','BIDDING','SHORTLIST',
                         'PREFERRED_NEGOTIATION','CONTRACTED','CONDITIONS_PENDING',
                         'CLOSED','FAILED','WITHDRAWN','REBID'
                       )),
    launched_at        TEXT,
    closed_at          TEXT,
    currency_code      TEXT NOT NULL DEFAULT 'KRW',
    evidence_status    TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                         'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                       )),
    source_claim_id    TEXT REFERENCES claims(claim_id),
    review_status      TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                         'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                       )),
    metadata_json      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (closed_at IS NULL OR launched_at IS NULL OR closed_at >= launched_at),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE sale_process_relations (
    sale_process_relation_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    from_sale_process_id TEXT NOT NULL REFERENCES sale_processes(sale_process_id) ON DELETE CASCADE,
    to_sale_process_id   TEXT NOT NULL REFERENCES sale_processes(sale_process_id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL CHECK (relation_type IN (
                          'RELAUNCHED_AS','PREVIOUS_ATTEMPT','SUCCESSOR_ATTEMPT',
                          'PREFERRED_SWITCH_CONTINUATION','PACKAGE_COMPONENT_OF',
                          'STRUCTURE_CHANGED_TO','DUPLICATE_OF','OTHER'
                        )),
    evidence_status     TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                          'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                        )),
    source_claim_id     TEXT REFERENCES claims(claim_id),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                          'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                        )),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(from_sale_process_id,to_sale_process_id,relation_type),
    CHECK (from_sale_process_id <> to_sale_process_id),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE sale_process_roles (
    process_role_id    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    sale_process_id    TEXT NOT NULL REFERENCES sale_processes(sale_process_id) ON DELETE CASCADE,
    organization_id    TEXT NOT NULL REFERENCES organizations(organization_id),
    role_code          TEXT NOT NULL CHECK (role_code IN (
                         'SELLER','OWNER','SELL_SIDE_ADVISOR','BUY_SIDE_ADVISOR',
                         'LEGAL_ADVISOR','FINANCIAL_ADVISOR','DEBT_ARRANGER',
                         'APPRAISER','TRUSTEE','SERVICER','OTHER'
                       )),
    valid_from         TEXT,
    valid_to           TEXT,
    evidence_status    TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                         'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                       )),
    source_claim_id    TEXT REFERENCES claims(claim_id),
    review_status      TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                         'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                       )),
    metadata_json      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE UNIQUE INDEX uq_sale_process_role
    ON sale_process_roles(sale_process_id,organization_id,role_code,coalesce(valid_from,''));

CREATE TABLE bid_rounds (
    bid_round_id       TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    sale_process_id    TEXT NOT NULL REFERENCES sale_processes(sale_process_id) ON DELETE CASCADE,
    round_no           INTEGER NOT NULL CHECK (round_no >= 1),
    round_code         TEXT NOT NULL,
    round_type         TEXT NOT NULL CHECK (round_type IN (
                         'INDICATION_OF_INTEREST','PRELIMINARY','SHORTLIST_CONFIRMATION',
                         'FINAL','REBID','BEST_AND_FINAL','OTHER'
                       )),
    invited_at         TEXT,
    deadline_at        TEXT,
    announced_at       TEXT,
    round_status       TEXT NOT NULL DEFAULT 'REPORTED' CHECK (round_status IN (
                         'PLANNED','OPEN','COMPLETED','CANCELLED','SUPERSEDED','REPORTED'
                       )),
    evidence_status    TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                         'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                       )),
    source_claim_id    TEXT REFERENCES claims(claim_id),
    review_status      TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                         'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                       )),
    metadata_json      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(sale_process_id,round_no),
    UNIQUE(sale_process_id,round_code),
    CHECK (deadline_at IS NULL OR invited_at IS NULL OR deadline_at >= invited_at),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE bidder_participations (
    participation_id       TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    bid_round_id           TEXT NOT NULL REFERENCES bid_rounds(bid_round_id) ON DELETE CASCADE,
    bidder_organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    participation_status   TEXT NOT NULL CHECK (participation_status IN (
                             'INTEREST_REPORTED','IM_RECEIVED','PRELIMINARY_BID_SUBMITTED',
                             'FINAL_BID_SUBMITTED','SHORTLISTED','NOT_SHORTLISTED',
                             'WITHDREW','PREFERRED','RESERVE_BIDDER','LOST','UNKNOWN'
                           )),
    status_as_of            TEXT,
    evidence_status         TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                             'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                           )),
    source_claim_id         TEXT REFERENCES claims(claim_id),
    review_status           TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                             'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                           )),
    confidence              REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json           TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(bid_round_id,bidder_organization_id),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE bidder_participation_members (
    participation_member_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    participation_id        TEXT NOT NULL REFERENCES bidder_participations(participation_id) ON DELETE CASCADE,
    organization_id         TEXT NOT NULL REFERENCES organizations(organization_id),
    member_role             TEXT NOT NULL CHECK (member_role IN (
                              'LEAD_BIDDER','CONSORTIUM_MEMBER','ASSET_MANAGER','MANAGED_FUND',
                              'REIT','ACQUISITION_VEHICLE','STRATEGIC_INVESTOR',
                              'FINANCIAL_INVESTOR','CO_INVESTOR'
                            )),
    ownership_percent_decimal TEXT,
    evidence_status          TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                              'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                            )),
    source_claim_id          TEXT REFERENCES claims(claim_id),
    review_status            TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                              'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                            )),
    metadata_json            TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(participation_id,organization_id,member_role),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE bid_submissions (
    bid_submission_id    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    participation_id     TEXT NOT NULL REFERENCES bidder_participations(participation_id) ON DELETE CASCADE,
    submission_no        INTEGER NOT NULL DEFAULT 1 CHECK (submission_no >= 1),
    submitted_at         TEXT,
    bid_amount_decimal   TEXT,
    currency_code        TEXT,
    comparator_code      TEXT NOT NULL DEFAULT 'EXACT' CHECK (comparator_code IN (
                           'EXACT','ABOUT','AT_LEAST','AT_MOST','GREATER_THAN','LESS_THAN','RANGE','UNKNOWN'
                         )),
    amount_precision     TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (amount_precision IN (
                           'EXACT','ROUNDED','REPORTED_RANGE','RELATIVE_ONLY','UNKNOWN'
                         )),
    lower_amount_decimal TEXT,
    upper_amount_decimal TEXT,
    price_basis          TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (price_basis IN (
                           'TOTAL_CONSIDERATION','EQUITY_VALUE','ENTERPRISE_VALUE',
                           'PRICE_PER_PYEONG','PRICE_PER_M2','UNKNOWN'
                         )),
    vat_inclusion        TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (vat_inclusion IN ('INCLUDED','EXCLUDED','UNKNOWN')),
    debt_assumption      TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (debt_assumption IN ('INCLUDED','EXCLUDED','UNKNOWN')),
    financing_condition TEXT,
    due_diligence_condition TEXT,
    closing_condition   TEXT,
    conditions_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(conditions_json)),
    reported_rank       INTEGER CHECK (reported_rank IS NULL OR reported_rank >= 1),
    rank_scope          TEXT,
    rank_as_of          TEXT,
    evidence_status     TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                           'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                         )),
    source_claim_id     TEXT REFERENCES claims(claim_id),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                           'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                         )),
    confidence          REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(participation_id,submission_no),
    CHECK (comparator_code <> 'RANGE' OR (lower_amount_decimal IS NOT NULL AND upper_amount_decimal IS NOT NULL)),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE bid_funding_components (
    funding_component_id     TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    bid_submission_id        TEXT NOT NULL REFERENCES bid_submissions(bid_submission_id) ON DELETE CASCADE,
    funding_type             TEXT NOT NULL CHECK (funding_type IN (
                               'OWN_BALANCE_SHEET','BLIND_FUND_EQUITY','PROJECT_FUND_EQUITY',
                               'REIT_EQUITY','LP_EQUITY','CO_INVESTMENT','ACQUISITION_DEBT',
                               'BRIDGE_DEBT','MEZZANINE','SELLER_FINANCING','OTHER','UNKNOWN'
                             )),
    provider_organization_id TEXT REFERENCES organizations(organization_id),
    recipient_vehicle_id     TEXT REFERENCES organizations(organization_id),
    amount_decimal           TEXT,
    currency_code            TEXT,
    comparator_code          TEXT NOT NULL DEFAULT 'EXACT' CHECK (comparator_code IN (
                               'EXACT','ABOUT','AT_LEAST','AT_MOST','GREATER_THAN','LESS_THAN','RANGE','UNKNOWN'
                             )),
    lower_amount_decimal     TEXT,
    upper_amount_decimal     TEXT,
    commitment_status        TEXT NOT NULL DEFAULT 'REPORTED' CHECK (commitment_status IN (
                               'RUMORED','PLANNED','INDICATIVE','COMMITTED','EXECUTED','WITHDRAWN','REPORTED','UNKNOWN'
                             )),
    evidence_status          TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id          TEXT REFERENCES claims(claim_id),
    review_status            TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    confidence               REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json            TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (provider_organization_id IS NOT NULL OR recipient_vehicle_id IS NOT NULL OR funding_type='UNKNOWN'),
    CHECK (comparator_code <> 'RANGE' OR (lower_amount_decimal IS NOT NULL AND upper_amount_decimal IS NOT NULL)),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE bid_decisions (
    bid_decision_id       TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    sale_process_id       TEXT NOT NULL REFERENCES sale_processes(sale_process_id) ON DELETE CASCADE,
    bid_round_id          TEXT REFERENCES bid_rounds(bid_round_id),
    participation_id      TEXT REFERENCES bidder_participations(participation_id),
    decision_type         TEXT NOT NULL CHECK (decision_type IN (
                            'SHORTLISTED','NOT_SHORTLISTED','PREFERRED','RESERVE','SELECTED','NOT_SELECTED'
                          )),
    decision_date         TEXT,
    decision_status       TEXT NOT NULL DEFAULT 'REPORTED' CHECK (decision_status IN (
                            'REPORTED','CURRENT','VERIFIED','SUPERSEDED','REVOKED','CONTRADICTED'
                          )),
    source_reason         TEXT,
    price_evaluation      TEXT,
    non_price_evaluation  TEXT,
    supersedes_decision_id TEXT REFERENCES bid_decisions(bid_decision_id),
    evidence_status       TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                            'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                          )),
    source_claim_id       TEXT REFERENCES claims(claim_id),
    review_status         TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                            'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                          )),
    confidence            REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (supersedes_decision_id IS NULL OR supersedes_decision_id <> bid_decision_id),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE UNIQUE INDEX uq_current_preferred_decision
    ON bid_decisions(sale_process_id)
    WHERE decision_type='PREFERRED' AND decision_status IN ('CURRENT','VERIFIED');

CREATE TABLE transaction_milestones (
    milestone_id        TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    sale_process_id     TEXT NOT NULL REFERENCES sale_processes(sale_process_id) ON DELETE CASCADE,
    milestone_code      TEXT NOT NULL CHECK (milestone_code IN (
                           'MOU_SIGNED','EXCLUSIVITY_GRANTED','DUE_DILIGENCE_STARTED',
                           'DUE_DILIGENCE_COMPLETED','SPA_SIGNED','DEPOSIT_PAID',
                           'FINANCING_COMMITTED','REGULATORY_APPROVED','CONDITIONS_SATISFIED',
                           'BALANCE_PAID','OWNERSHIP_TRANSFERRED','MOLIT_FILED','CLOSED',
                           'NEGOTIATION_FAILED','CONTRACT_TERMINATED','WITHDRAWN','REBID'
                         )),
    milestone_status    TEXT NOT NULL DEFAULT 'REPORTED' CHECK (milestone_status IN (
                           'PLANNED','REPORTED','CONFIRMED','SUPERSEDED','REVOKED','FAILED'
                         )),
    announced_at        TEXT,
    effective_date      TEXT,
    expected_date       TEXT,
    source_note         TEXT,
    supersedes_milestone_id TEXT REFERENCES transaction_milestones(milestone_id),
    evidence_status     TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                           'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                         )),
    source_claim_id     TEXT REFERENCES claims(claim_id),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                           'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                         )),
    confidence          REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (supersedes_milestone_id IS NULL OR supersedes_milestone_id <> milestone_id),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE INDEX ix_sale_process_status ON sale_processes(process_status,launched_at);
CREATE INDEX ix_sale_roles_org ON sale_process_roles(organization_id,role_code,sale_process_id);
CREATE INDEX ix_bid_round_process ON bid_rounds(sale_process_id,round_no);
CREATE INDEX ix_participation_bidder ON bidder_participations(bidder_organization_id,bid_round_id);
CREATE INDEX ix_bid_submission_rank ON bid_submissions(participation_id,reported_rank);
CREATE INDEX ix_bid_funding_provider ON bid_funding_components(provider_organization_id,funding_type);
CREATE INDEX ix_bid_decision_process ON bid_decisions(sale_process_id,decision_date);
CREATE INDEX ix_milestone_process_date ON transaction_milestones(sale_process_id,effective_date,announced_at);

-- A selected fact points to one source claim. Historical and conflicting claims remain.
CREATE TABLE fact_selections (
    fact_selection_id   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    predicate_code      TEXT NOT NULL REFERENCES predicate_definitions(predicate_code),
    slot_key            TEXT NOT NULL DEFAULT 'default',
    event_id            TEXT REFERENCES events(event_id),
    asset_id            TEXT REFERENCES assets(asset_id),
    project_id          TEXT REFERENCES projects(project_id),
    organization_id     TEXT REFERENCES organizations(organization_id),
    selected_claim_id   TEXT NOT NULL REFERENCES claims(claim_id),
    valid_from          TEXT,
    valid_to            TEXT,
    selection_status    TEXT NOT NULL DEFAULT 'CURRENT' CHECK (selection_status IN (
                          'CURRENT','SUPERSEDED','REVOKED'
                        )),
    selected_by         TEXT NOT NULL,
    selected_at         TEXT NOT NULL,
    CHECK ((event_id IS NOT NULL) + (asset_id IS NOT NULL) +
           (project_id IS NOT NULL) + (organization_id IS NOT NULL) = 1),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE UNIQUE INDEX uq_current_event_fact
    ON fact_selections(event_id, predicate_code, slot_key)
    WHERE event_id IS NOT NULL AND selection_status = 'CURRENT';
CREATE UNIQUE INDEX uq_current_asset_fact
    ON fact_selections(asset_id, predicate_code, slot_key)
    WHERE asset_id IS NOT NULL AND selection_status = 'CURRENT';
CREATE UNIQUE INDEX uq_current_project_fact
    ON fact_selections(project_id, predicate_code, slot_key)
    WHERE project_id IS NOT NULL AND selection_status = 'CURRENT';
CREATE UNIQUE INDEX uq_current_org_fact
    ON fact_selections(organization_id, predicate_code, slot_key)
    WHERE organization_id IS NOT NULL AND selection_status = 'CURRENT';

-- ============================================================================
-- 6. Extensible measurements: definition + scope + dimensions + values
-- ============================================================================

CREATE TABLE measurement_facts (
    measurement_fact_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    measurement_definition_id TEXT NOT NULL REFERENCES measurement_definitions(measurement_definition_id),
    asset_id            TEXT REFERENCES assets(asset_id),
    project_id          TEXT REFERENCES projects(project_id),
    spatial_unit_id     TEXT REFERENCES spatial_units(spatial_unit_id),
    event_id            TEXT REFERENCES events(event_id),
    region_id           TEXT REFERENCES regions(region_id),
    source_claim_id     TEXT REFERENCES claims(claim_id),
    source_mention_id   TEXT REFERENCES mentions(mention_id),
    raw_value           TEXT NOT NULL,
    comparator_code     TEXT NOT NULL DEFAULT 'EXACT' CHECK (comparator_code IN (
                          'EXACT','ABOUT','AT_LEAST','AT_MOST','GREATER_THAN','LESS_THAN','RANGE'
                        )),
    value_decimal_text  TEXT,
    lower_decimal_text  TEXT,
    upper_decimal_text  TEXT,
    source_unit_code    TEXT NOT NULL REFERENCES units(unit_code),
    normalized_value_decimal_text TEXT,
    normalized_lower_decimal_text TEXT,
    normalized_upper_decimal_text TEXT,
    normalized_numeric_value REAL,
    normalized_unit_code TEXT NOT NULL REFERENCES units(unit_code),
    normalization_version TEXT,
    measurement_status TEXT NOT NULL CHECK (measurement_status IN (
                          'ACTUAL','REGISTERED','APPROVED','PLANNED','ESTIMATED',
                          'REPORTED','CALCULATED','SUPERSEDED','WITHDRAWN'
                        )),
    measurement_basis_code TEXT NOT NULL CHECK (measurement_basis_code IN (
                          'SOURCE_REPORTED','LEGAL_REGISTER','PERMIT_DOCUMENT','DESIGN_DOCUMENT',
                          'LEASE_DOCUMENT','OPERATIONAL_MEASURED','APPRAISAL','CALCULATED','OTHER'
                        )),
    observed_on         TEXT,
    valid_from          TEXT,
    valid_to            TEXT,
    confidence          REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (verification_status IN (
                          'UNVERIFIED','PENDING','VERIFIED','CONTRADICTED','INCONCLUSIVE'
                        )),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                          'UNREVIEWED','ACCEPTED','REJECTED','SUPERSEDED','CORRECTED'
                        )),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((asset_id IS NOT NULL) + (project_id IS NOT NULL) +
           (spatial_unit_id IS NOT NULL) + (event_id IS NOT NULL) +
           (region_id IS NOT NULL) = 1),
    CHECK (comparator_code <> 'RANGE' OR
           (lower_decimal_text IS NOT NULL AND upper_decimal_text IS NOT NULL)),
    CHECK (comparator_code = 'RANGE' OR value_decimal_text IS NOT NULL),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TRIGGER measurement_fact_unit_dimension_guard
BEFORE INSERT ON measurement_facts
WHEN EXISTS (
    SELECT 1
    FROM measurement_definitions d
    JOIN units source_u ON source_u.unit_code = NEW.source_unit_code
    JOIN units normalized_u ON normalized_u.unit_code = NEW.normalized_unit_code
    WHERE d.measurement_definition_id = NEW.measurement_definition_id
      AND (source_u.dimension_code <> d.dimension_code
           OR normalized_u.dimension_code <> d.dimension_code)
)
BEGIN SELECT RAISE(ABORT, 'measurement unit dimension mismatch'); END;

CREATE TABLE measurement_fact_dimensions (
    measurement_fact_dimension_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    measurement_fact_id TEXT NOT NULL REFERENCES measurement_facts(measurement_fact_id) ON DELETE CASCADE,
    measurement_dimension_id TEXT NOT NULL REFERENCES measurement_dimension_definitions(measurement_dimension_id),
    ordinal             INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    option_id           TEXT REFERENCES measurement_dimension_options(measurement_dimension_option_id),
    text_value          TEXT,
    decimal_value_text  TEXT,
    integer_value       INTEGER,
    boolean_value       INTEGER CHECK (boolean_value IS NULL OR boolean_value IN (0,1)),
    date_value          TEXT,
    spatial_unit_value_id TEXT REFERENCES spatial_units(spatial_unit_id),
    source_text         TEXT,
    UNIQUE(measurement_fact_id, measurement_dimension_id, ordinal),
    FOREIGN KEY(measurement_dimension_id, option_id)
      REFERENCES measurement_dimension_options(measurement_dimension_id, measurement_dimension_option_id),
    CHECK ((option_id IS NOT NULL) + (text_value IS NOT NULL) +
           (decimal_value_text IS NOT NULL) + (integer_value IS NOT NULL) +
           (boolean_value IS NOT NULL) + (date_value IS NOT NULL) +
           (spatial_unit_value_id IS NOT NULL) = 1)
) STRICT;

CREATE TRIGGER measurement_fact_dimension_kind_guard
BEFORE INSERT ON measurement_fact_dimensions
WHEN (
    SELECT value_kind
    FROM measurement_dimension_definitions
    WHERE measurement_dimension_id = NEW.measurement_dimension_id
) <> CASE
    WHEN NEW.option_id IS NOT NULL THEN 'OPTION'
    WHEN NEW.text_value IS NOT NULL THEN 'TEXT'
    WHEN NEW.decimal_value_text IS NOT NULL THEN 'DECIMAL'
    WHEN NEW.integer_value IS NOT NULL THEN 'INTEGER'
    WHEN NEW.boolean_value IS NOT NULL THEN 'BOOLEAN'
    WHEN NEW.date_value IS NOT NULL THEN 'DATE'
    WHEN NEW.spatial_unit_value_id IS NOT NULL THEN 'SPATIAL_UNIT'
END
BEGIN SELECT RAISE(ABORT, 'measurement dimension value kind mismatch'); END;

CREATE TABLE measurement_fact_selections (
    measurement_fact_selection_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    measurement_definition_id TEXT NOT NULL REFERENCES measurement_definitions(measurement_definition_id),
    slot_key            TEXT NOT NULL DEFAULT 'default',
    asset_id            TEXT REFERENCES assets(asset_id),
    project_id          TEXT REFERENCES projects(project_id),
    spatial_unit_id     TEXT REFERENCES spatial_units(spatial_unit_id),
    event_id            TEXT REFERENCES events(event_id),
    region_id           TEXT REFERENCES regions(region_id),
    selected_measurement_fact_id TEXT NOT NULL REFERENCES measurement_facts(measurement_fact_id),
    selection_status    TEXT NOT NULL DEFAULT 'CURRENT' CHECK (selection_status IN (
                          'CURRENT','SUPERSEDED','REVOKED'
                        )),
    selected_by         TEXT NOT NULL,
    selected_at         TEXT NOT NULL,
    selection_reason    TEXT,
    CHECK ((asset_id IS NOT NULL) + (project_id IS NOT NULL) +
           (spatial_unit_id IS NOT NULL) + (event_id IS NOT NULL) +
           (region_id IS NOT NULL) = 1)
) STRICT;

CREATE TRIGGER measurement_selection_target_guard
BEFORE INSERT ON measurement_fact_selections
WHEN NOT EXISTS (
    SELECT 1
    FROM measurement_facts f
    WHERE f.measurement_fact_id = NEW.selected_measurement_fact_id
      AND f.measurement_definition_id = NEW.measurement_definition_id
      AND f.asset_id IS NEW.asset_id
      AND f.project_id IS NEW.project_id
      AND f.spatial_unit_id IS NEW.spatial_unit_id
      AND f.event_id IS NEW.event_id
      AND f.region_id IS NEW.region_id
)
BEGIN SELECT RAISE(ABORT, 'selected measurement fact definition or target mismatch'); END;

CREATE UNIQUE INDEX uq_current_measurement_asset
    ON measurement_fact_selections(asset_id, measurement_definition_id, slot_key)
    WHERE asset_id IS NOT NULL AND selection_status = 'CURRENT';
CREATE UNIQUE INDEX uq_current_measurement_project
    ON measurement_fact_selections(project_id, measurement_definition_id, slot_key)
    WHERE project_id IS NOT NULL AND selection_status = 'CURRENT';
CREATE UNIQUE INDEX uq_current_measurement_spatial
    ON measurement_fact_selections(spatial_unit_id, measurement_definition_id, slot_key)
    WHERE spatial_unit_id IS NOT NULL AND selection_status = 'CURRENT';
CREATE UNIQUE INDEX uq_current_measurement_event
    ON measurement_fact_selections(event_id, measurement_definition_id, slot_key)
    WHERE event_id IS NOT NULL AND selection_status = 'CURRENT';
CREATE UNIQUE INDEX uq_current_measurement_region
    ON measurement_fact_selections(region_id, measurement_definition_id, slot_key)
    WHERE region_id IS NOT NULL AND selection_status = 'CURRENT';


CREATE TABLE measurement_derivations (
    measurement_derivation_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    output_measurement_fact_id TEXT NOT NULL UNIQUE REFERENCES measurement_facts(measurement_fact_id),
    method_code         TEXT NOT NULL CHECK (method_code IN (
                          'SUM','DIFFERENCE','RATIO','FORMULA','UNIT_CONVERSION','MANUAL_DERIVATION'
                        )),
    expression_text     TEXT,
    calculation_version TEXT NOT NULL,
    rounding_rule       TEXT,
    calculated_at       TEXT NOT NULL,
    calculated_by       TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE measurement_derivation_inputs (
    measurement_derivation_id TEXT NOT NULL REFERENCES measurement_derivations(measurement_derivation_id) ON DELETE CASCADE,
    input_measurement_fact_id TEXT NOT NULL REFERENCES measurement_facts(measurement_fact_id),
    input_role_code     TEXT NOT NULL CHECK (input_role_code IN (
                          'ADDEND','MINUEND','SUBTRAHEND','NUMERATOR','DENOMINATOR','SOURCE','REFERENCE'
                        )),
    ordinal             INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    weight_decimal_text TEXT,
    PRIMARY KEY(measurement_derivation_id, input_measurement_fact_id, input_role_code, ordinal)
) STRICT;

CREATE INDEX ix_measurement_facts_definition ON measurement_facts(measurement_definition_id, review_status, observed_on);
CREATE INDEX ix_measurement_facts_asset ON measurement_facts(asset_id, measurement_definition_id);
CREATE INDEX ix_measurement_facts_project ON measurement_facts(project_id, measurement_definition_id);
CREATE INDEX ix_measurement_facts_spatial ON measurement_facts(spatial_unit_id, measurement_definition_id);
CREATE INDEX ix_measurement_fact_dimensions_lookup ON measurement_fact_dimensions(measurement_dimension_id, option_id);

-- ============================================================================
-- 7. Macro and market time-series with non-destructive vintages
-- ============================================================================

CREATE TABLE macro_series (
    macro_series_id     TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    series_code         TEXT NOT NULL UNIQUE,
    series_name_ko      TEXT NOT NULL,
    metric_code         TEXT NOT NULL,
    source_id           TEXT REFERENCES collection_sources(source_id),
    external_series_key TEXT,
    frequency_code      TEXT NOT NULL CHECK (frequency_code IN (
                          'EVENT','DAILY','WEEKLY','MONTHLY','QUARTERLY','ANNUAL'
                        )),
    unit_code           TEXT NOT NULL REFERENCES units(unit_code),
    region_id           TEXT REFERENCES regions(region_id),
    asset_class_id      TEXT REFERENCES asset_classes(asset_class_id),
    adjustment_code     TEXT NOT NULL DEFAULT 'NONE' CHECK (adjustment_code IN (
                          'NONE','SEASONALLY_ADJUSTED','REAL','NOMINAL','INDEXED'
                        )),
    aggregation_code    TEXT,
    definition_text     TEXT NOT NULL,
    valid_from          TEXT,
    valid_to            TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE macro_releases (
    macro_release_id    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_id           TEXT NOT NULL REFERENCES collection_sources(source_id),
    publisher_release_key TEXT NOT NULL,
    release_title       TEXT,
    released_at         TEXT,
    effective_date      TEXT,
    artifact_sha256     TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    artifact_uri        TEXT,
    publisher_revision_no TEXT,
    revises_release_id  TEXT REFERENCES macro_releases(macro_release_id),
    first_collected_at  TEXT NOT NULL,
    source_document_version_id TEXT REFERENCES document_versions(document_version_id),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(source_id, publisher_release_key, artifact_sha256),
    CHECK (revises_release_id IS NULL OR revises_release_id <> macro_release_id)
) STRICT;

CREATE TABLE macro_observations (
    macro_observation_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    macro_series_id     TEXT NOT NULL REFERENCES macro_series(macro_series_id),
    macro_release_id    TEXT NOT NULL REFERENCES macro_releases(macro_release_id),
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    period_label        TEXT,
    observed_on         TEXT,
    numeric_value       REAL,
    value_decimal_text  TEXT,
    text_value          TEXT,
    unit_code           TEXT NOT NULL REFERENCES units(unit_code),
    collected_at        TEXT NOT NULL,
    vintage_at          TEXT NOT NULL,
    revision_no         INTEGER NOT NULL DEFAULT 0 CHECK (revision_no >= 0),
    observation_status  TEXT NOT NULL DEFAULT 'FINAL' CHECK (observation_status IN (
                          'PRELIMINARY','FINAL','REVISED','DISCONTINUED','MISSING',
                          'SUPPRESSED','WITHDRAWN'
                        )),
    source_document_version_id TEXT REFERENCES document_versions(document_version_id),
    source_record_key   TEXT,
    raw_value           TEXT,
    row_sha256          TEXT NOT NULL CHECK (length(row_sha256) = 64),
    supersedes_observation_id TEXT REFERENCES macro_observations(macro_observation_id),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(macro_series_id, period_start, period_end, macro_release_id),
    UNIQUE(macro_series_id, period_start, period_end, row_sha256),
    CHECK (period_end >= period_start),
    CHECK (supersedes_observation_id IS NULL OR supersedes_observation_id <> macro_observation_id),
    CHECK (
      observation_status IN ('MISSING','SUPPRESSED','WITHDRAWN')
      OR numeric_value IS NOT NULL OR value_decimal_text IS NOT NULL OR text_value IS NOT NULL
    )
) STRICT;

CREATE TRIGGER macro_observation_supersedes_guard
BEFORE INSERT ON macro_observations
WHEN NEW.supersedes_observation_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM macro_observations previous
        WHERE previous.macro_observation_id = NEW.supersedes_observation_id
          AND previous.macro_series_id = NEW.macro_series_id
          AND previous.period_start = NEW.period_start
          AND previous.period_end = NEW.period_end
    ) THEN RAISE(ABORT, 'superseded observation must have the same series and period') END;
END;

CREATE TRIGGER macro_release_no_update
BEFORE UPDATE ON macro_releases
BEGIN SELECT RAISE(ABORT, 'macro release is append-only'); END;
CREATE TRIGGER macro_release_no_delete
BEFORE DELETE ON macro_releases
BEGIN SELECT RAISE(ABORT, 'macro release is append-only'); END;
CREATE TRIGGER macro_observation_no_update
BEFORE UPDATE ON macro_observations
BEGIN SELECT RAISE(ABORT, 'macro observation is append-only; insert a revision'); END;
CREATE TRIGGER macro_observation_no_delete
BEFORE DELETE ON macro_observations
BEGIN SELECT RAISE(ABORT, 'macro observation is append-only'); END;

CREATE INDEX ix_macro_releases_source_time
    ON macro_releases(source_id, released_at, macro_release_id);
CREATE INDEX ix_macro_observations_series_period
    ON macro_observations(macro_series_id, period_start DESC, vintage_at DESC);
CREATE INDEX ix_macro_observations_release
    ON macro_observations(macro_release_id);

-- ============================================================================
-- 7. Daily/weekly immutable snapshots and aggregate metrics
-- ============================================================================

CREATE TABLE snapshots (
    snapshot_id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    snapshot_type       TEXT NOT NULL CHECK (snapshot_type IN (
                          'DAILY','WEEKLY','MONTHLY','MANUAL'
                        )),
    scheduled_for       TEXT,
    as_of_at            TEXT NOT NULL,
    as_of_basis         TEXT NOT NULL DEFAULT 'COLLECTION' CHECK (as_of_basis IN (
                          'COLLECTION','PUBLICATION'
                        )),
    collection_run_id   TEXT REFERENCES collection_runs(run_id),
    generator_version   TEXT NOT NULL,
    status_code         TEXT NOT NULL DEFAULT 'BUILDING' CHECK (status_code IN (
                          'BUILDING','COMPLETE','FAILED'
                        )),
    row_count           INTEGER CHECK (row_count IS NULL OR row_count >= 0),
    checksum_sha256     TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at        TEXT,
    UNIQUE(snapshot_type, as_of_at, generator_version)
) STRICT;

CREATE TRIGGER completed_snapshot_no_update
BEFORE UPDATE ON snapshots
WHEN OLD.status_code = 'COMPLETE'
BEGIN SELECT RAISE(ABORT, 'completed snapshot is immutable'); END;
CREATE TRIGGER snapshot_no_delete
BEFORE DELETE ON snapshots
BEGIN SELECT RAISE(ABORT, 'snapshot history is append-only'); END;

CREATE TABLE snapshot_macro_items (
    snapshot_id         TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    macro_observation_id TEXT NOT NULL REFERENCES macro_observations(macro_observation_id),
    PRIMARY KEY(snapshot_id, macro_observation_id)
) STRICT;

CREATE TABLE snapshot_event_states (
    snapshot_id         TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    stage_code          TEXT REFERENCES event_stages(stage_code),
    lifecycle_status    TEXT NOT NULL,
    verification_level  TEXT NOT NULL,
    overall_confidence  REAL,
    event_date_start    TEXT,
    captured_at         TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, event_id)
) STRICT;

CREATE TABLE snapshot_metrics (
    snapshot_metric_id  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    snapshot_id         TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    metric_code         TEXT NOT NULL,
    event_category_id   TEXT REFERENCES event_categories(event_category_id),
    region_id           TEXT REFERENCES regions(region_id),
    asset_class_id      TEXT REFERENCES asset_classes(asset_class_id),
    numeric_value       REAL NOT NULL,
    unit_code           TEXT NOT NULL REFERENCES units(unit_code),
    dimension_json      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(dimension_json)),
    calculation_version TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(snapshot_id, metric_code, event_category_id, region_id, asset_class_id, dimension_json)
) STRICT;

-- ============================================================================
-- 8. Review, duplicate handling and audit
-- ============================================================================

CREATE TABLE review_tasks (
    review_task_id      TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    target_kind         TEXT NOT NULL CHECK (target_kind IN (
                          'MENTION','RESOLUTION','EVENT_MENTION','CLAIM','EVENT','TRANSITION',
                          'MEASUREMENT_DEFINITION','MEASUREMENT_FACT','SPATIAL_UNIT','MACRO_OBSERVATION'
                        )),
    target_id           TEXT NOT NULL,
    review_type         TEXT NOT NULL,
    status_code         TEXT NOT NULL DEFAULT 'PENDING' CHECK (status_code IN (
                          'PENDING','IN_PROGRESS','APPROVED','REJECTED','CHANGES_REQUESTED'
                        )),
    priority            INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    reason_code         TEXT,
    assigned_to         TEXT,
    decision_note       TEXT,
    payload_json        TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    started_at          TEXT,
    completed_at        TEXT,
    CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
) STRICT;

CREATE TABLE duplicate_candidates (
    duplicate_candidate_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    record_kind         TEXT NOT NULL CHECK (record_kind IN (
                          'DOCUMENT','ASSET','PROJECT','ORGANIZATION','EVENT',
                          'SPATIAL_UNIT','MEASUREMENT_DEFINITION'
                        )),
    record_id_a         TEXT NOT NULL,
    record_id_b         TEXT NOT NULL,
    blocking_key        TEXT,
    similarity_score    REAL NOT NULL CHECK (similarity_score BETWEEN 0 AND 1),
    features_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(features_json)),
    status_code         TEXT NOT NULL DEFAULT 'PENDING' CHECK (status_code IN (
                          'PENDING','CONFIRMED_DUPLICATE','NOT_DUPLICATE'
                        )),
    reviewed_by         TEXT,
    reviewed_at         TEXT,
    CHECK (record_id_a < record_id_b),
    UNIQUE(record_kind, record_id_a, record_id_b)
) STRICT;

CREATE TABLE merge_history (
    merge_id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    record_kind         TEXT NOT NULL CHECK (record_kind IN (
                          'ASSET','PROJECT','ORGANIZATION','EVENT'
                        )),
    survivor_id         TEXT NOT NULL,
    duplicate_id        TEXT NOT NULL,
    merge_reason        TEXT NOT NULL,
    field_resolution_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(field_resolution_json)),
    merged_by           TEXT NOT NULL,
    merged_at           TEXT NOT NULL,
    CHECK (survivor_id <> duplicate_id),
    UNIQUE(record_kind, duplicate_id)
) STRICT;

CREATE TABLE audit_log (
    audit_id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    occurred_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    actor_type          TEXT NOT NULL CHECK (actor_type IN ('SYSTEM','AGENT','USER')),
    actor_id            TEXT,
    action_code         TEXT NOT NULL,
    record_kind         TEXT NOT NULL,
    record_id           TEXT NOT NULL,
    before_json         TEXT CHECK (before_json IS NULL OR json_valid(before_json)),
    after_json          TEXT CHECK (after_json IS NULL OR json_valid(after_json)),
    run_id              TEXT REFERENCES collection_runs(run_id),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

-- ============================================================================
-- 9. Query indexes and read views
-- ============================================================================

CREATE INDEX ix_runs_job_started ON collection_runs(job_id, started_at DESC);
CREATE INDEX ix_documents_last_seen ON source_documents(last_seen_at DESC);
CREATE INDEX ix_document_versions_published ON document_versions(published_at DESC);
CREATE INDEX ix_mentions_type_text ON mentions(mention_type, normalized_text);
CREATE INDEX ix_mentions_review ON mentions(review_status, mention_type);
CREATE INDEX ix_resolutions_queue ON mention_resolutions(resolution_status, match_score DESC);
CREATE INDEX ix_event_mentions_status ON event_mentions(status_code, created_at);
CREATE INDEX ix_claims_predicate ON claims(predicate_code, review_status, verification_status);
CREATE INDEX ix_events_date_category ON events(primary_category_id, event_date_start DESC);
CREATE INDEX ix_event_assets_asset ON event_assets(asset_id, event_id);
CREATE INDEX ix_event_projects_project ON event_projects(project_id, event_id);
CREATE INDEX ix_event_participants_org_role ON event_participants(organization_id, role_code, event_id);
CREATE INDEX ix_transitions_event_date ON event_transitions(event_id, effective_date, announced_at);
CREATE INDEX ix_review_queue ON review_tasks(status_code, priority, created_at);
CREATE INDEX ix_snapshot_asof ON snapshots(snapshot_type, as_of_at DESC);

CREATE VIEW v_measurement_catalog AS
SELECT d.measurement_definition_id,
       d.code,
       d.name_ko,
       p.code AS parent_code,
       p.name_ko AS parent_name_ko,
       d.measurement_family,
       d.dimension_code,
       d.canonical_unit_code,
       d.aggregation_behavior,
       d.sector_scope,
       d.definition_text,
       d.is_abstract,
       d.status_code,
       group_concat(DISTINCT a.alias_text) AS aliases
FROM measurement_definitions d
LEFT JOIN measurement_definitions p
       ON p.measurement_definition_id = d.parent_definition_id
LEFT JOIN measurement_definition_aliases a
       ON a.measurement_definition_id = d.measurement_definition_id
GROUP BY d.measurement_definition_id;

CREATE VIEW v_current_measurements AS
SELECT s.measurement_fact_selection_id,
       s.measurement_definition_id,
       d.code AS measurement_code,
       d.name_ko AS measurement_name_ko,
       d.measurement_family,
       d.aggregation_behavior,
       CASE
         WHEN s.asset_id IS NOT NULL THEN 'ASSET'
         WHEN s.project_id IS NOT NULL THEN 'PROJECT'
         WHEN s.spatial_unit_id IS NOT NULL THEN 'SPATIAL_UNIT'
         WHEN s.event_id IS NOT NULL THEN 'EVENT'
         ELSE 'REGION'
       END AS subject_kind,
       coalesce(s.asset_id,s.project_id,s.spatial_unit_id,s.event_id,s.region_id) AS subject_id,
       coalesce(a.canonical_name,p.canonical_name,su.canonical_name,e.canonical_title,r.canonical_name) AS subject_name,
       f.raw_value,
       f.comparator_code,
       f.value_decimal_text,
       f.lower_decimal_text,
       f.upper_decimal_text,
       f.source_unit_code,
       f.normalized_value_decimal_text,
       f.normalized_lower_decimal_text,
       f.normalized_upper_decimal_text,
       f.normalized_numeric_value,
       f.normalized_unit_code,
       f.measurement_status,
       f.measurement_basis_code,
       f.observed_on,
       f.source_claim_id,
       f.source_mention_id,
       f.verification_status,
       f.review_status,
       s.slot_key,
       s.selected_at,
       s.selection_reason
FROM measurement_fact_selections s
JOIN measurement_facts f
  ON f.measurement_fact_id = s.selected_measurement_fact_id
JOIN measurement_definitions d
  ON d.measurement_definition_id = s.measurement_definition_id
LEFT JOIN assets a ON a.asset_id = s.asset_id
LEFT JOIN projects p ON p.project_id = s.project_id
LEFT JOIN spatial_units su ON su.spatial_unit_id = s.spatial_unit_id
LEFT JOIN events e ON e.event_id = s.event_id
LEFT JOIN regions r ON r.region_id = s.region_id
WHERE s.selection_status = 'CURRENT';

CREATE VIEW v_latest_macro_observation AS
WITH ranked AS (
    SELECT mo.*,
           row_number() OVER (
               PARTITION BY mo.macro_series_id, mo.period_start, mo.period_end
               ORDER BY mo.vintage_at DESC, mo.revision_no DESC
           ) AS rn
    FROM macro_observations mo
)
SELECT * FROM ranked WHERE rn = 1;

CREATE VIEW v_current_event_state AS
SELECT e.event_id,
       e.canonical_title,
       ec.code AS category_code,
       ec.name_ko AS category_name,
       e.current_stage_code,
       es.name_ko AS stage_name,
       e.event_date_start,
       e.event_date_end,
       e.date_precision,
       e.lifecycle_status,
       e.verification_level,
       e.overall_confidence,
       e.updated_at
FROM events e
LEFT JOIN event_categories ec ON ec.event_category_id = e.primary_category_id
LEFT JOIN event_stages es ON es.stage_code = e.current_stage_code
WHERE e.lifecycle_status <> 'MERGED';

CREATE VIEW v_event_feed AS
SELECT e.event_id,
       e.canonical_title,
       ec.code AS category_code,
       ec.name_ko AS category_name,
       e.current_stage_code,
       e.event_date_start,
       e.verification_level,
       e.overall_confidence,
       group_concat(DISTINCT a.canonical_name) AS asset_names,
       group_concat(DISTINCT p.canonical_name) AS project_names
FROM events e
LEFT JOIN event_categories ec ON ec.event_category_id = e.primary_category_id
LEFT JOIN event_assets ea ON ea.event_id = e.event_id
LEFT JOIN assets a ON a.asset_id = ea.asset_id
LEFT JOIN event_projects ep ON ep.event_id = e.event_id
LEFT JOIN projects p ON p.project_id = ep.project_id
WHERE e.lifecycle_status IN ('ACTIVE','COMPLETED')
GROUP BY e.event_id;

CREATE VIEW v_asset_timeline AS
SELECT a.asset_id,
       a.canonical_name AS asset_name,
       e.event_id,
       e.canonical_title,
       ec.code AS category_code,
       e.current_stage_code,
       e.event_date_start,
       ea.role_code
FROM assets a
JOIN event_assets ea ON ea.asset_id = a.asset_id
JOIN events e ON e.event_id = ea.event_id
LEFT JOIN event_categories ec ON ec.event_category_id = e.primary_category_id
WHERE e.lifecycle_status <> 'MERGED';

CREATE VIEW v_project_timeline AS
SELECT p.project_id,
       p.canonical_name AS project_name,
       e.event_id,
       e.canonical_title,
       ec.code AS category_code,
       e.current_stage_code,
       e.event_date_start,
       ep.role_code
FROM projects p
JOIN event_projects ep ON ep.project_id = p.project_id
JOIN events e ON e.event_id = ep.event_id
LEFT JOIN event_categories ec ON ec.event_category_id = e.primary_category_id
WHERE e.lifecycle_status <> 'MERGED';

CREATE VIEW v_bid_competition AS
SELECT sp.sale_process_id,
       sp.process_code,
       br.bid_round_id,
       br.round_no,
       br.round_code,
       br.round_type,
       bp.participation_id,
       bp.participation_status,
       o.organization_id AS bidder_organization_id,
       o.canonical_name AS bidder_name,
       bs.bid_submission_id,
       bs.submission_no,
       bs.bid_amount_decimal,
       bs.currency_code,
       bs.comparator_code,
       bs.amount_precision,
       bs.price_basis,
       bs.reported_rank,
       bs.rank_scope,
       bs.rank_as_of,
       CASE WHEN EXISTS (
           SELECT 1 FROM bid_decisions d
           WHERE d.sale_process_id=sp.sale_process_id
             AND d.participation_id=bp.participation_id
             AND d.decision_type='PREFERRED'
             AND d.decision_status IN ('CURRENT','VERIFIED')
       ) THEN 1 ELSE 0 END AS is_current_preferred,
       bs.evidence_status,
       bs.review_status,
       bs.source_claim_id
FROM sale_processes sp
JOIN bid_rounds br ON br.sale_process_id=sp.sale_process_id
JOIN bidder_participations bp ON bp.bid_round_id=br.bid_round_id
JOIN organizations o ON o.organization_id=bp.bidder_organization_id
LEFT JOIN bid_submissions bs ON bs.participation_id=bp.participation_id;

CREATE VIEW v_bid_funding AS
SELECT fc.funding_component_id,
       fc.bid_submission_id,

       fc.funding_type,
       fc.provider_organization_id,
       provider.canonical_name AS provider_name,
       fc.recipient_vehicle_id,
       recipient.canonical_name AS recipient_vehicle_name,
       fc.amount_decimal,
       fc.currency_code,
       fc.comparator_code,
       fc.commitment_status,
       fc.evidence_status,
       fc.review_status,
       fc.source_claim_id
FROM bid_funding_components fc
LEFT JOIN organizations provider ON provider.organization_id=fc.provider_organization_id
LEFT JOIN organizations recipient ON recipient.organization_id=fc.recipient_vehicle_id;

CREATE VIEW v_sale_process_current AS
SELECT sp.sale_process_id,
       sp.event_id,
       e.canonical_title,
       sp.process_code,
       sp.sale_method,
       sp.process_status,
       sp.launched_at,
       sp.closed_at,
       (
         SELECT o.canonical_name
         FROM bid_decisions d
         JOIN bidder_participations bp ON bp.participation_id=d.participation_id
         JOIN organizations o ON o.organization_id=bp.bidder_organization_id
         WHERE d.sale_process_id=sp.sale_process_id
           AND d.decision_type='PREFERRED'
           AND d.decision_status IN ('CURRENT','VERIFIED')
         ORDER BY coalesce(d.decision_date,'' ) DESC,d.created_at DESC LIMIT 1
       ) AS current_preferred_bidder,
       (
         SELECT tm.milestone_code
         FROM transaction_milestones tm
         WHERE tm.sale_process_id=sp.sale_process_id
           AND tm.milestone_status IN ('REPORTED','CONFIRMED','FAILED')
         ORDER BY coalesce(tm.effective_date,tm.announced_at,tm.expected_date,'') DESC,
                  tm.created_at DESC LIMIT 1
       ) AS current_milestone,
       sp.evidence_status,
       sp.review_status
FROM sale_processes sp
JOIN events e ON e.event_id=sp.event_id;

CREATE VIEW v_sale_process_relations AS
SELECT r.sale_process_relation_id,
       r.from_sale_process_id,
       source.process_code AS from_process_code,
       r.to_sale_process_id,
       target.process_code AS to_process_code,
       r.relation_type,
       r.evidence_status,
       r.review_status,
       r.source_claim_id,
       r.metadata_json
FROM sale_process_relations r
JOIN sale_processes source ON source.sale_process_id=r.from_sale_process_id
JOIN sale_processes target ON target.sale_process_id=r.to_sale_process_id;

CREATE TABLE predicate_relationship_rules (
    relationship_rule_id TEXT PRIMARY KEY,
    predicate_code      TEXT NOT NULL REFERENCES predicate_definitions(predicate_code),
    claim_role_code     TEXT REFERENCES claim_role_definitions(role_code),
    target_relation     TEXT NOT NULL CHECK (target_relation IN (
                          'EVENT_PARTICIPANT','PROPERTY_OCCUPANCY','BUSINESS_ACTIVITY'
                        )),
    participant_role_code TEXT,
    occupancy_type      TEXT,
    tenure_type         TEXT,
    minimum_verification_status TEXT NOT NULL DEFAULT 'VERIFIED' CHECK (
                          minimum_verification_status IN ('VERIFIED','PENDING','UNVERIFIED')
                        ),
    auto_apply          INTEGER NOT NULL DEFAULT 1 CHECK (auto_apply IN (0,1)),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(predicate_code,claim_role_code,target_relation)
) STRICT;

-- ============================================================================
-- 12. Institutional LP manager mandates, awards and disclosed deployments
-- ============================================================================

CREATE TABLE lp_mandates (
    mandate_id             TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    event_id               TEXT REFERENCES events(event_id),
    lp_organization_id     TEXT NOT NULL REFERENCES organizations(organization_id),
    mandate_code           TEXT NOT NULL UNIQUE,
    mandate_name           TEXT NOT NULL,
    vintage_year           INTEGER NOT NULL CHECK (vintage_year BETWEEN 1900 AND 2200),
    announced_at           TEXT,
    application_deadline   TEXT,
    selected_at            TEXT,
    mandate_status         TEXT NOT NULL CHECK (mandate_status IN (
                               'PLANNED','OPEN','SCREENING','SHORTLISTED','SELECTED',
                               'COMMITTED','CANCELLED','CLOSED','UNKNOWN'
                             )),
    mandate_scope          TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (mandate_scope IN (
                               'DOMESTIC','OVERSEAS','GLOBAL','MIXED','UNKNOWN'
                             )),
    evidence_status        TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id        TEXT REFERENCES claims(claim_id),
    review_status          TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    metadata_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (application_deadline IS NULL OR announced_at IS NULL OR application_deadline >= announced_at),
    CHECK (selected_at IS NULL OR announced_at IS NULL OR selected_at >= announced_at),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE lp_mandate_tracks (
    mandate_track_id       TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    mandate_id             TEXT NOT NULL REFERENCES lp_mandates(mandate_id) ON DELETE CASCADE,
    track_code             TEXT NOT NULL,
    track_name             TEXT NOT NULL,
    strategy_code          TEXT NOT NULL CHECK (strategy_code IN (
                               'REAL_ESTATE','INFRASTRUCTURE','PRIVATE_EQUITY','PRIVATE_DEBT',
                               'REAL_ASSETS','MULTI_ASSET','SECONDARIES','OTHER','UNKNOWN'
                             )),
    geography_code         TEXT CHECK (geography_code IS NULL OR geography_code IN (
                               'DOMESTIC','ASIA','NORTH_AMERICA','EUROPE','GLOBAL','MIXED','OTHER','UNKNOWN'
                             )),
    target_manager_count   INTEGER CHECK (target_manager_count IS NULL OR target_manager_count >= 1),
    evidence_status        TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id        TEXT REFERENCES claims(claim_id),
    review_status          TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    metadata_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(mandate_id,track_code),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE lp_mandate_guidelines (
    mandate_guideline_id   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    mandate_track_id       TEXT NOT NULL REFERENCES lp_mandate_tracks(mandate_track_id) ON DELETE CASCADE,
    term_type              TEXT NOT NULL CHECK (term_type IN (
                               'TARGET_RETURN','STRATEGY','SECTOR','GEOGRAPHY','RISK_PROFILE','INVESTMENT_PERIOD',
                               'FUND_TERM','LEVERAGE','DEAL_SIZE','ELIGIBLE_ASSET','EXCLUSION',
                               'MANAGER_COMMITMENT','CO_INVESTMENT','ESG','OTHER'
                             )),
    requirement_level      TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (requirement_level IN (
                               'REQUIRED','PREFERRED','MINIMUM','MAXIMUM','REFERENCE','PROHIBITED','UNKNOWN'
                             )),
    raw_text               TEXT NOT NULL,
    value_kind             TEXT NOT NULL DEFAULT 'TEXT' CHECK (value_kind IN (
                               'TEXT','PERCENT','MONEY','DURATION','NUMBER','JSON'
                             )),
    text_value             TEXT,
    value_decimal_text     TEXT,
    lower_decimal_text     TEXT,
    upper_decimal_text     TEXT,
    comparator_code        TEXT NOT NULL DEFAULT 'EXACT' CHECK (comparator_code IN (
                               'EXACT','ABOUT','AT_LEAST','AT_MOST','GREATER_THAN','LESS_THAN','RANGE','UNKNOWN'
                             )),
    currency_code          TEXT,
    unit_code              TEXT REFERENCES units(unit_code),
    return_basis           TEXT CHECK (return_basis IS NULL OR return_basis IN (
                               'GROSS_IRR','NET_IRR','GROSS_MULTIPLE','NET_MULTIPLE',
                               'CASH_YIELD','TOTAL_RETURN','UNSPECIFIED'
                             )),
    evidence_status        TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id        TEXT REFERENCES claims(claim_id),
    review_status          TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    metadata_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (comparator_code <> 'RANGE' OR (lower_decimal_text IS NOT NULL AND upper_decimal_text IS NOT NULL)),
    CHECK (term_type = 'TARGET_RETURN' OR return_basis IS NULL),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE lp_mandate_selections (
    mandate_selection_id   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    mandate_track_id       TEXT NOT NULL REFERENCES lp_mandate_tracks(mandate_track_id) ON DELETE CASCADE,
    manager_organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    selection_status       TEXT NOT NULL CHECK (selection_status IN (
                               'APPLIED','SHORTLISTED','SELECTED','RESERVE','NOT_SELECTED',
                               'WITHDRAWN','REVOKED','UNKNOWN'
                             )),
    selected_at            TEXT,
    rank_no                INTEGER CHECK (rank_no IS NULL OR rank_no >= 1),
    evidence_status        TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id        TEXT REFERENCES claims(claim_id),
    review_status          TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    confidence             REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(mandate_track_id,manager_organization_id),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE lp_mandate_selection_members (
    mandate_selection_id   TEXT NOT NULL REFERENCES lp_mandate_selections(mandate_selection_id) ON DELETE CASCADE,
    organization_id        TEXT NOT NULL REFERENCES organizations(organization_id),
    member_role            TEXT NOT NULL CHECK (member_role IN (
                               'LEAD_MANAGER','CO_MANAGER','CONSORTIUM_MEMBER','LOCAL_PARTNER','OTHER'
                             )),
    evidence_status        TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id        TEXT REFERENCES claims(claim_id),
    review_status          TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    metadata_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    PRIMARY KEY(mandate_selection_id,organization_id,member_role),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE lp_mandate_selection_vehicles (
    mandate_selection_id   TEXT NOT NULL REFERENCES lp_mandate_selections(mandate_selection_id) ON DELETE CASCADE,
    vehicle_organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    vehicle_role           TEXT NOT NULL CHECK (vehicle_role IN (
                               'MANAGED_FUND','FEEDER','CO_INVESTMENT_VEHICLE','SPV','UNKNOWN'
                             )),
    evidence_status        TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id        TEXT REFERENCES claims(claim_id),
    review_status          TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    metadata_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    PRIMARY KEY(mandate_selection_id,vehicle_organization_id,vehicle_role),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE TABLE lp_mandate_amounts (
    mandate_amount_id      TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    mandate_id             TEXT REFERENCES lp_mandates(mandate_id) ON DELETE CASCADE,
    mandate_track_id       TEXT REFERENCES lp_mandate_tracks(mandate_track_id) ON DELETE CASCADE,
    mandate_selection_id   TEXT REFERENCES lp_mandate_selections(mandate_selection_id) ON DELETE CASCADE,
    amount_basis           TEXT NOT NULL CHECK (amount_basis IN (
                               'PROGRAM_TOTAL','LP_COMMITMENT_TOTAL','TRACK_LP_COMMITMENT',
                               'ALLOCATION_PER_MANAGER','SELECTION_LP_COMMITMENT','TARGET_FUND_SIZE',
                               'MANAGER_COMMITMENT','CO_INVESTMENT_RESERVE','OTHER','UNKNOWN'
                             )),
    amount_decimal         TEXT,
    lower_amount_decimal   TEXT,
    upper_amount_decimal   TEXT,
    currency_code          TEXT NOT NULL,
    comparator_code        TEXT NOT NULL DEFAULT 'EXACT' CHECK (comparator_code IN (
                               'EXACT','ABOUT','AT_LEAST','AT_MOST','GREATER_THAN','LESS_THAN','RANGE','UNKNOWN'
                             )),
    amount_status          TEXT NOT NULL CHECK (amount_status IN (
                               'ANNOUNCED','PROPOSED','AWARDED','COMMITTED','CANCELLED','SUPERSEDED','REPORTED','UNKNOWN'
                             )),
    is_current             INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    supersedes_amount_id   TEXT REFERENCES lp_mandate_amounts(mandate_amount_id),
    raw_value              TEXT,
    evidence_status        TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id        TEXT REFERENCES claims(claim_id),
    review_status          TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    metadata_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((mandate_id IS NOT NULL) + (mandate_track_id IS NOT NULL) + (mandate_selection_id IS NOT NULL) = 1),
    CHECK (comparator_code <> 'RANGE' OR (lower_amount_decimal IS NOT NULL AND upper_amount_decimal IS NOT NULL)),
    CHECK (comparator_code = 'RANGE' OR amount_decimal IS NOT NULL OR comparator_code = 'UNKNOWN'),
    CHECK (supersedes_amount_id IS NULL OR supersedes_amount_id <> mandate_amount_id),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE UNIQUE INDEX uq_lp_mandate_current_amount
    ON lp_mandate_amounts(
       coalesce(mandate_id,''),coalesce(mandate_track_id,''),coalesce(mandate_selection_id,''),
       amount_basis,currency_code
    ) WHERE is_current=1;

CREATE TABLE lp_mandate_deployments (
    mandate_deployment_id  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    mandate_selection_id   TEXT NOT NULL REFERENCES lp_mandate_selections(mandate_selection_id) ON DELETE CASCADE,
    fund_vehicle_organization_id TEXT REFERENCES organizations(organization_id),
    sale_process_id        TEXT REFERENCES sale_processes(sale_process_id),
    event_id               TEXT REFERENCES events(event_id),
    asset_id               TEXT REFERENCES assets(asset_id),
    project_id             TEXT REFERENCES projects(project_id),
    deployment_basis       TEXT NOT NULL CHECK (deployment_basis IN (
                               'LP_SOURCE_DEPLOYMENT','FUND_EQUITY_DEPLOYMENT',
                               'TOTAL_EQUITY_COMMITMENT','CO_INVESTMENT','OTHER','UNKNOWN'
                             )),
    amount_decimal         TEXT,
    lower_amount_decimal   TEXT,
    upper_amount_decimal   TEXT,
    currency_code          TEXT NOT NULL,
    comparator_code        TEXT NOT NULL DEFAULT 'EXACT' CHECK (comparator_code IN (
                               'EXACT','ABOUT','AT_LEAST','AT_MOST','GREATER_THAN','LESS_THAN','RANGE','UNKNOWN'
                             )),
    deployment_status      TEXT NOT NULL CHECK (deployment_status IN (
                               'PLANNED','INDICATIVE','COMMITTED','EXECUTED','REALISED',
                               'CANCELLED','SUPERSEDED','REPORTED','UNKNOWN'
                             )),
    deployed_at            TEXT,
    is_current             INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    raw_value              TEXT,
    evidence_status        TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                               'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                             )),
    source_claim_id        TEXT REFERENCES claims(claim_id),
    review_status          TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                               'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                             )),
    confidence             REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((sale_process_id IS NOT NULL) + (event_id IS NOT NULL) + (asset_id IS NOT NULL) + (project_id IS NOT NULL) >= 1),
    CHECK (comparator_code <> 'RANGE' OR (lower_amount_decimal IS NOT NULL AND upper_amount_decimal IS NOT NULL)),
    CHECK (comparator_code = 'RANGE' OR amount_decimal IS NOT NULL OR comparator_code = 'UNKNOWN'),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE INDEX ix_lp_mandates_lp_vintage ON lp_mandates(lp_organization_id,vintage_year,mandate_status);
CREATE INDEX ix_lp_mandate_selections_manager ON lp_mandate_selections(manager_organization_id,selection_status);
CREATE INDEX ix_lp_mandate_deployments_sale ON lp_mandate_deployments(sale_process_id,mandate_selection_id);
CREATE INDEX ix_lp_mandate_deployments_asset ON lp_mandate_deployments(asset_id,mandate_selection_id);

CREATE VIEW v_lp_mandate_source_balance AS
WITH source_amounts AS (
    SELECT a.mandate_selection_id,
           a.currency_code,
           a.amount_decimal,
           a.amount_basis,
           a.amount_status
      FROM lp_mandate_amounts a
     WHERE (
             (a.amount_basis='SELECTION_LP_COMMITMENT'
              AND a.amount_status IN ('COMMITTED','REPORTED'))
          OR (a.amount_basis='ALLOCATION_PER_MANAGER'
              AND a.amount_status='AWARDED')
           )
       AND a.comparator_code='EXACT'
       AND a.is_current=1
       AND a.review_status='APPROVED'
), deployed AS (
    SELECT d.mandate_selection_id,
           d.currency_code,
           SUM(CAST(d.amount_decimal AS INTEGER)) AS deployed_amount
      FROM lp_mandate_deployments d
     WHERE d.deployment_basis='LP_SOURCE_DEPLOYMENT'
       AND d.comparator_code='EXACT'
       AND d.is_current=1
       AND d.deployment_status IN ('COMMITTED','EXECUTED')
       AND d.review_status='APPROVED'
     GROUP BY d.mandate_selection_id,d.currency_code
)
SELECT s.mandate_selection_id,
       s.currency_code,
       s.amount_decimal AS source_amount_decimal,
       CAST(coalesce(d.deployed_amount,0) AS TEXT) AS disclosed_deployed_decimal,
       CAST(CAST(s.amount_decimal AS INTEGER)-coalesce(d.deployed_amount,0) AS TEXT) AS untraced_amount_decimal,
       CASE
         WHEN s.amount_basis='SELECTION_LP_COMMITMENT'
           THEN 'UNTRACED_COMMITTED_NOT_CONFIRMED_AVAILABLE'
         ELSE 'UNTRACED_AWARDED_NOT_CONFIRMED_COMMITTED_OR_AVAILABLE'
       END AS balance_semantics
  FROM source_amounts s
  LEFT JOIN deployed d
    ON d.mandate_selection_id=s.mandate_selection_id
   AND d.currency_code=s.currency_code;

CREATE VIEW v_lp_mandate_deal_sources AS
SELECT m.mandate_id,
       m.mandate_code,
       lp.organization_id AS lp_organization_id,
       lp.canonical_name AS lp_name,
       t.mandate_track_id,
       t.track_code,
       t.strategy_code,
       s.mandate_selection_id,
       manager.organization_id AS manager_organization_id,
       manager.canonical_name AS manager_name,
       d.mandate_deployment_id,
       d.fund_vehicle_organization_id,
       vehicle.canonical_name AS fund_vehicle_name,
       d.sale_process_id,
       sp.process_code AS sale_process_code,
       d.event_id,
       d.asset_id,
       d.project_id,
       d.deployment_basis,
       d.amount_decimal,
       d.currency_code,
       d.comparator_code,
       d.deployment_status,
       d.deployed_at,
       d.evidence_status,
       d.review_status
  FROM lp_mandate_deployments d
  JOIN lp_mandate_selections s ON s.mandate_selection_id=d.mandate_selection_id
  JOIN lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id
  JOIN lp_mandates m ON m.mandate_id=t.mandate_id
  JOIN organizations lp ON lp.organization_id=m.lp_organization_id
  JOIN organizations manager ON manager.organization_id=s.manager_organization_id
  LEFT JOIN organizations vehicle ON vehicle.organization_id=d.fund_vehicle_organization_id
  LEFT JOIN sale_processes sp ON sp.sale_process_id=d.sale_process_id;

CREATE VIEW v_lp_manager_best_available AS
SELECT m.mandate_code,
       t.track_code,
       manager.organization_id AS manager_organization_id,
       manager.canonical_name AS manager_name,
       s.selection_status,
       s.selected_at,
       'VERIFIED_OFFICIAL' AS value_status,
       1 AS canonical_eligible,
       coalesce(s.confidence,1.0) AS confidence,
       1 AS independent_family_count,
       1 AS occurrence_count,
       NULL AS reported_allocation_decimal,
       NULL AS allocation_currency_code,
       s.source_claim_id
  FROM lp_mandate_selections s
  JOIN lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id
  JOIN lp_mandates m ON m.mandate_id=t.mandate_id
  JOIN organizations manager ON manager.organization_id=s.manager_organization_id
 WHERE s.review_status='APPROVED'
UNION ALL
SELECT m.mandate_code,
       t.track_code,
       manager.organization_id AS manager_organization_id,
       manager.canonical_name AS manager_name,
       'REPORTED_SELECTED' AS selection_status,
       c.date_start AS selected_at,
       coalesce((SELECT a.text_value FROM claim_arguments a
                  WHERE a.claim_id=c.claim_id AND a.role_code='RESOLUTION_STATUS' LIMIT 1),
                'NEWS_ONLY_PENDING_PRIMARY') AS value_status,
       0 AS canonical_eligible,
       c.confidence,
       coalesce(CAST((SELECT a.value_decimal_text FROM claim_arguments a
                       WHERE a.claim_id=c.claim_id AND a.role_code='INDEPENDENT_FAMILY_COUNT' LIMIT 1) AS INTEGER),1)
         AS independent_family_count,
       coalesce(CAST((SELECT a.value_decimal_text FROM claim_arguments a
                       WHERE a.claim_id=c.claim_id AND a.role_code='OCCURRENCE_COUNT' LIMIT 1) AS INTEGER),1)
         AS occurrence_count,
       (SELECT ac.value_decimal_text FROM claims ac
         WHERE ac.event_mention_id=c.event_mention_id
           AND ac.predicate_code='LP_MANDATE_REPORTED_MANAGER_ALLOCATION'
           AND ac.object_organization_id=c.object_organization_id LIMIT 1) AS reported_allocation_decimal,
       (SELECT ac.currency_code FROM claims ac
         WHERE ac.event_mention_id=c.event_mention_id
           AND ac.predicate_code='LP_MANDATE_REPORTED_MANAGER_ALLOCATION'
           AND ac.object_organization_id=c.object_organization_id LIMIT 1) AS allocation_currency_code,
       c.claim_id AS source_claim_id
  FROM claims c
  JOIN event_mention_links eml ON eml.event_mention_id=c.event_mention_id AND eml.relation_code='SUPPORTING'
  JOIN lp_mandates m ON m.event_id=eml.event_id
  JOIN lp_mandate_tracks t ON t.mandate_id=m.mandate_id
  JOIN organizations manager ON manager.organization_id=c.object_organization_id
 WHERE c.predicate_code='LP_MANDATE_REPORTED_SELECTED_MANAGER'
   AND c.verification_status IN ('UNVERIFIED','PENDING','INCONCLUSIVE')
   AND c.review_status='ACCEPTED'
   AND t.track_code=coalesce((SELECT a.text_value FROM claim_arguments a
                               WHERE a.claim_id=c.claim_id AND a.role_code='MANDATE_TRACK' LIMIT 1),t.track_code);

-- ============================================================================
-- 13. Point-in-time company universe, industry and property occupancy
-- ============================================================================

CREATE TABLE industry_taxonomies (
    taxonomy_code       TEXT PRIMARY KEY,
    taxonomy_name       TEXT NOT NULL,
    publisher_name      TEXT NOT NULL,
    version_label       TEXT NOT NULL,
    valid_from          TEXT,
    valid_to            TEXT,
    source_document_version_id TEXT REFERENCES document_versions(document_version_id),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE industry_nodes (
    industry_node_id    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    taxonomy_code       TEXT NOT NULL REFERENCES industry_taxonomies(taxonomy_code),
    industry_code       TEXT NOT NULL,
    industry_name       TEXT NOT NULL,
    parent_industry_node_id TEXT REFERENCES industry_nodes(industry_node_id),
    valid_from          TEXT,
    valid_to            TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(taxonomy_code,industry_code),

    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (parent_industry_node_id IS NULL OR parent_industry_node_id <> industry_node_id)
) STRICT;

CREATE TABLE organization_industry_assignments (
    organization_industry_assignment_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    organization_id     TEXT NOT NULL REFERENCES organizations(organization_id),
    industry_node_id    TEXT NOT NULL REFERENCES industry_nodes(industry_node_id),
    valid_from          TEXT NOT NULL,
    valid_to            TEXT,
    is_primary          INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    assignment_basis    TEXT NOT NULL CHECK (assignment_basis IN (
                              'KRX_OFFICIAL','KSIC_OFFICIAL','COMPANY_DISCLOSURE',
                              'RESEARCH_CLASSIFICATION','MANUAL_REVIEWED','OTHER'
                            )),
    source_claim_id     TEXT REFERENCES claims(claim_id),
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (verification_status IN (
                              'UNVERIFIED','PENDING','VERIFIED','CONTRADICTED','INCONCLUSIVE'
                            )),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                              'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                            )),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(organization_id,industry_node_id,valid_from),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE market_universe_snapshots (
    universe_snapshot_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    snapshot_date        TEXT NOT NULL,
    market_code          TEXT NOT NULL,
    universe_code        TEXT NOT NULL CHECK (universe_code IN (
                              'KRX_MARKET_CAP_TOP_50','KRX_INDUSTRY_MARKET_CAP_TOP_10',
                              'AS_OF_EMERGING_INDUSTRY_WATCHLIST','MANUAL_WATCHLIST'
                            )),
    ranking_basis        TEXT NOT NULL DEFAULT 'MARKET_CAP',
    taxonomy_code       TEXT REFERENCES industry_taxonomies(taxonomy_code),
    source_document_version_id TEXT REFERENCES document_versions(document_version_id),
    snapshot_status     TEXT NOT NULL DEFAULT 'BUILDING' CHECK (snapshot_status IN (
                              'BUILDING','COMPLETE','PARTIAL','FAILED','SUPERSEDED'
                            )),
    methodology_json    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(methodology_json)),
    row_count           INTEGER CHECK (row_count IS NULL OR row_count >= 0),
    checksum_sha256     TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(snapshot_date,market_code,universe_code,taxonomy_code)
) STRICT;

CREATE TABLE market_universe_members (
    universe_member_id  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    universe_snapshot_id TEXT NOT NULL REFERENCES market_universe_snapshots(universe_snapshot_id) ON DELETE CASCADE,
    organization_id     TEXT NOT NULL REFERENCES organizations(organization_id),
    industry_node_id    TEXT REFERENCES industry_nodes(industry_node_id),
    overall_rank        INTEGER CHECK (overall_rank IS NULL OR overall_rank >= 1),
    industry_rank       INTEGER CHECK (industry_rank IS NULL OR industry_rank >= 1),
    market_cap_decimal  TEXT,
    currency_code       TEXT,
    inclusion_reason    TEXT NOT NULL CHECK (inclusion_reason IN (
                              'TOP_50_OVERALL','TOP_10_INDUSTRY','EMERGING_INDUSTRY','MANUAL_WATCHLIST'
                            )),
    source_claim_id     TEXT REFERENCES claims(claim_id),
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (verification_status IN (
                              'UNVERIFIED','PENDING','VERIFIED','CONTRADICTED','INCONCLUSIVE'
                            )),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                              'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                            )),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(universe_snapshot_id,organization_id,inclusion_reason,industry_node_id),
    CHECK (inclusion_reason <> 'TOP_50_OVERALL' OR overall_rank IS NOT NULL),
    CHECK (inclusion_reason <> 'TOP_10_INDUSTRY' OR (industry_node_id IS NOT NULL AND industry_rank IS NOT NULL)),
    CHECK (market_cap_decimal IS NULL OR currency_code IS NOT NULL)
) STRICT;

CREATE TABLE organization_business_activities (
    organization_business_activity_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    organization_id     TEXT NOT NULL REFERENCES organizations(organization_id),
    industry_node_id    TEXT REFERENCES industry_nodes(industry_node_id),
    activity_code       TEXT NOT NULL,
    activity_name       TEXT NOT NULL,
    activity_description TEXT,
    activity_importance TEXT NOT NULL DEFAULT 'SECONDARY' CHECK (activity_importance IN (
                              'PRIMARY','SECONDARY','EMERGING','DISCONTINUED','UNKNOWN'
                            )),
    valid_from          TEXT NOT NULL,
    valid_to            TEXT,
    source_claim_id     TEXT REFERENCES claims(claim_id),
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (verification_status IN (
                              'UNVERIFIED','PENDING','VERIFIED','CONTRADICTED','INCONCLUSIVE'
                            )),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                              'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                            )),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(organization_id,activity_code,valid_from),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE TABLE organization_property_occupancies (
    occupancy_id        TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    organization_id     TEXT NOT NULL REFERENCES organizations(organization_id),
    asset_id            TEXT REFERENCES assets(asset_id),
    project_id          TEXT REFERENCES projects(project_id),
    region_id           TEXT REFERENCES regions(region_id),
    occupancy_type      TEXT NOT NULL CHECK (occupancy_type IN (
                              'HEADQUARTERS','OFFICE','R_AND_D','LOGISTICS','DATA_CENTER',
                              'PRODUCTION','RETAIL','HOSPITALITY','OTHER','UNKNOWN'
                            )),
    tenure_type         TEXT NOT NULL CHECK (tenure_type IN (
                              'TENANT','OWNER','OPERATOR','PLANNED','UNKNOWN'
                            )),
    occupancy_status    TEXT NOT NULL CHECK (occupancy_status IN (
                              'REPORTED','PLANNED','NEGOTIATING','CONTRACTED','OCCUPIED',
                              'ENDED','CANCELLED','UNKNOWN'
                            )),
    valid_from          TEXT,
    valid_to            TEXT,
    event_id            TEXT REFERENCES events(event_id),
    source_claim_id     TEXT REFERENCES claims(claim_id),
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (verification_status IN (
                              'UNVERIFIED','PENDING','VERIFIED','CONTRADICTED','INCONCLUSIVE'
                            )),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                              'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                            )),
    confidence          REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((asset_id IS NOT NULL) + (project_id IS NOT NULL) + (region_id IS NOT NULL) = 1),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE INDEX ix_org_industry_asof ON organization_industry_assignments(organization_id,valid_from,valid_to,is_primary);
CREATE INDEX ix_universe_snapshot_date ON market_universe_snapshots(snapshot_date,market_code,universe_code,snapshot_status);
CREATE INDEX ix_universe_member_org ON market_universe_members(organization_id,universe_snapshot_id,inclusion_reason);
CREATE UNIQUE INDEX ux_universe_overall_rank ON market_universe_members(universe_snapshot_id,overall_rank) WHERE overall_rank IS NOT NULL;
CREATE UNIQUE INDEX ux_universe_industry_rank ON market_universe_members(universe_snapshot_id,industry_node_id,industry_rank) WHERE industry_rank IS NOT NULL;
CREATE INDEX ix_business_activity_org_time ON organization_business_activities(organization_id,valid_from,valid_to);
CREATE INDEX ix_occupancy_org_time ON organization_property_occupancies(organization_id,valid_from,valid_to,occupancy_status);
CREATE INDEX ix_occupancy_asset ON organization_property_occupancies(asset_id,organization_id);

CREATE VIEW v_company_universe_current AS
SELECT s.universe_snapshot_id,s.snapshot_date,s.market_code,s.universe_code,s.taxonomy_code,
       m.universe_member_id,m.organization_id,o.canonical_name AS organization_name,
       m.industry_node_id,n.industry_name,m.overall_rank,m.industry_rank,
       m.market_cap_decimal,m.currency_code,m.inclusion_reason,
       m.verification_status,m.review_status
  FROM market_universe_snapshots s
  JOIN market_universe_members m ON m.universe_snapshot_id=s.universe_snapshot_id
  JOIN organizations o ON o.organization_id=m.organization_id
  LEFT JOIN industry_nodes n ON n.industry_node_id=m.industry_node_id
 WHERE s.snapshot_status='COMPLETE'
   AND NOT EXISTS (
       SELECT 1 FROM market_universe_snapshots newer
        WHERE newer.market_code=s.market_code
          AND newer.universe_code=s.universe_code
          AND newer.taxonomy_code IS s.taxonomy_code
          AND newer.snapshot_status='COMPLETE'
          AND newer.snapshot_date>s.snapshot_date
   );

CREATE VIEW v_company_real_estate_timeline AS
SELECT e.event_id,e.canonical_title,c.code AS event_category,e.current_stage_code,
       e.event_date_start,e.event_date_end,e.date_precision,e.lifecycle_status,
       e.verification_level,e.overall_confidence,
       ep.organization_id,o.canonical_name AS organization_name,ep.role_code,
       ea.asset_id,epj.project_id
  FROM events e
  JOIN event_categories c ON c.event_category_id=e.primary_category_id
  JOIN event_participants ep ON ep.event_id=e.event_id
  JOIN organizations o ON o.organization_id=ep.organization_id
  LEFT JOIN event_assets ea ON ea.event_id=e.event_id
  LEFT JOIN event_projects epj ON epj.event_id=e.event_id
 WHERE c.code IN ('LEASE','CORPORATE_RELOCATION','INVESTMENT')
   AND o.organization_type='COMPANY';

CREATE VIEW v_company_event_universe_context AS
SELECT tl.*,
       s.universe_snapshot_id,s.snapshot_date,s.market_code,s.universe_code,
       um.inclusion_reason,um.overall_rank,um.industry_rank,um.market_cap_decimal,um.currency_code,
       um.industry_node_id
  FROM v_company_real_estate_timeline tl
  LEFT JOIN market_universe_members um ON um.organization_id=tl.organization_id
  LEFT JOIN market_universe_snapshots s ON s.universe_snapshot_id=um.universe_snapshot_id
   AND s.snapshot_status='COMPLETE'
   AND s.snapshot_date=(
       SELECT MAX(s2.snapshot_date)
         FROM market_universe_snapshots s2
         JOIN market_universe_members um2 ON um2.universe_snapshot_id=s2.universe_snapshot_id
        WHERE um2.organization_id=tl.organization_id
          AND s2.snapshot_status='COMPLETE'
          AND s2.snapshot_date<=substr(coalesce(tl.event_date_start,'9999-12-31'),1,10)
          AND s2.market_code=s.market_code
          AND s2.universe_code=s.universe_code
   );

-- ============================================================================
-- 14. Post-collection relationship reconciliation (V2.7)
-- ============================================================================

CREATE TABLE relationship_resolution_runs (
    relationship_run_id TEXT PRIMARY KEY,
    collection_run_id   TEXT REFERENCES collection_runs(run_id),
    scope_code          TEXT NOT NULL CHECK (scope_code IN ('COLLECTION_RUN','ALL_EXISTING')),
    pipeline_version    TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    completed_at        TEXT,
    status_code         TEXT NOT NULL CHECK (status_code IN ('RUNNING','COMPLETED','FAILED')),
    resolved_mentions   INTEGER NOT NULL DEFAULT 0 CHECK (resolved_mentions >= 0),
    ambiguous_mentions  INTEGER NOT NULL DEFAULT 0 CHECK (ambiguous_mentions >= 0),
    event_participants_created INTEGER NOT NULL DEFAULT 0 CHECK (event_participants_created >= 0),
    occupancies_created INTEGER NOT NULL DEFAULT 0 CHECK (occupancies_created >= 0),
    business_activities_created INTEGER NOT NULL DEFAULT 0 CHECK (business_activities_created >= 0),
    unresolved_mentions INTEGER NOT NULL DEFAULT 0 CHECK (unresolved_mentions >= 0),
    error_message       TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE INDEX ix_relationship_runs_collection
    ON relationship_resolution_runs(collection_run_id,started_at DESC);

CREATE VIEW v_relationship_gaps AS
SELECT 'UNRESOLVED_ORGANIZATION_MENTION' AS gap_code,
       'MENTION' AS record_kind,
       m.mention_id AS record_id,
       m.surface_text AS detail,
       (SELECT min(rd.run_id)
          FROM extraction_runs er
          JOIN run_documents rd ON rd.document_version_id=er.document_version_id
         WHERE er.extraction_run_id=m.extraction_run_id) AS collection_run_id
  FROM mentions m
 WHERE m.mention_type='ORGANIZATION'
   AND m.review_status<>'REJECTED'
   AND NOT EXISTS (
       SELECT 1 FROM mention_resolutions mr
        WHERE mr.mention_id=m.mention_id AND mr.selected=1
   )
UNION ALL
SELECT 'ORGANIZATION_MISSING_IDENTIFIERS','ORGANIZATION',o.organization_id,o.canonical_name,NULL
  FROM organizations o
 WHERE o.status_code<>'MERGED'
   AND o.corporate_no IS NULL AND o.business_no IS NULL
   AND o.dart_corp_code IS NULL AND o.stock_code IS NULL
UNION ALL
SELECT 'COMPANY_EVENT_WITHOUT_PARTICIPANT','EVENT',e.event_id,e.canonical_title,NULL
  FROM events e
  JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
 WHERE ec.code IN ('LEASE','CORPORATE_RELOCATION','INVESTMENT')
   AND e.lifecycle_status<>'MERGED'
   AND NOT EXISTS (SELECT 1 FROM event_participants ep WHERE ep.event_id=e.event_id)
UNION ALL
SELECT 'PROPERTY_EVENT_WITHOUT_PLACE','EVENT',e.event_id,e.canonical_title,NULL
  FROM events e
  JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
 WHERE ec.code IN ('LEASE','CORPORATE_RELOCATION')
   AND e.lifecycle_status<>'MERGED'
   AND NOT EXISTS (SELECT 1 FROM event_assets ea WHERE ea.event_id=e.event_id)
   AND NOT EXISTS (SELECT 1 FROM event_projects ep WHERE ep.event_id=e.event_id);

-- ============================================================================
-- 15. Version-bound content enrichment (V2.8)
-- ============================================================================

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
    UNIQUE(document_version_id, enrichment_kind, pipeline_version),
    CHECK (status_code <> 'COMPLETED' OR summary_text IS NOT NULL),
    CHECK (safe_excerpt IS NULL OR content_mode IN ('FULL_TEXT','SAFE_EXCERPT'))
) STRICT;

CREATE INDEX ix_document_enrichments_version_status
    ON document_enrichments(document_version_id,status_code,review_status);

-- Version-bound domain scope assessment. Raw documents remain evidence; only
-- CRE_CONFIRMED disclosures enter the default market-document search surface.
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
    ON document_scope_assessments(scope_code,status_code,classifier_version,document_version_id);

-- Version-bound CRE scope assessment for organization identity masters.
CREATE TABLE organization_scope_assessments (
    organization_scope_assessment_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    scope_code TEXT NOT NULL CHECK (scope_code='CRE'),
    classifier_version TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK (status_code IN ('CRE_CONFIRMED','CRE_CONTEXT_ONLY','CRE_REVIEW')),
    reason_codes_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(reason_codes_json)),
    evidence_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(evidence_json)),
    assessed_at TEXT NOT NULL,
    UNIQUE(organization_id, scope_code, classifier_version)
) STRICT;

CREATE INDEX ix_organization_scope_assessments_scope_status
    ON organization_scope_assessments(scope_code,status_code,classifier_version,organization_id);

CREATE INDEX IF NOT EXISTS ix_extraction_runs_document_version
ON extraction_runs(document_version_id);
CREATE INDEX IF NOT EXISTS ix_mentions_extraction_run
ON mentions(extraction_run_id);
CREATE INDEX IF NOT EXISTS ix_mention_resolutions_selected
ON mention_resolutions(mention_id,resolution_status,selected);
CREATE INDEX IF NOT EXISTS ix_event_mentions_extraction_run
ON event_mentions(extraction_run_id);
CREATE INDEX IF NOT EXISTS ix_claims_event_verification
ON claims(event_mention_id,verification_status,review_status);

CREATE VIEW v_document_entity_relations AS
WITH event_evidence AS (
    SELECT DISTINCT dv.document_id,er.document_version_id,em.event_mention_id,
           eml.event_id,eml.relation_code,em.confidence
    FROM extraction_runs er
    JOIN document_versions dv ON dv.document_version_id=er.document_version_id
    JOIN event_mentions em ON em.extraction_run_id=er.extraction_run_id
    JOIN event_mention_links eml ON eml.event_mention_id=em.event_mention_id
    WHERE em.status_code<>'REJECTED'
), relation_rows AS (
    SELECT ee.document_id,ee.document_version_id,'EVENT' AS entity_kind,
           ee.event_id AS entity_id,'CANONICAL_EVENT' AS relation_basis,
           ee.relation_code AS relation_role,e.verification_level AS evidence_status,
           ee.confidence,ee.event_id,NULL AS claim_id,NULL AS mention_id
    FROM event_evidence ee JOIN events e ON e.event_id=ee.event_id
    WHERE e.lifecycle_status NOT IN ('REJECTED','MERGED')
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'ASSET',ea.asset_id,'CANONICAL_EVENT',
           ea.role_code,e.verification_level,coalesce(ea.confidence,ee.confidence),ee.event_id,
           ea.supporting_claim_id,NULL
    FROM event_evidence ee JOIN events e ON e.event_id=ee.event_id
    JOIN event_assets ea ON ea.event_id=ee.event_id
    WHERE e.lifecycle_status NOT IN ('REJECTED','MERGED')
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'ORGANIZATION',ep.organization_id,'CANONICAL_EVENT',
           ep.role_code,e.verification_level,coalesce(ep.confidence,ee.confidence),ee.event_id,
           ep.supporting_claim_id,NULL
    FROM event_evidence ee JOIN events e ON e.event_id=ee.event_id
    JOIN event_participants ep ON ep.event_id=ee.event_id
    WHERE e.lifecycle_status NOT IN ('REJECTED','MERGED')
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'PROJECT',ep.project_id,'CANONICAL_EVENT',
           ep.role_code,e.verification_level,coalesce(ep.confidence,ee.confidence),ee.event_id,
           ep.supporting_claim_id,NULL
    FROM event_evidence ee JOIN events e ON e.event_id=ee.event_id
    JOIN event_projects ep ON ep.event_id=ee.event_id
    WHERE e.lifecycle_status NOT IN ('REJECTED','MERGED')
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'SALE_PROCESS',sp.sale_process_id,'CANONICAL_EVENT',
           'EVENT_PROCESS',sp.evidence_status,ee.confidence,ee.event_id,sp.source_claim_id,NULL
    FROM event_evidence ee JOIN sale_processes sp ON sp.event_id=ee.event_id
    WHERE sp.review_status<>'REJECTED'
    UNION ALL
    SELECT ee.document_id,ee.document_version_id,'LP_MANDATE',lm.mandate_id,'CANONICAL_EVENT',
           'EVENT_MANDATE',lm.evidence_status,ee.confidence,ee.event_id,lm.source_claim_id,NULL
    FROM event_evidence ee JOIN lp_mandates lm ON lm.event_id=ee.event_id
    WHERE lm.review_status<>'REJECTED'
    UNION ALL
    SELECT dv.document_id,er.document_version_id,
           CASE WHEN mr.asset_id IS NOT NULL THEN 'ASSET'
                WHEN mr.project_id IS NOT NULL THEN 'PROJECT'
                WHEN mr.organization_id IS NOT NULL THEN 'ORGANIZATION' END,
           coalesce(mr.asset_id,mr.project_id,mr.organization_id),
           'RESOLVED_MENTION',mr.method_code,'RESOLVED',mr.match_score,NULL,NULL,m.mention_id
    FROM extraction_runs er
    JOIN document_versions dv ON dv.document_version_id=er.document_version_id
    JOIN mentions m ON m.extraction_run_id=er.extraction_run_id
    JOIN mention_resolutions mr ON mr.mention_id=m.mention_id
    WHERE mr.resolution_status='RESOLVED' AND mr.selected=1
      AND m.review_status<>'REJECTED'
      AND (mr.asset_id IS NOT NULL OR mr.project_id IS NOT NULL OR mr.organization_id IS NOT NULL)
    UNION ALL
    SELECT dv.document_id,er.document_version_id,
           CASE WHEN c.object_asset_id IS NOT NULL THEN 'ASSET'
                WHEN c.object_project_id IS NOT NULL THEN 'PROJECT'
                WHEN c.object_organization_id IS NOT NULL THEN 'ORGANIZATION' END,
           coalesce(c.object_asset_id,c.object_project_id,c.object_organization_id),
           'VERIFIED_CLAIM',c.predicate_code,c.verification_status,c.confidence,NULL,c.claim_id,NULL
    FROM claims c
    JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
    JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN document_versions dv ON dv.document_version_id=er.document_version_id
    WHERE c.verification_status='VERIFIED' AND c.review_status<>'REJECTED'
      AND (c.object_asset_id IS NOT NULL OR c.object_project_id IS NOT NULL OR c.object_organization_id IS NOT NULL)
    UNION ALL
    SELECT dv.document_id,er.document_version_id,
           CASE WHEN ca.asset_id IS NOT NULL THEN 'ASSET'
                WHEN ca.project_id IS NOT NULL THEN 'PROJECT'
                WHEN ca.organization_id IS NOT NULL THEN 'ORGANIZATION' END,
           coalesce(ca.asset_id,ca.project_id,ca.organization_id),
           'VERIFIED_CLAIM',ca.role_code,c.verification_status,
           coalesce(ca.confidence,c.confidence),NULL,c.claim_id,NULL
    FROM claims c
    JOIN claim_arguments ca ON ca.claim_id=c.claim_id
    JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
    JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN document_versions dv ON dv.document_version_id=er.document_version_id
    WHERE c.verification_status='VERIFIED' AND c.review_status<>'REJECTED'
      AND ca.argument_kind='ENTITY'
      AND (ca.asset_id IS NOT NULL OR ca.project_id IS NOT NULL OR ca.organization_id IS NOT NULL)
    UNION ALL
    SELECT dv.document_id,er.document_version_id,'LP_MANDATE',lm.mandate_id,'SOURCE_CLAIM',
           'MANDATE_SOURCE',lm.evidence_status,c.confidence,lm.event_id,c.claim_id,NULL
    FROM lp_mandates lm
    JOIN claims c ON c.claim_id=lm.source_claim_id
    JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
    JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN document_versions dv ON dv.document_version_id=er.document_version_id
    WHERE lm.review_status<>'REJECTED' AND c.review_status<>'REJECTED'
    UNION ALL
    SELECT dv.document_id,er.document_version_id,'SALE_PROCESS',sp.sale_process_id,'SOURCE_CLAIM',
           'PROCESS_SOURCE',sp.evidence_status,c.confidence,sp.event_id,c.claim_id,NULL
    FROM sale_processes sp
    JOIN claims c ON c.claim_id=sp.source_claim_id
    JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
    JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
    JOIN document_versions dv ON dv.document_version_id=er.document_version_id
    WHERE sp.review_status<>'REJECTED' AND c.review_status<>'REJECTED'
)
SELECT DISTINCT document_id,document_version_id,entity_kind,entity_id,relation_basis,
       relation_role,evidence_status,confidence,event_id,claim_id,mention_id
FROM relation_rows WHERE entity_kind IS NOT NULL AND entity_id IS NOT NULL;

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

-- ============================================================================
-- 16. Governed classification taxonomy and evidence-aware assignments
-- ============================================================================

CREATE TABLE classification_schemes (
    classification_scheme_id TEXT PRIMARY KEY,
    scheme_code TEXT NOT NULL UNIQUE,
    scheme_name_ko TEXT NOT NULL,
    scheme_name_en TEXT,
    description TEXT,
    cardinality_code TEXT NOT NULL CHECK(cardinality_code IN ('SINGLE','MULTIPLE')),
    is_hierarchical INTEGER NOT NULL DEFAULT 0 CHECK(is_hierarchical IN (0,1)),
    target_kinds_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(target_kinds_json)),
    vocabulary_version TEXT NOT NULL,
    governance_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(governance_status IN ('DRAFT','ACTIVE','DEPRECATED')),
    valid_from TEXT,
    valid_to TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to>=valid_from)
) STRICT;

CREATE TABLE classification_terms (
    classification_term_id TEXT PRIMARY KEY,
    classification_scheme_id TEXT NOT NULL REFERENCES classification_schemes(classification_scheme_id) ON DELETE RESTRICT,
    term_code TEXT NOT NULL,
    term_name_ko TEXT NOT NULL,
    term_name_en TEXT,
    parent_term_id TEXT,
    description TEXT,
    synonyms_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(synonyms_json)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_assignable INTEGER NOT NULL DEFAULT 1 CHECK(is_assignable IN (0,1)),
    governance_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(governance_status IN ('DRAFT','ACTIVE','DEPRECATED')),
    valid_from TEXT,
    valid_to TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(classification_scheme_id,term_code),
    UNIQUE(classification_scheme_id,classification_term_id),
    FOREIGN KEY(classification_scheme_id,parent_term_id)
      REFERENCES classification_terms(classification_scheme_id,classification_term_id) ON DELETE RESTRICT,
    CHECK(parent_term_id IS NULL OR parent_term_id<>classification_term_id),
    CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to>=valid_from)
) STRICT;

CREATE TABLE record_classifications (
    record_classification_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK(target_kind IN (
      'DOCUMENT','DOCUMENT_VERSION','EVENT','ASSET','ORGANIZATION','PROJECT',
      'LP_MANDATE','SALE_PROCESS','MACRO_SERIES','MACRO_OBSERVATION'
    )),
    target_id TEXT NOT NULL,
    classification_scheme_id TEXT NOT NULL,
    classification_term_id TEXT NOT NULL,
    assignment_role TEXT NOT NULL CHECK(assignment_role IN (
      'DIRECT','DERIVED','RELATED','MANUAL','LEGACY_BACKFILL'
    )),
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
    confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    classifier_version TEXT NOT NULL,
    evidence_status TEXT NOT NULL CHECK(evidence_status IN (
      'DIRECT_OFFICIAL','DERIVED_OFFICIAL','DIRECT_STRUCTURED','MEDIA_DIRECT',
      'MANUAL_REVIEWED','INFERRED','UNVERIFIED'
    )),
    source_claim_id TEXT,
    source_document_version_id TEXT,
    evidence_locator TEXT,
    derived_from_assignment_id TEXT REFERENCES record_classifications(record_classification_id) ON DELETE RESTRICT,
    review_status TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK(review_status IN (
      'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
    )),
    valid_from TEXT,
    valid_to TEXT,
    assigned_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    reviewed_at TEXT,
    lineage_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(lineage_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    FOREIGN KEY(classification_scheme_id,classification_term_id)
      REFERENCES classification_terms(classification_scheme_id,classification_term_id) ON DELETE RESTRICT,
    UNIQUE(target_kind,target_id,classification_scheme_id,classification_term_id,assignment_role,classifier_version),
    CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to>=valid_from),
    CHECK(derived_from_assignment_id IS NULL OR assignment_role IN ('DERIVED','RELATED'))
) STRICT;

CREATE INDEX ix_classification_terms_parent
ON classification_terms(classification_scheme_id,parent_term_id,sort_order);
CREATE INDEX ix_record_classifications_target
ON record_classifications(target_kind,target_id,review_status);
CREATE INDEX ix_record_classifications_term_target
ON record_classifications(classification_scheme_id,classification_term_id,target_kind);
CREATE INDEX ix_record_classifications_classifier
ON record_classifications(classifier_version,assignment_role,review_status);
CREATE INDEX ix_record_classifications_evidence
ON record_classifications(source_document_version_id,source_claim_id);
CREATE UNIQUE INDEX ux_record_classifications_primary_current
ON record_classifications(target_kind,target_id,classification_scheme_id)
WHERE is_primary=1 AND valid_to IS NULL AND review_status IN ('UNREVIEWED','PENDING','APPROVED');

INSERT INTO classification_schemes(
  classification_scheme_id,scheme_code,scheme_name_ko,scheme_name_en,description,
  cardinality_code,is_hierarchical,target_kinds_json,vocabulary_version
) VALUES
 ('scheme-market-category','MARKET_CATEGORY','시장 카테고리','Market category','시장 탐색의 상위 카테고리','MULTIPLE',1,'["DOCUMENT","EVENT","ASSET","PROJECT","LP_MANDATE","SALE_PROCESS"]','1.0.0'),
 ('scheme-document-purpose','DOCUMENT_PURPOSE','문서 목적','Document purpose','문서가 제공하는 정보와 근거의 역할','MULTIPLE',1,'["DOCUMENT","DOCUMENT_VERSION"]','1.0.0'),
 ('scheme-asset-class','ASSET_CLASS','자산 유형','Asset class','부동산 및 실물자산 유형','MULTIPLE',1,'["ASSET","DOCUMENT","EVENT","PROJECT"]','1.0.0'),
 ('scheme-organization-type','ORGANIZATION_TYPE','기관 유형','Organization type','기관의 기능 및 법적·시장 역할','MULTIPLE',1,'["ORGANIZATION","DOCUMENT","EVENT"]','1.0.0'),
 ('scheme-industry','INDUSTRY','산업 분류','Industry','기업 및 사건의 산업 분류','MULTIPLE',1,'["ORGANIZATION","DOCUMENT","EVENT"]','1.0.0'),
 ('scheme-investment-strategy','INVESTMENT_STRATEGY','투자 전략','Investment strategy','기관자금 및 투자전략','MULTIPLE',1,'["LP_MANDATE","ORGANIZATION","EVENT"]','1.0.0'),
 ('scheme-geography','GEOGRAPHY','지역 분류','Geography','국가·권역·행정구역 분류','MULTIPLE',1,'["DOCUMENT","EVENT","ASSET","ORGANIZATION","PROJECT","LP_MANDATE","SALE_PROCESS"]','1.0.0'),
 ('scheme-evidence-grade','EVIDENCE_GRADE','근거 등급','Evidence grade','분류 및 사실의 근거 신뢰도','SINGLE',1,'["DOCUMENT","EVENT","ASSET","ORGANIZATION","PROJECT","LP_MANDATE","SALE_PROCESS","MACRO_SERIES","MACRO_OBSERVATION"]','1.0.0');

INSERT INTO classification_terms(
  classification_term_id,classification_scheme_id,term_code,term_name_ko,term_name_en,parent_term_id,sort_order,is_assignable
) VALUES
 ('term-market-transaction','scheme-market-category','TRANSACTION','거래','Transaction',NULL,10,0),
 ('term-market-occupancy','scheme-market-category','OCCUPANCY','임대·점유','Occupancy',NULL,20,0),
 ('term-market-development','scheme-market-category','DEVELOPMENT','개발·공급','Development',NULL,30,0),
 ('term-market-capital','scheme-market-category','CAPITAL','자본·금융','Capital',NULL,40,0),
 ('term-market-corporate','scheme-market-category','CORPORATE','기업활동','Corporate',NULL,50,0),
 ('term-market-sale','scheme-market-category','SALE','매각','Sale','term-market-transaction',11,1),
 ('term-market-acquisition','scheme-market-category','ACQUISITION','매입','Acquisition','term-market-transaction',12,1),
 ('term-market-auction','scheme-market-category','AUCTION','경공매','Auction','term-market-transaction',13,1),
 ('term-market-lease','scheme-market-category','LEASE','임대차','Lease','term-market-occupancy',21,1),
 ('term-market-relocation','scheme-market-category','RELOCATION','이전','Relocation','term-market-occupancy',22,1),
 ('term-market-vacancy','scheme-market-category','VACANCY','공실','Vacancy','term-market-occupancy',23,1),
 ('term-market-supply','scheme-market-category','SUPPLY','공급','Supply','term-market-development',31,1),
 ('term-market-permit','scheme-market-category','PERMIT','인허가','Permit','term-market-development',32,1),
 ('term-market-completion','scheme-market-category','COMPLETION','준공','Completion','term-market-development',33,1),
 ('term-market-pf','scheme-market-category','PF','프로젝트금융','Project finance','term-market-capital',41,1),
 ('term-market-loan','scheme-market-category','LOAN','대출','Loan','term-market-capital',42,1),
 ('term-market-equity','scheme-market-category','EQUITY_INVESTMENT','지분투자','Equity investment','term-market-capital',43,1),
 ('term-market-fundraising','scheme-market-category','FUNDRAISING','자금모집','Fundraising','term-market-capital',44,1),
 ('term-market-lp-mandate','scheme-market-category','LP_MANDATE','기관출자','LP mandate','term-market-capital',45,1),
 ('term-market-corporate-action','scheme-market-category','CORPORATE_ACTION','기업행위','Corporate action','term-market-corporate',51,1),
 ('term-doc-official','scheme-document-purpose','OFFICIAL_SOURCE','공식 원문','Official source',NULL,10,1),
 ('term-doc-transaction','scheme-document-purpose','TRANSACTION_EVIDENCE','거래 근거','Transaction evidence',NULL,20,1),
 ('term-doc-company','scheme-document-purpose','COMPANY_EVIDENCE','기업 근거','Company evidence',NULL,30,1),
 ('term-doc-market','scheme-document-purpose','MARKET_INTELLIGENCE','시장 동향','Market intelligence',NULL,40,1),
 ('term-doc-procedure','scheme-document-purpose','PROCEDURE_NOTICE','절차 공고','Procedure notice',NULL,50,1),
 ('term-doc-research','scheme-document-purpose','RESEARCH','연구·분석','Research',NULL,60,1),
 ('term-strategy-real-estate','scheme-investment-strategy','REAL_ESTATE','부동산','Real estate',NULL,10,1),
 ('term-strategy-infrastructure','scheme-investment-strategy','INFRASTRUCTURE','인프라','Infrastructure',NULL,20,1),
 ('term-strategy-private-equity','scheme-investment-strategy','PRIVATE_EQUITY','사모주식','Private equity',NULL,30,1),
 ('term-strategy-private-debt','scheme-investment-strategy','PRIVATE_DEBT','사모대출','Private debt',NULL,40,1),
 ('term-strategy-real-assets','scheme-investment-strategy','REAL_ASSETS','실물자산','Real assets',NULL,50,1),
 ('term-strategy-multi-asset','scheme-investment-strategy','MULTI_ASSET','멀티에셋','Multi asset',NULL,60,1),
 ('term-strategy-secondaries','scheme-investment-strategy','SECONDARIES','세컨더리','Secondaries',NULL,70,1),
 ('term-evidence-official-direct','scheme-evidence-grade','OFFICIAL_DIRECT','공식 직접근거','Official direct',NULL,10,1),
 ('term-evidence-official-derived','scheme-evidence-grade','OFFICIAL_DERIVED','공식 파생근거','Official derived',NULL,20,1),
 ('term-evidence-media-direct','scheme-evidence-grade','MEDIA_DIRECT','언론 직접근거','Media direct',NULL,30,1),
 ('term-evidence-inferred','scheme-evidence-grade','INFERRED','추론','Inferred',NULL,40,1),
 ('term-evidence-unverified','scheme-evidence-grade','UNVERIFIED','미검증','Unverified',NULL,50,1);

CREATE VIEW v_record_classification_summary AS
SELECT r.target_kind,r.target_id,
       max(CASE WHEN s.scheme_code='MARKET_CATEGORY' AND r.is_primary=1 THEN t.term_code END) AS primary_market_category_code,
       max(CASE WHEN s.scheme_code='MARKET_CATEGORY' AND r.is_primary=1 THEN t.term_name_ko END) AS primary_market_category_label,
       max(CASE WHEN s.scheme_code='DOCUMENT_PURPOSE' AND r.is_primary=1 THEN t.term_code END) AS primary_document_purpose_code,
       max(CASE WHEN s.scheme_code='DOCUMENT_PURPOSE' AND r.is_primary=1 THEN t.term_name_ko END) AS primary_document_purpose_label,
       max(CASE WHEN s.scheme_code='ASSET_CLASS' AND r.is_primary=1 THEN t.term_code END) AS primary_asset_class_code,
       max(CASE WHEN s.scheme_code='ASSET_CLASS' AND r.is_primary=1 THEN t.term_name_ko END) AS primary_asset_class_label,
       max(CASE WHEN s.scheme_code='ORGANIZATION_TYPE' AND r.is_primary=1 THEN t.term_code END) AS primary_organization_type_code,
       max(CASE WHEN s.scheme_code='ORGANIZATION_TYPE' AND r.is_primary=1 THEN t.term_name_ko END) AS primary_organization_type_label,
       max(CASE WHEN s.scheme_code='INVESTMENT_STRATEGY' AND r.is_primary=1 THEN t.term_code END) AS primary_investment_strategy_code,
       max(CASE WHEN s.scheme_code='EVIDENCE_GRADE' AND r.is_primary=1 THEN t.term_code END) AS primary_evidence_grade_code,
       count(*) AS classification_count,
       max(r.assigned_at) AS classifications_updated_at
FROM record_classifications r
JOIN classification_schemes s ON s.classification_scheme_id=r.classification_scheme_id
JOIN classification_terms t ON t.classification_scheme_id=r.classification_scheme_id
                           AND t.classification_term_id=r.classification_term_id
WHERE r.review_status NOT IN ('REJECTED','SUPERSEDED')
  AND (r.valid_from IS NULL OR r.valid_from<=strftime('%Y-%m-%dT%H:%M:%fZ','now'))
  AND (r.valid_to IS NULL OR r.valid_to>strftime('%Y-%m-%dT%H:%M:%fZ','now'))
GROUP BY r.target_kind,r.target_id;

CREATE TABLE analytics_refresh_runs (
    analytics_refresh_run_id TEXT PRIMARY KEY,
    pipeline_code TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK(status_code IN ('RUNNING','COMPLETED','FAILED','ROLLED_BACK')),
    algorithm_version TEXT NOT NULL,
    window_start TEXT,
    window_end TEXT,
    source_scope_code TEXT NOT NULL DEFAULT 'ALL',
    input_count INTEGER NOT NULL DEFAULT 0,
    output_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json))
) STRICT;

CREATE TABLE keyword_dictionary (
    keyword_id TEXT PRIMARY KEY,
    normalized_term TEXT NOT NULL,
    display_term TEXT NOT NULL,
    term_kind TEXT NOT NULL CHECK(term_kind IN ('TOKEN','PHRASE','ENTITY')),
    status_code TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status_code IN ('ACTIVE','STOPWORD','DEPRECATED')),
    is_collection_bias INTEGER NOT NULL DEFAULT 0 CHECK(is_collection_bias IN (0,1)),
    algorithm_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(normalized_term,algorithm_version)
) STRICT;

CREATE TABLE keyword_observations_daily (
    keyword_observation_id TEXT PRIMARY KEY,
    bucket_date TEXT NOT NULL,
    keyword_id TEXT NOT NULL REFERENCES keyword_dictionary(keyword_id) ON DELETE RESTRICT,
    source_scope_code TEXT NOT NULL DEFAULT 'ALL',
    document_frequency INTEGER NOT NULL CHECK(document_frequency>=0),
    mention_count INTEGER NOT NULL CHECK(mention_count>=document_frequency),
    baseline_document_frequency REAL NOT NULL DEFAULT 0 CHECK(baseline_document_frequency>=0),
    burst_score REAL NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    source_scope_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(source_scope_json) AND json_type(source_scope_json)='object'),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object')
) STRICT;
CREATE UNIQUE INDEX ux_keyword_observation_identity ON keyword_observations_daily(bucket_date,keyword_id,source_scope_code,algorithm_version);
CREATE INDEX ix_keyword_observations_trend ON keyword_observations_daily(keyword_id,bucket_date,algorithm_version);
CREATE INDEX ix_keyword_observations_burst ON keyword_observations_daily(bucket_date,burst_score DESC,document_frequency DESC);

CREATE TABLE keyword_cooccurrences_daily (
    keyword_cooccurrence_id TEXT PRIMARY KEY,
    bucket_date TEXT NOT NULL,
    keyword_left_id TEXT NOT NULL REFERENCES keyword_dictionary(keyword_id) ON DELETE RESTRICT,
    keyword_right_id TEXT NOT NULL REFERENCES keyword_dictionary(keyword_id) ON DELETE RESTRICT,
    source_scope_code TEXT NOT NULL DEFAULT 'ALL',
    document_frequency INTEGER NOT NULL CHECK(document_frequency>0),
    computed_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    CHECK(keyword_left_id<keyword_right_id)
) STRICT;
CREATE UNIQUE INDEX ux_keyword_cooccurrence_identity ON keyword_cooccurrences_daily(bucket_date,keyword_left_id,keyword_right_id,source_scope_code,algorithm_version);
CREATE INDEX ix_keyword_cooccurrences_left ON keyword_cooccurrences_daily(keyword_left_id,bucket_date);
CREATE INDEX ix_keyword_cooccurrences_right ON keyword_cooccurrences_daily(keyword_right_id,bucket_date);

CREATE TABLE insight_signals (
    insight_signal_id TEXT PRIMARY KEY,
    signal_type TEXT NOT NULL CHECK(signal_type IN ('KEYWORD_BURST','COOCCURRENCE_SHIFT','VOLUME_ANOMALY')),
    signal_date TEXT NOT NULL,
    title TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK(review_status IN ('UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED')),
    severity_code TEXT NOT NULL CHECK(severity_code IN ('LOW','MEDIUM','HIGH')),
    keyword_id TEXT REFERENCES keyword_dictionary(keyword_id) ON DELETE RESTRICT,
    strength_score REAL NOT NULL CHECK(strength_score BETWEEN 0 AND 1),
    evidence_score REAL NOT NULL CHECK(evidence_score BETWEEN 0 AND 1),
    source_diversity_score REAL NOT NULL CHECK(source_diversity_score BETWEEN 0 AND 1),
    confidence_score REAL NOT NULL CHECK(confidence_score BETWEEN 0 AND 1),
    algorithm_version TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object')
) STRICT;
CREATE UNIQUE INDEX ux_insight_signal_identity ON insight_signals(signal_type,signal_date,coalesce(keyword_id,'__NONE__'),algorithm_version);
CREATE INDEX ix_insight_signals_review ON insight_signals(review_status,signal_date DESC,severity_code);
CREATE INDEX ix_insight_signals_keyword ON insight_signals(keyword_id);

CREATE TABLE insight_signal_evidence (
    insight_signal_evidence_id TEXT PRIMARY KEY,
    insight_signal_id TEXT NOT NULL REFERENCES insight_signals(insight_signal_id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('DOCUMENT','DOCUMENT_VERSION','EVENT','CLAIM')),
    target_id TEXT NOT NULL,
    evidence_role TEXT NOT NULL CHECK(evidence_role IN ('TRIGGER','SUPPORTING','CONTRADICTING')),
    source_document_version_id TEXT REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    evidence_rank INTEGER NOT NULL CHECK(evidence_rank>0),
    evidence_locator TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    created_at TEXT NOT NULL,
    UNIQUE(insight_signal_id,target_kind,target_id,evidence_role)
) STRICT;
CREATE INDEX ix_insight_signal_evidence_signal ON insight_signal_evidence(insight_signal_id,evidence_rank);
CREATE INDEX ix_insight_signal_evidence_version ON insight_signal_evidence(source_document_version_id);

CREATE TABLE analytics_model_registry (
    model_registry_id TEXT PRIMARY KEY,
    task_code TEXT NOT NULL CHECK(task_code IN ('TOPIC_INTERPRETATION','SIGNAL_SUMMARY','EMBEDDING')),
    provider_code TEXT NOT NULL CHECK(length(provider_code)>0),
    model_name TEXT NOT NULL CHECK(length(model_name)>0),
    model_version TEXT NOT NULL CHECK(length(model_version)>0),
    embedding_version TEXT NOT NULL CHECK(length(embedding_version)>0),
    prompt_version TEXT NOT NULL CHECK(length(prompt_version)>0),
    prompt_hash TEXT NOT NULL CHECK(length(prompt_hash)=64),
    status_code TEXT NOT NULL DEFAULT 'DISABLED' CHECK(status_code IN ('ENABLED','DISABLED','RETIRED')),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json) AND json_type(config_json)='object'),
    created_at TEXT NOT NULL,
    retired_at TEXT,
    UNIQUE(task_code,provider_code,model_name,model_version,embedding_version,prompt_version,prompt_hash)
) STRICT;

CREATE TABLE analytics_model_runs (
    model_run_id TEXT PRIMARY KEY,
    model_registry_id TEXT NOT NULL REFERENCES analytics_model_registry(model_registry_id) ON DELETE RESTRICT,
    status_code TEXT NOT NULL CHECK(status_code IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')),
    input_count INTEGER NOT NULL DEFAULT 0 CHECK(input_count>=0),
    output_count INTEGER NOT NULL DEFAULT 0 CHECK(output_count>=0),
    input_token_count INTEGER CHECK(input_token_count IS NULL OR input_token_count>=0),
    output_token_count INTEGER CHECK(output_token_count IS NULL OR output_token_count>=0),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object')
) STRICT;
CREATE INDEX ix_analytics_model_runs_registry ON analytics_model_runs(model_registry_id,started_at DESC);

CREATE TABLE insight_interpretations (
    interpretation_id TEXT PRIMARY KEY,
    insight_signal_id TEXT NOT NULL REFERENCES insight_signals(insight_signal_id) ON DELETE CASCADE,
    model_registry_id TEXT NOT NULL REFERENCES analytics_model_registry(model_registry_id) ON DELETE RESTRICT,
    model_run_id TEXT NOT NULL REFERENCES analytics_model_runs(model_run_id) ON DELETE RESTRICT,
    interpretation_status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(interpretation_status IN ('DRAFT','IN_REVIEW','APPROVED','REJECTED','SUPERSEDED')),
    headline TEXT NOT NULL,
    narrative_text TEXT NOT NULL,
    topic_labels_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(topic_labels_json) AND json_type(topic_labels_json)='array'),
    input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
    output_hash TEXT NOT NULL CHECK(length(output_hash)=64),
    generated_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(insight_signal_id,model_registry_id,input_hash,output_hash)
) STRICT;
CREATE INDEX ix_insight_interpretations_signal ON insight_interpretations(insight_signal_id,interpretation_status,generated_at DESC);
CREATE INDEX ix_insight_interpretations_registry ON insight_interpretations(model_registry_id,generated_at DESC);
CREATE INDEX ix_insight_interpretations_run ON insight_interpretations(model_run_id);

CREATE TABLE insight_interpretation_evidence (
    interpretation_evidence_id TEXT PRIMARY KEY,
    interpretation_id TEXT NOT NULL REFERENCES insight_interpretations(interpretation_id) ON DELETE CASCADE,
    insight_signal_evidence_id TEXT NOT NULL REFERENCES insight_signal_evidence(insight_signal_evidence_id) ON DELETE RESTRICT,
    evidence_role TEXT NOT NULL CHECK(evidence_role IN ('GROUNDING','CONTEXT','CONTRADICTING')),
    created_at TEXT NOT NULL,
    UNIQUE(interpretation_id,insight_signal_evidence_id,evidence_role)
) STRICT;
CREATE INDEX ix_interpretation_evidence_interpretation ON insight_interpretation_evidence(interpretation_id);
CREATE INDEX ix_interpretation_evidence_signal_evidence ON insight_interpretation_evidence(insight_signal_evidence_id);

-- Contextual intelligence feature schema 1.0.0 (baseline).
CREATE TABLE contextual_processing_campaigns (
    campaign_id TEXT PRIMARY KEY,
    campaign_code TEXT NOT NULL UNIQUE,
    corpus_cutoff_at TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    rule_set_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK(status_code IN ('DRAFT','RUNNING','COMPLETED','FAILED','SUPERSEDED')),
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    CHECK(completed_at IS NULL OR started_at IS NOT NULL)
) STRICT;

CREATE TABLE contextual_rule_sets (
    rule_set_id TEXT PRIMARY KEY,
    rule_set_code TEXT NOT NULL,
    version TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK(status_code IN ('DRAFT','ACTIVE','DEPRECATED','SUPERSEDED')),
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(rule_set_code,version),
    CHECK(status_code<>'ACTIVE' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
) STRICT;

CREATE TABLE contextual_rules (
    rule_id TEXT PRIMARY KEY,
    rule_set_id TEXT NOT NULL REFERENCES contextual_rule_sets(rule_set_id) ON DELETE RESTRICT,
    rule_code TEXT NOT NULL,
    event_domain TEXT NOT NULL CHECK(event_domain IN (
      'TRANSACTION','MANAGER_SELECTION','POLICY_REGULATION','MONETARY_POLICY',
      'GEOPOLITICS_TRADE','FINANCING_RESTRUCTURING','INDUSTRY_DEMAND',
      'MARKET_TREND','ASSET_REGIONAL_CHANGE'
    )),
    event_type TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    minimum_score REAL NOT NULL DEFAULT 1 CHECK(minimum_score>=0),
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json) AND json_type(definition_json)='object'),
    status_code TEXT NOT NULL CHECK(status_code IN ('DRAFT','ACTIVE','DEPRECATED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(rule_set_id,rule_code)
) STRICT;

CREATE TABLE contextual_document_runs (
    contextual_run_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    input_sha256 TEXT NOT NULL,
    status_code TEXT NOT NULL CHECK(status_code IN (
      'PENDING','RUNNING','COMPLETED','NO_CONTEXTUAL_EVENT','INSUFFICIENT_CONTENT',
      'ENTITY_UNRESOLVED','FAILED','SUPERSEDED'
    )),
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(candidate_count>=0),
    approved_count INTEGER NOT NULL DEFAULT 0 CHECK(approved_count>=0 AND approved_count<=candidate_count),
    error_code TEXT,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(campaign_id,document_version_id),
    CHECK(status_code NOT IN ('COMPLETED','NO_CONTEXTUAL_EVENT','INSUFFICIENT_CONTENT','ENTITY_UNRESOLVED','FAILED') OR completed_at IS NOT NULL)
) STRICT;

CREATE TABLE legacy_derived_records (
    legacy_record_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    target_kind TEXT NOT NULL CHECK(target_kind IN (
      'EXTRACTION_RUN','RECORD_CLASSIFICATION','ANALYTICS_REFRESH_RUN',
      'INSIGHT_SIGNAL','MODEL_INTERPRETATION'
    )),
    target_id TEXT NOT NULL,
    source_table TEXT NOT NULL CHECK(source_table IN (
      'extraction_runs','record_classifications','analytics_refresh_runs',
      'insight_signals','insight_interpretations'
    )),
    producer_run_id TEXT,
    original_status TEXT,
    legacy_reason TEXT NOT NULL,
    captured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(campaign_id,target_kind,target_id)
) STRICT;

CREATE TABLE contextual_event_frames (
    frame_id TEXT PRIMARY KEY,
    contextual_run_id TEXT NOT NULL REFERENCES contextual_document_runs(contextual_run_id) ON DELETE RESTRICT,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    source_event_mention_id TEXT REFERENCES event_mentions(event_mention_id) ON DELETE RESTRICT,
    canonical_event_id TEXT REFERENCES events(event_id) ON DELETE RESTRICT,
    extraction_key TEXT NOT NULL,
    event_domain TEXT NOT NULL CHECK(event_domain IN (
      'TRANSACTION','MANAGER_SELECTION','POLICY_REGULATION','MONETARY_POLICY',
      'GEOPOLITICS_TRADE','FINANCING_RESTRUCTURING','INDUSTRY_DEMAND',
      'MARKET_TREND','ASSET_REGIONAL_CHANGE'
    )),
    event_type TEXT NOT NULL,
    event_subtype TEXT,
    stage_code TEXT,
    process_type TEXT,
    action_code TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    temporal_basis TEXT NOT NULL CHECK(temporal_basis IN (
      'EVENT_DATE','ANNOUNCEMENT_DATE','EFFECTIVE_DATE','PUBLICATION_DATE',
      'EXPECTED_DATE','PERIOD','UNKNOWN'
    )),
    event_date_start TEXT,
    event_date_end TEXT,
    modality_code TEXT NOT NULL CHECK(modality_code IN (
      'FACTUAL','PLANNED','POSSIBLE','FORECAST','REPORTED','HISTORICAL','CONDITIONAL','UNKNOWN'
    )),
    polarity_code TEXT NOT NULL CHECK(polarity_code IN ('AFFIRMED','NEGATED','UNCERTAIN')),
    source_grade TEXT NOT NULL CHECK(source_grade IN (
      'OFFICIAL_DIRECT','OFFICIAL_DERIVED','STRUCTURED_DIRECT','MEDIA_DIRECT',
      'MULTI_SOURCE_CORROBORATED','MODEL_INFERRED','UNVERIFIED'
    )),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    review_status TEXT NOT NULL CHECK(review_status IN (
      'CANDIDATE','REVIEW_READY','APPROVED','REJECTED','SUPERSEDED'
    )),
    extraction_method TEXT NOT NULL CHECK(extraction_method IN ('RULE','WEIGHTED_MODEL','HYBRID','HUMAN')),
    rule_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    evidence_start INTEGER,
    evidence_end INTEGER,
    evidence_locator TEXT,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(contextual_run_id,extraction_key),
    CHECK(event_date_end IS NULL OR event_date_start IS NULL OR event_date_end>=event_date_start),
    CHECK((evidence_start IS NULL AND evidence_end IS NULL) OR
          (evidence_start IS NOT NULL AND evidence_end IS NOT NULL AND evidence_start>=0 AND evidence_end>evidence_start)),
    CHECK(review_status<>'APPROVED' OR
          (length(trim(evidence_text))>0 AND approved_by IS NOT NULL AND approved_at IS NOT NULL))
) STRICT;

CREATE TABLE contextual_frame_participants (
    frame_participant_id TEXT PRIMARY KEY,
    frame_id TEXT NOT NULL REFERENCES contextual_event_frames(frame_id) ON DELETE CASCADE,
    role_code TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0 CHECK(ordinal>=0),
    entity_kind TEXT NOT NULL CHECK(entity_kind IN ('ORGANIZATION','PERSON','COUNTRY','AUTHORITY','UNKNOWN')),
    entity_id TEXT,
    surface_text TEXT NOT NULL,
    mention_id TEXT REFERENCES mentions(mention_id) ON DELETE RESTRICT,
    resolution_status TEXT NOT NULL CHECK(resolution_status IN ('UNRESOLVED','CANDIDATE','RESOLVED','REJECTED')),
    confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    evidence_text TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(frame_id,role_code,ordinal),
    CHECK(resolution_status<>'RESOLVED' OR entity_id IS NOT NULL)
) STRICT;

CREATE TABLE contextual_frame_targets (
    frame_target_id TEXT PRIMARY KEY,
    frame_id TEXT NOT NULL REFERENCES contextual_event_frames(frame_id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK(target_kind IN (
      'ASSET','ASSET_CLASS','PROJECT','REGION','INDUSTRY','ORGANIZATION','MARKET','POLICY_AREA','COMMODITY'
    )),
    target_id TEXT,
    target_code TEXT,
    surface_text TEXT NOT NULL,
    role_code TEXT NOT NULL DEFAULT 'AFFECTED_TARGET',
    resolution_status TEXT NOT NULL CHECK(resolution_status IN ('UNRESOLVED','CANDIDATE','RESOLVED','REJECTED')),
    confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(frame_id,target_kind,role_code,surface_text),
    CHECK(resolution_status<>'RESOLVED' OR target_id IS NOT NULL OR target_code IS NOT NULL)
) STRICT;

CREATE TABLE contextual_impact_assertions (
    impact_assertion_id TEXT PRIMARY KEY,
    cause_frame_id TEXT NOT NULL REFERENCES contextual_event_frames(frame_id) ON DELETE CASCADE,
    effect_frame_id TEXT REFERENCES contextual_event_frames(frame_id) ON DELETE RESTRICT,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('ASSET','ASSET_CLASS','PROJECT','REGION','INDUSTRY','ORGANIZATION','MARKET','COST','DEMAND','SUPPLY','LIQUIDITY','VALUE')),
    target_id TEXT,
    target_code TEXT,
    target_text TEXT NOT NULL,
    mechanism_code TEXT NOT NULL,
    direction_code TEXT NOT NULL CHECK(direction_code IN ('INCREASE','DECREASE','POSITIVE','NEGATIVE','MIXED','UNCERTAIN')),
    horizon_code TEXT NOT NULL CHECK(horizon_code IN ('IMMEDIATE','SHORT_TERM','MEDIUM_TERM','LONG_TERM','UNKNOWN')),
    assertion_basis TEXT NOT NULL CHECK(assertion_basis IN (
      'DIRECT_FACT','OFFICIAL_FORECAST','INDUSTRY_ASSESSMENT','MODEL_DERIVED','ANALYST_HYPOTHESIS','UNCONFIRMED'
    )),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    review_status TEXT NOT NULL CHECK(review_status IN ('CANDIDATE','REVIEW_READY','APPROVED','REJECTED','SUPERSEDED')),
    evidence_text TEXT NOT NULL,
    source_claim_id TEXT REFERENCES claims(claim_id) ON DELETE RESTRICT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    CHECK(review_status<>'APPROVED' OR (length(trim(evidence_text))>0 AND assertion_basis<>'UNCONFIRMED'))
) STRICT;

CREATE TABLE contextual_review_decisions (
    review_decision_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('FRAME','PARTICIPANT','TARGET','IMPACT_ASSERTION')),
    target_id TEXT NOT NULL,
    decision_code TEXT NOT NULL CHECK(decision_code IN ('APPROVE','CORRECT','REJECT','SUPERSEDE','DEFER')),
    before_json TEXT NOT NULL CHECK(json_valid(before_json) AND json_type(before_json)='object'),
    after_json TEXT NOT NULL CHECK(json_valid(after_json) AND json_type(after_json)='object'),
    reason_code TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    eligible_for_training INTEGER NOT NULL DEFAULT 1 CHECK(eligible_for_training IN (0,1)),
    reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(target_kind,target_id,reviewed_at)
) STRICT;

CREATE TABLE contextual_search_records (
    search_record_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES contextual_processing_campaigns(campaign_id) ON DELETE RESTRICT,
    frame_id TEXT REFERENCES contextual_event_frames(frame_id) ON DELETE CASCADE,
    record_mode TEXT NOT NULL CHECK(record_mode IN ('APPROVED','CANDIDATE','LEGACY')),
    source_record_kind TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    event_domain TEXT,
    event_type TEXT,
    event_subtype TEXT,
    stage_code TEXT,
    process_type TEXT,
    action_code TEXT,
    event_date TEXT,
    temporal_basis TEXT,
    participant_roles_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(participant_roles_json) AND json_type(participant_roles_json)='array'),
    participant_entity_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(participant_entity_ids_json) AND json_type(participant_entity_ids_json)='array'),
    asset_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(asset_ids_json) AND json_type(asset_ids_json)='array'),
    region_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(region_ids_json) AND json_type(region_ids_json)='array'),
    industry_codes_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(industry_codes_json) AND json_type(industry_codes_json)='array'),
    impact_directions_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(impact_directions_json) AND json_type(impact_directions_json)='array'),
    source_grade TEXT,
    confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    review_status TEXT NOT NULL,
    evidence_text TEXT,
    evidence_locator TEXT,
    rule_version TEXT,
    model_version TEXT,
    search_text TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    UNIQUE(campaign_id,record_mode,source_record_kind,source_record_id),
    CHECK((record_mode='APPROVED' AND review_status='APPROVED') OR
          (record_mode='CANDIDATE' AND review_status IN ('CANDIDATE','REVIEW_READY')) OR
          record_mode='LEGACY')
) STRICT;

CREATE INDEX ix_contextual_campaign_status ON contextual_processing_campaigns(status_code,corpus_cutoff_at);
CREATE INDEX ix_contextual_runs_campaign_status ON contextual_document_runs(campaign_id,status_code,document_version_id);
CREATE INDEX ix_contextual_legacy_campaign_kind ON legacy_derived_records(campaign_id,target_kind,source_table);
CREATE INDEX ix_contextual_frames_mode ON contextual_event_frames(review_status,event_domain,event_type,event_date_start);
CREATE INDEX ix_contextual_frames_document ON contextual_event_frames(document_version_id,review_status);
CREATE INDEX ix_contextual_frames_canonical ON contextual_event_frames(canonical_event_id,review_status);
CREATE INDEX ix_contextual_participants_lookup ON contextual_frame_participants(role_code,entity_id,resolution_status);
CREATE INDEX ix_contextual_targets_lookup ON contextual_frame_targets(target_kind,target_code,target_id);
CREATE INDEX ix_contextual_impacts_lookup ON contextual_impact_assertions(direction_code,target_kind,review_status);
CREATE INDEX ix_contextual_search_filters ON contextual_search_records(record_mode,event_domain,event_type,stage_code,event_date);
CREATE INDEX ix_contextual_search_grade ON contextual_search_records(record_mode,source_grade,review_status);

INSERT INTO schema_meta(schema_key, schema_value) VALUES
    ('schema_name', 'cre-market-intelligence-sqlite'),
    ('schema_version', '3.5.0'),
    ('authority_model', 'source-document-to-mention-to-claim-to-event'),
    ('created_for', 'serverless-local-accumulation'),
    ('contextual_intelligence_schema_version', '1.0.0');

COMMIT;
