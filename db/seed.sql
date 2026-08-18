-- DEPRECATED V1: Do not use for new deployments.
-- Current authority: db/v2/seed.sql (SQLite 3).
-- Stage 1 seed data
begin;

insert into categories (code, name_ko) values
  ('SALE', '매각'),
  ('LEASE', '임대'),
  ('NEW_SUPPLY', '신규공급'),
  ('PERMIT', '인허가'),
  ('PF', 'PF'),
  ('LOAN', '대출'),
  ('INVESTMENT', '투자')
on conflict (code) do update set
  name_ko = excluded.name_ko,
  is_active = true;

insert into collection_sources
  (code, name_ko, base_url, source_kind, source_role, collection_policy, quality_tier, policy_notes)
values
  ('NAVER_NEWS', '네이버 뉴스 검색 API', 'https://developers.naver.com/docs/serviceapi/search/news/news.md', 'search_api', 'discovery', 'API_ALLOWED', 2, '앱 등록, 키, 호출한도와 원문 권리 분리'),
  ('GOOGLE_NEWS_RSS', 'Google News RSS 검색', 'https://news.google.com/rss/search', 'rss', 'discovery', 'RSS_ONLY', 1, '발견 채널로만 사용; 커버리지와 리다이렉트 변동 가능'),
  ('DART', 'OpenDART', 'https://opendart.fss.or.kr/', 'official_api', 'official_verification', 'API_ALLOWED', 3, '비상장 SPC와 사모계약 공백'),
  ('KIND', 'KRX KIND', 'https://kind.krx.co.kr/', 'official_site', 'official_verification', 'PUBLIC_LOW_RATE', 3, '상장사 공시 상태와 정정공시 확인'),
  ('DATA_GO_KR', '공공데이터포털', 'https://www.data.go.kr/', 'official_api', 'official_verification', 'API_ALLOWED', 3, '데이터셋별 서비스 승인, 쿼터, 이용허락 개별 확인'),
  ('VWORLD', 'VWorld', 'https://www.vworld.kr/', 'official_api', 'official_verification', 'API_ALLOWED', 3, '주소와 좌표는 식별 보조이며 단독 병합키가 아님'),
  ('MOLIT_RT', '국토부 실거래가', 'https://rt.molit.go.kr/', 'official_api', 'official_verification', 'API_ALLOWED', 4, '신고·정정 시차와 지분거래 누락 가능'),
  ('BUILDING_HUB', '건축HUB', 'https://www.data.go.kr/data/15134735/openapi.do', 'official_api', 'official_verification', 'API_ALLOWED', 4, '건축물대장과 인허가 서비스별 권한 확인'),
  ('REITS_MOLIT', '리츠정보시스템', 'https://reits.molit.go.kr/', 'official_site', 'official_verification', 'PUBLIC_LOW_RATE', 3, '영업·투자보고서 기준일 보존'),
  ('EUM', '토지이음', 'https://www.eum.go.kr/', 'official_site', 'official_verification', 'MANUAL_REVIEW', 3, '공개 API 우선, 업무화면 대량수집 금지'),
  ('ONBID', '온비드', 'https://www.onbid.co.kr/', 'official_site', 'official_verification', 'PUBLIC_LOW_RATE', 4, '공개 API와 이용조건 범위 내 수집'),
  ('COURT_AUCTION', '법원경매정보', 'https://www.courtauction.go.kr/', 'manual_system', 'manual_verification', 'MANUAL_REVIEW', 4, '자동화·로그인·CAPTCHA 우회 금지'),
  ('IROS', '인터넷등기소', 'https://www.iros.go.kr/', 'manual_system', 'manual_verification', 'MANUAL_REVIEW', 4, '채권최고액은 실제 원금이나 잔액이 아님'),
  ('R_ONE', '한국부동산원 R-ONE', 'https://www.reb.or.kr/r-one/', 'statistics', 'market_context', 'PUBLIC_LOW_RATE', 3, '개별 자산 이벤트 원천이 아닌 임대료·공실률 맥락'),
  ('ECOS', '한국은행 ECOS', 'https://ecos.bok.or.kr/api/', 'official_api', 'market_context', 'API_ALLOWED', 3, '개별 거래가 아닌 금리·거시 맥락')
on conflict (code) do update set
  name_ko = excluded.name_ko,
  base_url = excluded.base_url,
  source_kind = excluded.source_kind,
  source_role = excluded.source_role,
  collection_policy = excluded.collection_policy,
  quality_tier = excluded.quality_tier,
  policy_notes = excluded.policy_notes,
  is_active = true,
  updated_at = now();

insert into field_definitions (field_code, subject_type, data_type, description, is_multi_value) values
  ('event.transaction_price_krw', 'event', 'numeric', '부동산 거래가격. value_basis로 호가·입찰가·계약가·종결가 구분', false),
  ('event.expected_price_krw', 'event', 'numeric', '희망가·예상가', false),
  ('event.loan_commitment_krw', 'event', 'numeric', '대출 또는 PF 총 약정액', false),
  ('event.loan_executed_krw', 'event', 'numeric', '실제 실행액', false),
  ('event.loan_outstanding_krw', 'event', 'numeric', '기준일 현재 잔액', false),
  ('event.interest_rate_pct', 'event', 'numeric', '대출 금리', false),
  ('event.ltv_pct', 'event', 'numeric', 'LTV', false),
  ('event.ltc_pct', 'event', 'numeric', 'LTC', false),
  ('event.loan_maturity_date', 'event', 'date', '대출 만기일', false),
  ('event.lease_area_sqm', 'event', 'numeric', '계약 또는 임대대상 면적', false),
  ('event.monthly_rent_krw', 'event', 'numeric', '월 임대료', false),
  ('event.lease_deposit_krw', 'event', 'numeric', '임대보증금', false),
  ('event.lease_start_date', 'event', 'date', '임대차 개시일', false),
  ('event.lease_end_date', 'event', 'date', '임대차 만료일', false),
  ('event.expected_completion_date', 'event', 'date', '공식 또는 추정 준공예정일', false),
  ('event.actual_completion_date', 'event', 'date', '실제 준공일', false),
  ('event.opening_date', 'event', 'date', '영업·개관·입주개시일', false),
  ('event.permit_notice_number', 'event', 'text', '고시·공고·허가 문서번호', false),
  ('event.permit_effective_date', 'event', 'date', '인허가 법적 효력 발생일', false),
  ('event.permit_legal_effective', 'event', 'boolean', '법적 효력 확인 여부', false),
  ('asset.gross_floor_area_sqm', 'asset', 'numeric', '연면적', false),
  ('asset.land_area_sqm', 'asset', 'numeric', '대지면적', false),
  ('asset.leasable_area_sqm', 'asset', 'numeric', '임대가능면적', false),
  ('asset.building_mgmt_no', 'asset', 'text', '건축물대장 관리번호', false),
  ('asset.parcel_keys', 'asset', 'json', 'PNU 또는 필지 키 집합', true),
  ('project.total_project_cost_krw', 'project', 'numeric', '총사업비', false),
  ('project.parcel_keys', 'project', 'json', '프로젝트 필지 집합', true),
  ('entity.corporate_no', 'entity', 'text', '법인등록번호', false),
  ('entity.business_no', 'entity', 'text', '사업자등록번호', false),
  ('entity.dart_corp_code', 'entity', 'text', 'OpenDART 고유번호', false)
on conflict (field_code) do update set
  subject_type = excluded.subject_type,
  data_type = excluded.data_type,
  description = excluded.description,
  is_multi_value = excluded.is_multi_value;

commit;
