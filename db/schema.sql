-- DEPRECATED V1: Do not use for new deployments.
-- Current authority: db/v2/schema.sql (SQLite 3).
-- Commercial Real Estate Market Intelligence
-- PostgreSQL 15+ / Supabase compatible Stage 1 schema
-- Authority: docs/01-system-contract.md

begin;

create extension if not exists pgcrypto;
create extension if not exists pg_trgm;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Category-first discovery registry
-- ─────────────────────────────────────────────────────────────────────────────

create table categories (
    category_id       smallint generated always as identity primary key,
    code              text not null unique,
    name_ko           text not null unique,
    parent_id         smallint references categories(category_id),
    is_active         boolean not null default true,
    created_at        timestamptz not null default now()
);

create table collection_sources (
    source_id          uuid primary key default gen_random_uuid(),
    code               text not null unique,
    name_ko            text not null,
    base_url           text,
    source_kind        text not null check (source_kind in (
                         'search_api','rss','official_api','official_site',
                         'media','party_site','statistics','manual_system'
                       )),
    source_role        text not null check (source_role in (
                         'discovery','party_confirmation','official_verification',
                         'market_context','manual_verification'
                       )),
    collection_policy  text not null check (collection_policy in (
                         'API_ALLOWED','RSS_ONLY','PUBLIC_LOW_RATE',
                         'METADATA_ONLY','MANUAL_REVIEW','PROHIBITED'
                       )),
    quality_tier       smallint check (quality_tier between 0 and 4),
    policy_checked_at  timestamptz,
    policy_notes       text,
    is_active          boolean not null default true,
    config             jsonb not null default '{}'::jsonb,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create table search_rules (
    search_rule_id     uuid primary key default gen_random_uuid(),
    category_id        smallint not null references categories(category_id),
    source_id          uuid references collection_sources(source_id),
    rule_code          text not null,
    rule_version       text not null,
    name_ko            text not null,
    query_template     text not null,
    query_config       jsonb not null default '{}'::jsonb,
    cadence_minutes    integer check (cadence_minutes is null or cadence_minutes > 0),
    is_active          boolean not null default true,
    valid_from         timestamptz not null default now(),
    valid_to           timestamptz,
    created_at         timestamptz not null default now(),
    unique (rule_code, rule_version),
    check (valid_to is null or valid_to > valid_from)
);

create table search_runs (
    search_run_id      uuid primary key default gen_random_uuid(),
    search_rule_id     uuid references search_rules(search_rule_id),
    provider_code      text not null,
    query_text         text not null,
    query_config       jsonb not null default '{}'::jsonb,
    rule_version       text not null,
    cursor_in          text,
    cursor_out         text,
    status             text not null default 'queued' check (status in (
                         'queued','running','completed','partial','failed'
                       )),
    result_count       integer check (result_count is null or result_count >= 0),
    started_at         timestamptz,
    completed_at       timestamptz,
    error_code         text,
    error_message      text,
    created_at         timestamptz not null default now(),
    check (completed_at is null or started_at is null or completed_at >= started_at)
);

create table search_run_categories (
    search_run_id      uuid not null references search_runs(search_run_id) on delete cascade,
    category_id        smallint not null references categories(category_id),
    is_primary         boolean not null default false,
    primary key (search_run_id, category_id)
);

create unique index uq_search_run_primary_category
    on search_run_categories(search_run_id)
    where is_primary;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Source documents and search lineage
-- ─────────────────────────────────────────────────────────────────────────────

create table document_groups (
    document_group_id  uuid primary key default gen_random_uuid(),
    group_type         text not null check (group_type in (
                         'same_article_version','syndicated_copy','same_press_release','other'
                       )),
    representative_url text,
    created_at         timestamptz not null default now()
);

create table source_documents (
    source_document_id uuid primary key default gen_random_uuid(),
    source_id          uuid references collection_sources(source_id),
    document_group_id  uuid references document_groups(document_group_id),
    canonical_url      text not null,
    title              text,
    publisher_name     text,
    author_name        text,
    document_type      text not null default 'article' check (document_type in (
                         'article','press_release','disclosure','notice','bid_notice',
                         'report','rss_item','api_record','legal_document','other'
                       )),
    published_at       timestamptz,
    modified_at        timestamptz,
    retrieved_at       timestamptz not null default now(),
    language_code      text not null default 'ko',
    mime_type          text,
    content_sha256     text not null,
    snippet_text       text,
    stored_text        text,
    raw_payload_uri    text,
    rights_status      text not null default 'metadata_only' check (rights_status in (
                         'full_storage_allowed','excerpt_allowed','metadata_only',
                         'manual_access','unknown'
                       )),
    access_status      text not null default 'accessible' check (access_status in (
                         'accessible','login_required','paywalled','blocked',
                         'removed','error','manual_only'
                       )),
    source_quality     numeric(4,3) check (source_quality between 0 and 1),
    metadata           jsonb not null default '{}'::jsonb,
    unique (canonical_url, content_sha256),
    check (stored_text is null or rights_status = 'full_storage_allowed')
);

create table source_document_runs (
    search_run_id       uuid not null references search_runs(search_run_id) on delete cascade,
    source_document_id  uuid not null references source_documents(source_document_id),
    result_rank         integer check (result_rank is null or result_rank > 0),
    search_snippet      text,
    discovered_at       timestamptz not null default now(),
    primary key (search_run_id, source_document_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Canonical asset, project and participant masters
-- ─────────────────────────────────────────────────────────────────────────────

create table assets (
    asset_id             uuid primary key default gen_random_uuid(),
    canonical_name       text not null,
    asset_type           text,
    asset_subtype        text,
    road_address         text,
    jibun_address        text,
    postal_code          text,
    legal_dong_code      text,
    latitude             numeric(9,6) check (latitude between -90 and 90),
    longitude            numeric(9,6) check (longitude between -180 and 180),
    building_mgmt_no     text,
    parcel_key           text,
    status               text not null default 'active' check (status in (
                           'active','inactive','merged'
                         )),
    merged_into_asset_id uuid references assets(asset_id),
    normalized_payload   jsonb not null default '{}'::jsonb,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now(),
    check (merged_into_asset_id is null or merged_into_asset_id <> asset_id),
    check (
      (status = 'merged' and merged_into_asset_id is not null)
      or (status <> 'merged' and merged_into_asset_id is null)
    )
);

create table asset_aliases (
    asset_alias_id      uuid primary key default gen_random_uuid(),
    asset_id            uuid not null references assets(asset_id) on delete cascade,
    alias_name          text not null,
    alias_type          text not null default 'other',
    normalized_alias    text not null,
    unique (asset_id, normalized_alias)
);

create table projects (
    project_id             uuid primary key default gen_random_uuid(),
    canonical_name         text not null,
    project_type           text,
    representative_address text,
    parcel_set_hash        text,
    status                 text not null default 'active' check (status in (
                             'active','completed','cancelled','merged'
                           )),
    merged_into_project_id uuid references projects(project_id),
    normalized_payload     jsonb not null default '{}'::jsonb,
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now(),
    check (merged_into_project_id is null or merged_into_project_id <> project_id),
    check (
      (status = 'merged' and merged_into_project_id is not null)
      or (status <> 'merged' and merged_into_project_id is null)
    )
);

create table project_assets (
    project_id          uuid not null references projects(project_id),
    asset_id            uuid not null references assets(asset_id),
    relation_type       text not null default 'contains' check (relation_type in (
                         'contains','development_site','phase','resulting_asset','related'
                       )),
    valid_from          date,
    valid_to            date,
    primary key (project_id, asset_id, relation_type),
    check (valid_to is null or valid_from is null or valid_to >= valid_from)
);

create table entities (
    entity_id             uuid primary key default gen_random_uuid(),
    entity_type           text not null check (entity_type in (
                           'company','fund','reit','spc','person','government',
                           'financial_institution','association','other'
                         )),
    canonical_name        text not null,
    corporate_no          text,
    business_no           text,
    dart_corp_code        text,
    stock_code            text,
    country_code          char(2) not null default 'KR',
    status                text not null default 'active' check (status in (
                           'active','inactive','merged'
                         )),
    merged_into_entity_id uuid references entities(entity_id),
    metadata              jsonb not null default '{}'::jsonb,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    check (merged_into_entity_id is null or merged_into_entity_id <> entity_id),
    check (
      (status = 'merged' and merged_into_entity_id is not null)
      or (status <> 'merged' and merged_into_entity_id is null)
    )
);

create table entity_aliases (
    entity_alias_id     uuid primary key default gen_random_uuid(),
    entity_id           uuid not null references entities(entity_id) on delete cascade,
    alias_name          text not null,
    normalized_alias    text not null,
    alias_type          text not null default 'other',
    unique (entity_id, normalized_alias)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Document-level event candidates and unresolved mentions
-- ─────────────────────────────────────────────────────────────────────────────

create table event_candidates (
    event_candidate_id  uuid primary key default gen_random_uuid(),
    source_document_id  uuid not null references source_documents(source_document_id),
    search_run_id       uuid references search_runs(search_run_id),
    extraction_key      text not null,
    event_type_hint     text,
    stage_hint          text,
    title_raw           text,
    summary_raw         text,
    event_date_start    date,
    event_date_end      date,
    date_precision      text check (date_precision is null or date_precision in (
                          'day','month','quarter','year','range','unknown'
                        )),
    extracted_payload   jsonb not null default '{}'::jsonb,
    extraction_model    text,
    extraction_version  text,
    extraction_confidence numeric(4,3) check (extraction_confidence between 0 and 1),
    status              text not null default 'discovered' check (status in (
                         'discovered','extracted','needs_resolution','ready_for_review',
                         'approved','rejected','merged'
                       )),
    rejection_reason    text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    unique (source_document_id, extraction_key),
    check (event_date_end is null or event_date_start is null or event_date_end >= event_date_start)
);

create table candidate_categories (
    event_candidate_id  uuid not null references event_candidates(event_candidate_id) on delete cascade,
    category_id         smallint not null references categories(category_id),
    is_primary_hint     boolean not null default false,
    confidence          numeric(4,3) not null check (confidence between 0 and 1),
    primary key (event_candidate_id, category_id)
);

create unique index uq_candidate_primary_category_hint
    on candidate_categories(event_candidate_id)
    where is_primary_hint;

create table candidate_asset_mentions (
    asset_mention_id    uuid primary key default gen_random_uuid(),
    event_candidate_id  uuid not null references event_candidates(event_candidate_id) on delete cascade,
    raw_name            text,
    raw_address         text,
    raw_payload         jsonb not null default '{}'::jsonb,
    asset_id            uuid references assets(asset_id),
    resolution_status   text not null default 'unresolved' check (resolution_status in (
                         'unresolved','candidate_match','resolved','ambiguous','not_an_asset'
                       )),
    match_confidence    numeric(4,3) check (match_confidence between 0 and 1),
    resolution_note     text
);

create table candidate_project_mentions (
    project_mention_id  uuid primary key default gen_random_uuid(),
    event_candidate_id  uuid not null references event_candidates(event_candidate_id) on delete cascade,
    raw_name            text,
    raw_location        text,
    raw_payload         jsonb not null default '{}'::jsonb,
    project_id          uuid references projects(project_id),
    resolution_status   text not null default 'unresolved' check (resolution_status in (
                         'unresolved','candidate_match','resolved','ambiguous','not_a_project'
                       )),
    match_confidence    numeric(4,3) check (match_confidence between 0 and 1),
    resolution_note     text
);

create table candidate_entity_mentions (
    entity_mention_id   uuid primary key default gen_random_uuid(),
    event_candidate_id  uuid not null references event_candidates(event_candidate_id) on delete cascade,
    raw_name            text not null,
    role_hint           text,
    raw_payload         jsonb not null default '{}'::jsonb,
    entity_id           uuid references entities(entity_id),
    resolution_status   text not null default 'unresolved' check (resolution_status in (
                         'unresolved','candidate_match','resolved','ambiguous','not_an_entity'
                       )),
    match_confidence    numeric(4,3) check (match_confidence between 0 and 1),
    resolution_note     text
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. Canonical approved events
-- ─────────────────────────────────────────────────────────────────────────────

create table transaction_groups (
    transaction_group_id uuid primary key default gen_random_uuid(),
    canonical_name       text,
    group_type           text not null default 'related_events',
    created_at           timestamptz not null default now()
);

create table events (
    event_id             uuid primary key default gen_random_uuid(),
    transaction_group_id uuid references transaction_groups(transaction_group_id),
    previous_event_id    uuid references events(event_id),
    supersedes_event_id  uuid references events(event_id),
    canonical_title      text not null,
    summary              text,
    event_subtype        text,
    event_stage          text,
    event_date_start     date,
    event_date_end       date,
    date_precision       text not null default 'unknown' check (date_precision in (
                           'day','month','quarter','year','range','unknown'
                         )),
    lifecycle_status     text not null default 'draft' check (lifecycle_status in (
                           'draft','approved','published','withdrawn','merged'
                         )),
    review_status        text not null default 'unreviewed' check (review_status in (
                           'unreviewed','in_review','changes_requested','approved','rejected'
                         )),
    verification_level   text not null default 'V0' check (verification_level in (
                           'V0','V1','V2','V3','V4'
                         )),
    overall_confidence   numeric(4,3) check (overall_confidence between 0 and 1),
    confidence_method    text,
    confidence_version   text,
    merged_into_event_id uuid references events(event_id),
    approved_at          timestamptz,
    published_at         timestamptz,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now(),
    check (event_date_end is null or event_date_start is null or event_date_end >= event_date_start),
    check (previous_event_id is null or previous_event_id <> event_id),
    check (supersedes_event_id is null or supersedes_event_id <> event_id),
    check (merged_into_event_id is null or merged_into_event_id <> event_id),
    check (
      (lifecycle_status = 'merged' and merged_into_event_id is not null)
      or (lifecycle_status <> 'merged' and merged_into_event_id is null)
    )
);

create table candidate_event_links (
    event_candidate_id  uuid not null references event_candidates(event_candidate_id),
    event_id            uuid not null references events(event_id),
    relation_type       text not null check (relation_type in (
                         'primary','supporting','duplicate','split_source'
                       )),
    linked_at           timestamptz not null default now(),
    primary key (event_candidate_id, event_id, relation_type)
);

create unique index uq_candidate_primary_event
    on candidate_event_links(event_candidate_id)
    where relation_type = 'primary';

create table evidence_items (
    evidence_id          uuid primary key default gen_random_uuid(),
    source_document_id   uuid not null references source_documents(source_document_id),
    event_candidate_id   uuid references event_candidates(event_candidate_id),
    event_id             uuid references events(event_id),
    locator_type         text not null default 'text' check (locator_type in (
                          'text','paragraph','page','table_cell','timestamp','json_path'
                        )),
    locator              text,
    quote_text           text,
    evidence_payload     jsonb not null default '{}'::jsonb,
    extraction_confidence numeric(4,3) check (extraction_confidence between 0 and 1),
    created_at           timestamptz not null default now(),
    check (event_candidate_id is not null or event_id is not null)
);

create table event_categories (
    event_id            uuid not null references events(event_id),
    category_id         smallint not null references categories(category_id),
    is_primary          boolean not null default false,
    confidence          numeric(4,3) check (confidence between 0 and 1),
    evidence_id         uuid references evidence_items(evidence_id),
    primary key (event_id, category_id)
);

create unique index uq_event_primary_category
    on event_categories(event_id)
    where is_primary;

create table event_assets (
    event_id            uuid not null references events(event_id),
    asset_id            uuid not null references assets(asset_id),
    role_code           text not null default 'subject' check (role_code in (
                         'subject','portfolio_member','collateral','leased_asset',
                         'development_site','resulting_asset','other'
                       )),
    confidence          numeric(4,3) check (confidence between 0 and 1),
    evidence_id         uuid references evidence_items(evidence_id),
    primary key (event_id, asset_id, role_code)
);

create table event_projects (
    event_id            uuid not null references events(event_id),
    project_id          uuid not null references projects(project_id),
    role_code           text not null default 'subject' check (role_code in (
                         'subject','financed_project','permitted_project',
                         'supply_project','related'
                       )),
    confidence          numeric(4,3) check (confidence between 0 and 1),
    evidence_id         uuid references evidence_items(evidence_id),
    primary key (event_id, project_id, role_code)
);

create table event_entities (
    event_id            uuid not null references events(event_id),
    entity_id           uuid not null references entities(entity_id),
    role_code           text not null,
    confidence          numeric(4,3) check (confidence between 0 and 1),
    evidence_id         uuid references evidence_items(evidence_id),
    primary key (event_id, entity_id, role_code)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Field-level provenance and official verification
-- ─────────────────────────────────────────────────────────────────────────────

create table field_definitions (
    field_code          text primary key,
    subject_type        text not null check (subject_type in (
                         'event_candidate','event','asset','project','entity'
                       )),
    data_type           text not null check (data_type in (
                         'text','numeric','date','boolean','json','entity_ref','asset_ref','project_ref'
                       )),
    description         text,
    is_multi_value      boolean not null default false,
    created_at          timestamptz not null default now()
);

create table field_assertions (
    field_assertion_id  uuid primary key default gen_random_uuid(),
    event_candidate_id  uuid references event_candidates(event_candidate_id),
    event_id            uuid references events(event_id),
    asset_id            uuid references assets(asset_id),
    project_id          uuid references projects(project_id),
    entity_id           uuid references entities(entity_id),
    field_code          text not null references field_definitions(field_code),
    value_json          jsonb not null,
    normalized_value    text,
    unit_code           text,
    value_basis         text,
    evidence_id         uuid not null references evidence_items(evidence_id),
    derivation_type     text not null default 'extracted' check (derivation_type in (
                         'extracted','api','calculated','manual','inherited','merged'
                       )),
    confidence          numeric(4,3) not null check (confidence between 0 and 1),
    verification_status text not null default 'unverified' check (verification_status in (
                         'unverified','pending','verified','contradicted','inconclusive'
                       )),
    review_status       text not null default 'unreviewed' check (review_status in (
                         'unreviewed','in_review','accepted','rejected','superseded'
                       )),
    is_selected         boolean not null default false,
    asserted_at         timestamptz not null default now(),
    check (num_nonnulls(event_candidate_id, event_id, asset_id, project_id, entity_id) = 1)
);

create unique index uq_selected_candidate_field
    on field_assertions(event_candidate_id, field_code)
    where is_selected and event_candidate_id is not null;
create unique index uq_selected_event_field
    on field_assertions(event_id, field_code)
    where is_selected and event_id is not null;
create unique index uq_selected_asset_field
    on field_assertions(asset_id, field_code)
    where is_selected and asset_id is not null;
create unique index uq_selected_project_field
    on field_assertions(project_id, field_code)
    where is_selected and project_id is not null;
create unique index uq_selected_entity_field
    on field_assertions(entity_id, field_code)
    where is_selected and entity_id is not null;

create table api_verifications (
    api_verification_id uuid primary key default gen_random_uuid(),
    provider_code       text not null,
    endpoint_code       text not null,
    request_hash        text not null,
    request_params_redacted jsonb not null default '{}'::jsonb,
    response_payload_uri text,
    transport_status    text not null check (transport_status in (
                         'pending','success','timeout','unauthorized','rate_limited','error'
                       )),
    verification_result text check (verification_result is null or verification_result in (
                         'confirmed','contradicted','not_found','inconclusive'
                       )),
    confidence          numeric(4,3) check (confidence between 0 and 1),
    provider_record_at  timestamptz,
    verified_at         timestamptz,
    error_code          text,
    created_at          timestamptz not null default now(),
    unique (provider_code, endpoint_code, request_hash)
);

comment on column api_verifications.request_params_redacted is
'Credential values and secrets must never be stored; keep only redacted parameters and request fingerprints.';

create table field_assertion_verifications (
    field_assertion_id   uuid not null references field_assertions(field_assertion_id) on delete cascade,
    api_verification_id  uuid not null references api_verifications(api_verification_id),
    result               text not null check (result in (
                           'confirmed','contradicted','not_found','inconclusive'
                         )),
    note                 text,
    primary key (field_assertion_id, api_verification_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. Manual review, duplicate detection and non-destructive merge
-- ─────────────────────────────────────────────────────────────────────────────

create table manual_reviews (
    manual_review_id    uuid primary key default gen_random_uuid(),
    event_candidate_id  uuid references event_candidates(event_candidate_id),
    event_id            uuid references events(event_id),
    field_assertion_id  uuid references field_assertions(field_assertion_id),
    asset_id            uuid references assets(asset_id),
    project_id          uuid references projects(project_id),
    entity_id           uuid references entities(entity_id),
    review_type         text not null check (review_type in (
                         'candidate_approval','event_approval','field_review',
                         'duplicate_merge','asset_resolution','project_resolution','entity_resolution'
                       )),
    status              text not null default 'pending' check (status in (
                         'pending','in_progress','approved','rejected','changes_requested'
                       )),
    priority            smallint not null default 3 check (priority between 1 and 5),
    reviewer_id         text,
    decision_reason     text,
    override_reason     text,
    review_payload      jsonb not null default '{}'::jsonb,
    started_at          timestamptz,
    completed_at        timestamptz,
    created_at          timestamptz not null default now(),
    check (num_nonnulls(event_candidate_id, event_id, field_assertion_id, asset_id, project_id, entity_id) = 1),
    check (completed_at is null or started_at is null or completed_at >= started_at)
);

create table event_duplicate_candidates (
    duplicate_pair_id   uuid primary key default gen_random_uuid(),
    event_id_a          uuid not null references events(event_id),
    event_id_b          uuid not null references events(event_id),
    blocking_key        text,
    similarity_score    numeric(4,3) not null check (similarity_score between 0 and 1),
    match_features      jsonb not null default '{}'::jsonb,
    status              text not null default 'pending' check (status in (
                         'pending','confirmed_duplicate','not_duplicate'
                       )),
    reviewed_by         text,
    reviewed_at         timestamptz,
    check (event_id_a < event_id_b),
    unique (event_id_a, event_id_b)
);

create table event_merges (
    event_merge_id      uuid primary key default gen_random_uuid(),
    survivor_event_id   uuid not null references events(event_id),
    duplicate_event_id  uuid not null references events(event_id),
    reason              text not null,
    field_resolution    jsonb not null default '{}'::jsonb,
    merged_by           text not null,
    merged_at           timestamptz not null default now(),
    check (survivor_event_id <> duplicate_event_id),
    unique (duplicate_event_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. Queue and matching indexes
-- ─────────────────────────────────────────────────────────────────────────────

create index ix_search_rules_due
    on search_rules(is_active, cadence_minutes, valid_from);
create index ix_search_runs_status_created
    on search_runs(status, created_at desc);
create index ix_source_documents_url
    on source_documents(canonical_url);
create index ix_source_documents_hash
    on source_documents(content_sha256);
create index ix_source_documents_published
    on source_documents(published_at desc);
create index ix_source_document_runs_document
    on source_document_runs(source_document_id, search_run_id);
create index ix_event_candidates_status_created
    on event_candidates(status, created_at);
create index ix_candidate_assets_resolution
    on candidate_asset_mentions(resolution_status, event_candidate_id);
create index ix_candidate_projects_resolution
    on candidate_project_mentions(resolution_status, event_candidate_id);
create index ix_candidate_entities_resolution
    on candidate_entity_mentions(resolution_status, event_candidate_id);
create index ix_events_active_date
    on events(event_date_start desc)
    where lifecycle_status in ('approved','published');
create index ix_events_review_queue
    on events(review_status, updated_at)
    where lifecycle_status <> 'merged';
create index ix_event_categories_category
    on event_categories(category_id, event_id);
create index ix_event_assets_asset
    on event_assets(asset_id, event_id);
create index ix_event_projects_project
    on event_projects(project_id, event_id);
create index ix_event_entities_entity_role
    on event_entities(entity_id, role_code, event_id);
create index ix_evidence_document
    on evidence_items(source_document_id);
create index ix_assertions_event_field
    on field_assertions(event_id, field_code)
    where event_id is not null;
create index ix_assertions_pending_review
    on field_assertions(review_status, field_code)
    where review_status in ('unreviewed','in_review');
create index ix_assertions_verification
    on field_assertions(verification_status)
    where verification_status in ('pending','contradicted');
create index ix_candidate_payload_gin
    on event_candidates using gin(extracted_payload);
create index ix_duplicate_review_queue
    on event_duplicate_candidates(status, similarity_score desc)
    where status = 'pending';
create index ix_assets_name_trgm
    on assets using gin(canonical_name gin_trgm_ops);
create index ix_asset_aliases_trgm
    on asset_aliases using gin(normalized_alias gin_trgm_ops);
create index ix_projects_name_trgm
    on projects using gin(canonical_name gin_trgm_ops);
create index ix_entities_name_trgm
    on entities using gin(canonical_name gin_trgm_ops);
create index ix_entity_aliases_trgm
    on entity_aliases using gin(normalized_alias gin_trgm_ops);

commit;
