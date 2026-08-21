-- PostgreSQL V3.3.0: governed, hierarchical, evidence-aware record classification.
DO $$
DECLARE current_version TEXT;
BEGIN
  SELECT schema_value INTO current_version FROM market_intelligence.schema_meta WHERE schema_key='schema_version';
  IF current_version IS DISTINCT FROM '3.2.0' THEN
    RAISE EXCEPTION 'Expected schema 3.2.0, found %', COALESCE(current_version,'missing');
  END IF;
END $$;

CREATE TABLE market_intelligence.classification_schemes (
    classification_scheme_id TEXT PRIMARY KEY,
    scheme_code TEXT NOT NULL UNIQUE,
    scheme_name_ko TEXT NOT NULL,
    scheme_name_en TEXT,
    description TEXT,
    cardinality_code TEXT NOT NULL CHECK(cardinality_code IN ('SINGLE','MULTIPLE')),
    is_hierarchical BIGINT NOT NULL DEFAULT 0 CHECK(is_hierarchical IN (0,1)),
    target_kinds_json TEXT NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(target_kinds_json::jsonb)='array'),
    vocabulary_version TEXT NOT NULL,
    governance_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(governance_status IN ('DRAFT','ACTIVE','DEPRECATED')),
    valid_from TEXT,
    valid_to TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata_json::jsonb)='object'),
    created_at TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to>=valid_from)
);

CREATE TABLE market_intelligence.classification_terms (
    classification_term_id TEXT PRIMARY KEY,
    classification_scheme_id TEXT NOT NULL REFERENCES market_intelligence.classification_schemes(classification_scheme_id) ON DELETE RESTRICT,
    term_code TEXT NOT NULL,
    term_name_ko TEXT NOT NULL,
    term_name_en TEXT,
    parent_term_id TEXT,
    description TEXT,
    synonyms_json TEXT NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(synonyms_json::jsonb)='array'),
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_assignable BIGINT NOT NULL DEFAULT 1 CHECK(is_assignable IN (0,1)),
    governance_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(governance_status IN ('DRAFT','ACTIVE','DEPRECATED')),
    valid_from TEXT,
    valid_to TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata_json::jsonb)='object'),
    created_at TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    UNIQUE(classification_scheme_id,term_code),
    UNIQUE(classification_scheme_id,classification_term_id),
    FOREIGN KEY(classification_scheme_id,parent_term_id)
      REFERENCES market_intelligence.classification_terms(classification_scheme_id,classification_term_id) ON DELETE RESTRICT,
    CHECK(parent_term_id IS NULL OR parent_term_id<>classification_term_id),
    CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to>=valid_from)
);

CREATE TABLE market_intelligence.record_classifications (
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
    is_primary BIGINT NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
    confidence DOUBLE PRECISION CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    classifier_version TEXT NOT NULL,
    evidence_status TEXT NOT NULL CHECK(evidence_status IN (
      'DIRECT_OFFICIAL','DERIVED_OFFICIAL','DIRECT_STRUCTURED','MEDIA_DIRECT',
      'MANUAL_REVIEWED','INFERRED','UNVERIFIED'
    )),
    source_claim_id TEXT,
    source_document_version_id TEXT,
    evidence_locator TEXT,
    derived_from_assignment_id TEXT REFERENCES market_intelligence.record_classifications(record_classification_id) ON DELETE RESTRICT,
    review_status TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK(review_status IN (
      'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
    )),
    valid_from TEXT,
    valid_to TEXT,
    assigned_at TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    reviewed_at TEXT,
    lineage_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(lineage_json::jsonb)='object'),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata_json::jsonb)='object'),
    FOREIGN KEY(classification_scheme_id,classification_term_id)
      REFERENCES market_intelligence.classification_terms(classification_scheme_id,classification_term_id) ON DELETE RESTRICT,
    UNIQUE(target_kind,target_id,classification_scheme_id,classification_term_id,assignment_role,classifier_version),
    CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to>=valid_from),
    CHECK(derived_from_assignment_id IS NULL OR assignment_role IN ('DERIVED','RELATED'))
);

CREATE INDEX ix_classification_terms_parent
ON market_intelligence.classification_terms(classification_scheme_id,parent_term_id,sort_order);
CREATE INDEX ix_record_classifications_target
ON market_intelligence.record_classifications(target_kind,target_id,review_status);
CREATE INDEX ix_record_classifications_term_target
ON market_intelligence.record_classifications(classification_scheme_id,classification_term_id,target_kind);
CREATE INDEX ix_record_classifications_classifier
ON market_intelligence.record_classifications(classifier_version,assignment_role,review_status);
CREATE INDEX ix_record_classifications_evidence
ON market_intelligence.record_classifications(source_document_version_id,source_claim_id);
CREATE UNIQUE INDEX ux_record_classifications_primary_current
ON market_intelligence.record_classifications(target_kind,target_id,classification_scheme_id)
WHERE is_primary=1 AND valid_to IS NULL AND review_status IN ('UNREVIEWED','PENDING','APPROVED');

INSERT INTO market_intelligence.classification_schemes(
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

INSERT INTO market_intelligence.classification_terms(
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

CREATE VIEW market_intelligence.v_record_classification_summary AS
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
FROM market_intelligence.record_classifications r
JOIN market_intelligence.classification_schemes s ON s.classification_scheme_id=r.classification_scheme_id
JOIN market_intelligence.classification_terms t ON t.classification_scheme_id=r.classification_scheme_id
                           AND t.classification_term_id=r.classification_term_id
WHERE r.review_status NOT IN ('REJECTED','SUPERSEDED')
  AND (r.valid_from IS NULL OR r.valid_from<=to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
  AND (r.valid_to IS NULL OR r.valid_to>to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
GROUP BY r.target_kind,r.target_id;

UPDATE market_intelligence.schema_meta SET schema_value = '3.3.0'
WHERE schema_key='schema_version' AND schema_value='3.2.0';
