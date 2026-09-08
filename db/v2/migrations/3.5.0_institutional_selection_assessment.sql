-- PostgreSQL V3.5.0 additive contract for reviewable manager-selection inference.
-- This does not promote an inference into lp_mandate_selections.
-- Apply only after 3.5.0_model_interpretations.sql has advanced schema_meta to 3.5.0.
BEGIN;
DO $$ DECLARE current_version TEXT; BEGIN
  SELECT schema_value INTO current_version FROM market_intelligence.schema_meta WHERE schema_key='schema_version';
  IF current_version IS DISTINCT FROM '3.5.0' THEN RAISE EXCEPTION 'Expected schema 3.5.0, found %',COALESCE(current_version,'missing'); END IF;
END $$;

INSERT INTO market_intelligence.predicate_definitions(
  predicate_code,name_ko,subject_scope,value_kind,default_unit_code,is_multivalued,description
) VALUES
 ('LP_MANDATE_MANAGER_BID_PARTICIPANT','기관자금 입찰 참여 운용사','EVENT','ORGANIZATION_REF',NULL,1,'동일 LP mandate 자금으로 입찰·shortlist에 참여한 운용사. 선정 확정이 아님'),
 ('LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT','집행 근거 기반 위탁운용사 유추','EVENT','ORGANIZATION_REF',NULL,1,'동일 LP·track·vehicle·deal의 약정 또는 집행 근거로 유추한 운용사. 공식 선정과 별도')
ON CONFLICT(predicate_code) DO NOTHING;

INSERT INTO market_intelligence.claim_role_definitions(role_code,name_ko,allowed_kind,description) VALUES
 ('MANDATE_CODE','위탁 프로그램 코드','TEXT','후속 claim이 연결되는 canonical mandate code'),
 ('FOLLOW_UP_ACTION','후속 입찰·집행 행위','TEXT','APPLIED·SHORTLISTED·COMMITTED·EXECUTED 등 후속 행위'),
 ('FUNDING_BASIS','기관자금 연결 기준','TEXT','LP_SOURCE_DEPLOYMENT 등 후속 행위에 사용된 자금의 출처 기준'),
 ('LINKED_VEHICLE','연결 펀드·vehicle','ANY','기관자금과 입찰·집행을 연결하는 펀드·리츠·SPC'),
 ('LINKED_DEAL','연결 거래·자산','ANY','기관자금이 입찰 또는 집행된 거래·자산·프로젝트'),
 ('CONTRADICTION_NOTE','상충 근거','TEXT','다른 mandate·vintage·운용사 가능성 등 판정을 보류시키는 근거'),
 ('INFERENCE_RULE_VERSION','추론 규칙 버전','TEXT','선정 유추를 산출한 결정론적 규칙 버전')
ON CONFLICT(role_code) DO NOTHING;

CREATE INDEX IF NOT EXISTS ix_claims_lp_manager_assessment
ON market_intelligence.claims(predicate_code,review_status,verification_status)
WHERE predicate_code IN ('LP_MANDATE_MANAGER_BID_PARTICIPANT','LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT');

CREATE INDEX IF NOT EXISTS ix_claim_arguments_mandate_assessment
ON market_intelligence.claim_arguments(role_code,text_value,claim_id)
WHERE role_code IN ('MANDATE_CODE','MANDATE_TRACK','FOLLOW_UP_ACTION','FUNDING_BASIS');

COMMIT;
