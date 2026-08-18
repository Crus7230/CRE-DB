-- Migration 2.2.0 -> 2.3.0: competitive sale process and bid funding model
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
BEGIN IMMEDIATE;
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



INSERT OR IGNORE INTO event_stages(stage_code,event_category_id,name_ko,stage_rank,is_terminal) VALUES
 ('SHORTLISTED','cat_sale','숏리스트 확정',45,0),
 ('MOU_SIGNED','cat_sale','양해각서 체결',63,0),
 ('DUE_DILIGENCE','cat_sale','실사·가격협상',66,0),
 ('SPA_SIGNED','cat_sale','SPA 체결',72,0),
 ('CONDITIONS_PENDING','cat_sale','선행조건 충족 대기',75,0),
 ('SALE_FAILED','cat_sale','거래 무산',95,1),
 ('REBID','cat_sale','재입찰',35,0);

INSERT OR IGNORE INTO predicate_definitions(predicate_code,name_ko,subject_scope,value_kind,default_unit_code,is_multivalued,description) VALUES
 ('BID_RANK','입찰순위','EVENT','NUMBER',NULL,1,'특정 입찰 라운드·평가시점의 보고 순위'),
 ('SALE_PROCESS_STATUS','매각절차 상태','EVENT','TEXT',NULL,1,'매각절차의 보고된 단계 또는 상태'),
 ('BID_CONDITIONS','입찰조건','EVENT','JSON',NULL,1,'가격 외 자금조달·실사·종결 조건'),
 ('FUNDING_STRUCTURE','인수자금 구조','EVENT','JSON',NULL,1,'펀드·SPC·LP·대주 등 입찰자금 구조'),
 ('DECISION_REASON','선정사유','EVENT','TEXT',NULL,1,'숏리스트·우협·차순위 선정의 가격·비가격 사유');

INSERT OR IGNORE INTO claim_role_definitions(role_code,name_ko,allowed_kind,description) VALUES
 ('SELL_SIDE_ADVISOR','매도측 자문사','ANY','매각주관·매도측 재무자문 주체'),
 ('BUY_SIDE_ADVISOR','매수측 자문사','ANY','입찰자 측 재무·투자 자문 주체'),
 ('LEGAL_ADVISOR','법률자문사','ANY','거래 법률자문 주체'),
 ('DEBT_ARRANGER','인수금융 주선사','ANY','인수금융 구조화·주선 주체'),
 ('BIDDER','입찰자','ANY','특정 라운드의 입찰 참여 주체'),
 ('CONSORTIUM_MEMBER','컨소시엄 구성원','ANY','공동 입찰 컨소시엄 참여자'),
 ('MANAGED_FUND','운용 펀드·리츠','ANY','운용사가 입찰에 사용하는 펀드·리츠'),
 ('ACQUISITION_VEHICLE','매수기구·SPC','ANY','인수 명의 및 자금 수취 기구'),
 ('EQUITY_PROVIDER','지분자금 제공자','ANY','LP·공동투자자 등 equity 제공 주체'),
 ('DEBT_PROVIDER','인수금융 제공자','ANY','담보·인수금융 대주 또는 대주단'),
 ('BID_ROUND','입찰 라운드','ANY','예비·본입찰·재입찰 등 평가 라운드'),
 ('BID_RANK','입찰 순위','ANY','해당 라운드·시점에 보도된 순위'),
 ('SHORTLISTED_PARTY','숏리스트 후보','ANY','적격인수후보 또는 숏리스트 포함 주체'),
 ('PREFERRED_BIDDER','우선협상대상자','ANY','현재 또는 과거 우선협상대상자'),
 ('RESERVE_BIDDER','차순위협상대상자','ANY','차순위 또는 예비 협상대상자'),
 ('FUNDING_SOURCE','자금조달 출처','ANY','입찰 또는 인수를 뒷받침하는 자금원');

UPDATE schema_meta SET schema_value='2.3.0',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE schema_key='schema_version';
INSERT INTO schema_meta(schema_key,schema_value) VALUES ('sale_process_model_version','1.0.0')
 ON CONFLICT(schema_key) DO UPDATE SET schema_value=excluded.schema_value,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now');
UPDATE schema_meta SET schema_value='2.3.0',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE schema_key='seed_version';

COMMIT;
