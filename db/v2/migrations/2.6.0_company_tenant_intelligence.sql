BEGIN IMMEDIATE;

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

INSERT OR IGNORE INTO event_categories(event_category_id,code,name_ko,parent_id,is_active)
VALUES('cat_corporate_relocation','CORPORATE_RELOCATION','기업 이전',NULL,1);

INSERT OR IGNORE INTO event_stages(stage_code,event_category_id,name_ko,stage_rank,is_terminal) VALUES
 ('RELOCATION_REPORTED','cat_corporate_relocation','이전 보도·검토',10,0),
 ('RELOCATION_ANNOUNCED','cat_corporate_relocation','이전 계획 발표',20,0),
 ('RELOCATION_SITE_SELECTED','cat_corporate_relocation','이전지 선정',30,0),
 ('RELOCATION_CONTRACTED','cat_corporate_relocation','이전 계약',40,0),
 ('RELOCATION_COMPLETED','cat_corporate_relocation','이전 완료',50,1),
 ('RELOCATION_CANCELLED','cat_corporate_relocation','이전 취소',60,1);

INSERT OR IGNORE INTO predicate_definitions(predicate_code,name_ko,subject_scope,value_kind,default_unit_code,is_multivalued,description) VALUES
 ('BUSINESS_DOMAIN','사업영역','ORGANIZATION','TEXT',NULL,1,'시점별 주요 사업영역과 활동 설명'),
 ('INVESTMENT_PLAN_AMOUNT','투자계획 금액','EVENT','MONEY','KRW',1,'공식 또는 보도된 계획 단계 투자·CAPEX 금액'),
 ('INVESTMENT_PLAN_DESCRIPTION','투자계획 설명','EVENT','TEXT',NULL,1,'시설·인력·CAPEX 등 투자계획 원문'),
 ('HEADCOUNT_PLAN','인력 증감 계획','EVENT','COUNT','COUNT',1,'채용·감원·시설 인원 계획'),
 ('RELOCATION_ORIGIN','이전 출발지','EVENT','REGION_REF',NULL,1,'기업 이전 전 지역·자산'),
 ('RELOCATION_DESTINATION','이전 목적지','EVENT','REGION_REF',NULL,1,'기업 이전 후 지역·자산'),
 ('EXPECTED_MOVE_IN_DATE','입주 예정일','EVENT','DATE',NULL,1,'기사·공시·계약상 예상 입주시점'),
 ('LP_MANDATE_REPORTED_MANAGER_ALLOCATION','보도된 선정사 배정금액','EVENT','MONEY','KRW',1,'공식 결과 미확인 상태에서 기사·리서치가 선정사별로 보도한 배정금액');

DROP VIEW IF EXISTS v_lp_manager_best_available;
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

UPDATE schema_meta SET schema_value='2.6.0' WHERE schema_key='schema_version';
COMMIT;
