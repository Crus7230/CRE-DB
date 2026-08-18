BEGIN IMMEDIATE;

-- V2.5 institutional LP mandate extension. Generated from schema.sql section 12.
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


INSERT OR IGNORE INTO predicate_definitions(
 predicate_code,name_ko,subject_scope,value_kind,default_unit_code,is_multivalued,description
) VALUES
 ('LP_MANDATE_PROGRAM_AMOUNT','LP 위탁 프로그램 규모','EVENT','MONEY','KRW',1,'위탁운용 프로그램 전체 공고 규모'),
 ('LP_MANDATE_COMMITMENT_AMOUNT','LP 위탁 출자·배정액','EVENT','MONEY','KRW',1,'LP가 트랙·선정 운용사에 배정 또는 약정한 금액'),
 ('LP_MANDATE_TARGET_FUND_SIZE','위탁 펀드 목표규모','EVENT','MONEY','KRW',1,'LP 출자액과 구분되는 목표 펀드 결성 규모'),
 ('LP_MANDATE_TARGET_RETURN','위탁 투자 요구수익률','EVENT','PERCENT','PERCENT',1,'위탁운용 가이드라인의 목표·최소 수익률'),
 ('LP_MANDATE_GUIDELINE','위탁 투자 가이드라인','EVENT','TEXT',NULL,1,'전략·섹터·지역·기간·레버리지 등 투자지침'),
 ('LP_MANDATE_MANAGER_SELECTED','위탁운용사 선정','EVENT','ORGANIZATION_REF',NULL,1,'공개 절차에서 선정된 운용사');

INSERT OR IGNORE INTO event_stages(stage_code,event_category_id,name_ko,stage_rank,is_terminal) VALUES
 ('MANAGER_RFP_OPEN','cat_invest','위탁운용사 모집',12,0),
 ('MANAGER_SELECTED','cat_invest','위탁운용사 선정',15,0);

UPDATE schema_meta SET schema_value='2.5.0' WHERE schema_key='schema_version';

COMMIT;
