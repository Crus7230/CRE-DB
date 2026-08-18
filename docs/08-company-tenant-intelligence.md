# 기업·임차·이전·시총 Universe Intelligence

## 목표

시점별 주요 기업 universe와 기업의 사업·투자·부동산 사용 변화를 같은 시간축에 연결한다.

```text
KRX 시점별 시총 snapshot
→ 전체 상위 50 / 업종별 상위 10 / 당시 부각 산업군
→ 기업 identity·산업분류·사업활동
→ 임차·이전·시설투자 기사 및 공시
→ lease/relocation/investment event
→ 자산·프로젝트·지역·occupancy
→ 같은 시점 매각·임대·공급·개발·금융 흐름 비교
```

## 권위와 유력정보

- 공시·회사 공식자료·계약 당사자 원문이 claim을 직접 확인하면 `VERIFIED`.
- 공식 결과가 없더라도 full-text 기사에 회사·장소·날짜·면적·금액 등이 구체적이고 반증이 없으면 `LIKELY_REPORTED_PENDING_PRIMARY`.
- 독립 source family 둘 이상이 구체 내용을 일치 보도하면 `HIGHLY_LIKELY_REPORTED_PENDING_PRIMARY`.
- 같은 보도자료·기사의 전재는 `document_families`로 묶어 독립 근거 하나로 센다.
- 공시 부재는 임차·이전 기사의 반증이 아니다. 공시대상성·중요성·회사 공식 발표 여부를 별도 기록한다.
- likely claim은 조회에 표시하지만 canonical event stage·약정·잔액·집행을 변경하지 않는다.

## V2.6 관계형 구조

### 시점별 산업과 universe

- `industry_taxonomies`: KRX·KSIC 등 분류체계와 source version
- `industry_nodes`: 계층형 산업 node
- `organization_industry_assignments`: 기업–산업 배치의 `valid_from/valid_to`
- `market_universe_snapshots`: snapshot 날짜·시장·선정방식·방법론·원천 버전
- `market_universe_members`: 기업별 시총·전체순위·업종순위·포함사유

현재 시총을 과거 사건에 소급하지 않는다. 사건 비교에는 사건일 이전의 가장 가까운 완료 snapshot을 사용한다.

### 기업 내용과 부동산 점유

- `organization_business_activities`: 시점별 사업영역·주력/신규/중단 활동
- `organization_property_occupancies`: 본사·오피스·R&D·물류·데이터센터·생산시설의 tenant/owner/operator 상태
- `events` + `event_participants`: 임대·이전·투자 사건과 기업 역할
- `event_assets`, `event_projects`: 건물·개발사업 연결
- `claims`, `claim_evidence`: 공시·기사 exact span 및 검증상태

### 기업이전 stage

```text
RELOCATION_REPORTED
→ RELOCATION_ANNOUNCED
→ RELOCATION_SITE_SELECTED
→ RELOCATION_CONTRACTED
→ RELOCATION_COMPLETED
또는 RELOCATION_CANCELLED
```

### 주요 predicate

- `BUSINESS_DOMAIN`
- `INVESTMENT_PLAN_AMOUNT`
- `INVESTMENT_PLAN_DESCRIPTION`
- `HEADCOUNT_PLAN`
- `RELOCATION_ORIGIN`
- `RELOCATION_DESTINATION`
- `EXPECTED_MOVE_IN_DATE`
- 기존 `LEASED_AREA`, `RENT_AMOUNT`, `DEPOSIT_AMOUNT`

## 조회 view

- `v_company_universe_current`: market·universe별 최신 완료 snapshot
- `v_company_real_estate_timeline`: 회사의 lease·relocation·investment 사건
- `v_company_event_universe_context`: 사건일 직전 universe membership과 시총·순위
- `v_lp_manager_best_available`: 공식 선정사와 유력 보도 선정사를 상태 구분해 통합 표시

## 수집 주기

- KRX universe: 월말 마지막 거래일
- OpenDART 공시: 일간
- 회사 IR·보도자료: 주간
- 임차·이전 기사: 일간 또는 source limit에 따른 주간
- 사업영역: 분기·반기·사업보고서
- 검증대기 queue: 월간 재확인

## 기사–공시 비교 창

기사 최초 게시일을 기준으로:

- 이전 90일
- 이후 180일

OpenDART 주요사항보고서, 사업·분기·반기보고서, 거래소 공시, 회사 IR·공식 발표를 비교한다. 이후 공식자료가 확인되면 기사 claim을 삭제하지 않고 verified claim과 승격 관계를 남긴다.

## 운영상 미구현 항목

V2.6 schema와 campaign 계약은 구현됐지만 실제 KRX snapshot collector와 임차·이전 기사 collector는 아직 연결되지 않았다. 따라서 신규 universe·occupancy 테이블이 0건인 상태는 적재 실패가 아니라 collector 시작 전 baseline이다. 실제 수집 전 KRX 사용조건·필드정의·산업분류 version을 공식 원천으로 확정해야 한다.
