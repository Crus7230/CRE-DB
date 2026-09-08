# CRE DB Board Principle

> 대한민국 상업용 부동산 시장 인텔리전스의 탐색·수집·정규화·검증·서비스 운영 원칙

- **현재 운영 갱신:** 2026-09-08 KST (이하 상세 실행 수치는 각 절의 원래 기준일을 따름)
- **관리 위치:** `09. CRE DB Board`
- **원 개발 lineage:** `C:\10137_WorkSpace\real-estate-market-intelligence`
- **원격 source lineage:** `https://github.com/Crus7230/CRE-DB`
- **온라인 서비스:** `https://cre-db.vercel.app`
- **권위 DB:** `data/market.db` — 전체 이력·원문·비활성 자료를 보존하는 read-only local full archive
- **Online serving:** Turso/libSQL — local archive에서 가공한 compact serving. Supabase는 이전 운영 이력이며 신규 수집·게시 대상이 아님.
- **현재 schema:** global V3.5.0 + 기능별 schema version
- **문서의 지위:** 이 폴더에서 수행한 시장탐색, 데이터 적재, 관계정규화, dashboard, 기사 요약, 검증과 운영의 통합 원칙

### 2026-09-08 개편과 현재 제한

현재 수정 방향은 [대시보드 개편 계획](docs/12-dashboard-redesign-plan-20260908.md)을 따른다. 원본은 `data/market.db`, 기존 온라인용 가공본은 `data/market-serving-v2.candidate.db`다. 원천·버전·후보·정규 사건 lineage를 보존하면서 화면용 projection을 별도로 생성한다.

Turso 무료 읽기 한도 소진으로 현재 원격 조회가 BLOCKED다. 사용자는 무료 유지와 추후 다른 DB 검토를 선택했다. 로컬 수집/가공 완료와 원격 게시 완료는 별도 상태로 기록하고, 제한이 해제되기 전 원격 성공을 주장하거나 반복 조회하지 않는다. 화면 자동분류는 탐색 보조이며 사람의 검토나 사건 확정으로 표현하지 않는다.

### 증거상태 표기

- **운영계약:** 문서·규칙에 정의된 목표와 금지사항
- **현재구현:** 실행 가능한 code path가 존재함
- **실행확인:** campaign artifact, DB row, test 또는 live QA로 실제 수행이 확인됨
- **작업중:** 전달본에는 있으나 원 source Git commit에 아직 포함되지 않은 변경
- **계획:** schema·campaign·문서만 있고 운영 collector 또는 검증완료가 없는 영역

문서상의 설계가 실행 사실을 대신하지 않는다. schema가 존재하거나 command가 exit 0이라는 사실만으로 coverage·관계정합화·승인을 완료했다고 표현하지 않는다.

---

## 1. 목적

CRE DB Board는 이미 알고 있는 자산목록을 갱신하는 자산별 조사 시스템이 아니다. **매각·임대·신규공급·인허가·PF·대출·투자라는 시장행위 카테고리별 검색**에서 새로운 문서와 사건을 발견하고, 문서→주장→후보→자산·프로젝트·조직→검증된 사건으로 연결하는 시장 인텔리전스 시스템이다.

최종 목적은 다음 네 가지다.

1. 여러 출처에서 시장사건을 빠르게 발견한다.
2. 기사·공시·API record를 사실 자체가 아닌 근거문서로 보존한다.
3. 날짜·금액·면적·당사자·상태의 상충을 삭제하지 않고 assertion과 lineage로 관리한다.
4. dashboard에서 raw field 나열이 아닌 사건의 의미·관계·근거·검증수준을 읽을 수 있게 한다.

---

## 2. 절대 원칙

1. **Category-first:** 자산명보다 행위 카테고리와 단계변화 keyword가 탐색의 출발점이다.
2. **Source-faithful:** 기사·공시·고시는 사건을 주장하는 문서이지 자동 확정 사실이 아니다.
3. **Append-only lineage:** 정정·후속·취소는 이전 값을 덮어쓰지 않고 새 version 또는 assertion으로 연결한다.
4. **Fact/claim/review 분리:** confidence, 공식 verification, 사람 review는 서로 다른 축이다.
5. **다대다 관계:** 한 문서가 여러 사건을, 한 사건이 여러 자산·프로젝트·조직을, 한 자산이 시간에 따라 여러 사건을 가질 수 있다.
6. **비파괴 중복처리:** duplicate 후보와 약한 근거를 hard delete하지 않는다.
7. **날짜 의미 분리:** 발행일, 사건일, 계약일, 거래일, 공시일, 수집일, 요약생성일을 섞지 않는다.
8. **금액 basis 보존:** 총사업비, 프로그램 총액, track 금액, manager 배정액, fund size, 실제 납입액을 같은 금액으로 취급하지 않는다.
9. **권리·약관 준수:** 로그인, CAPTCHA, 유료벽, 비공개 endpoint를 우회하지 않는다.
10. **원문 최소보존:** 권리근거가 없는 기사 전문은 영구 저장하지 않고 제목·URL·출처·시각·hash·제한 발췌·요약을 보존한다.
11. **Main/Sub 단방향:** Supabase가 main이고 SQLite는 read-only sub다. SQLite 수정값을 자동으로 main에 승격하지 않는다.
12. **실패와 0건 분리:** 검색실패, API 무응답, parser 불일치, 공식 source 미언급, 정상 0건을 각각 구분한다.
13. **추정 금지:** 확인되지 않은 날짜·금액·면적·당사자·자산 식별정보는 임의로 채우지 않는다.
14. **완료는 검증까지:** command exit 0이나 문서 수집만으로 campaign을 완료 처리하지 않는다.
15. **공시 domain gate:** OpenDART 공시는 제목 유형만으로 시장근거에 승격하지 않는다. 거래대상 field의 자산구분·자산명·양수도 주요내용을 version-bound classifier로 판정한다.
16. **공시 노출·보존 분리:** `CRE_CONFIRMED`만 기본 검색에 노출하고 parse 실패·혼합·영업양수도는 검토함에 보존한다. 명시적 비부동산과 주거 중심 공시만 scope 밖으로 제거한다.

---

## 3. 작업 과정과 시스템 발전

### Phase 1 — System contract와 taxonomy

- 7개 핵심 카테고리와 단계 taxonomy 수립
- 문서, document version, mention, claim/assertion, event candidate, canonical event 분리
- source policy, review gate, 중복·병합·verification 등급 정의
- 근거: `docs/01-system-contract.md`, `rules/category-rules.json`

### Phase 2 — SQLite V2 데이터모델

- 자산, 프로젝트, 조직, 문서, 주장, 사건, 참여자, 검수, 검색실행 ledger 구축
- 이벤트를 자연키 하나로 강제하지 않고 다대다 bridge로 연결
- FTS, trigger, FK, CHECK, review/approval 구조 구성
- schema는 V2.2~V2.7 동안 매각절차, 기관자금, 회사, 임차·이전, 관계 gap으로 확장

### Phase 3 — 기간별 backfill

- 2025 연간 7개 카테고리 Google News RSS 탐색
- 2026년 1~6월 H1, 2026년 7월 연속 campaign
- 2020~2024 및 2025 경쟁입찰 매각절차 별도 탐색
- 2020~2025와 pre-2020 기관 LP→운용사 선정 이력 탐색
- OpenDART 공시 및 국토부 상업업무용 실거래 API 적재

### Phase 4 — 관계정규화와 검증

- 자산·프로젝트·조직 mention을 canonical master와 후행 연결
- alias, 식별번호, 주소, 시점별 조직·기업 분류를 분리
- 상충 assertion, document family, supersession, relation gap 보존
- approved manifest와 candidate manifest를 분리

### Phase 5 — Supabase main 전환

- 로컬 SQLite 단일 writer 구조에서 Supabase PostgreSQL `market_intelligence` main으로 이관
- base table, row count, PK/UNIQUE/CHECK/FK, view, trigger, 검색 view 검증
- SQLite는 Supabase→SQLite 전체 snapshot으로 재생성하는 read-only sub로 전환
- runbook: `docs/09-supabase-main-sqlite-sub-runbook.md`

### Phase 6 — Category-first dashboard

- Next.js dashboard와 server-only PostgreSQL adapter 구현
- 상단 navigation은 전역 업무 화면(시장 탐색·뉴스 모니터·기업·임차·기관자금·매각 파이프라인) 전환만 담당한다.
- 좌측 navigation은 현재 `시장 탐색` 업무 안의 조회 대상(시장 변화·관련 자산·근거자료)과 세부 분류만 담당하며 상단 taxonomy를 반복하지 않는다.
- 근거자료는 DB 원천 코드 나열이 아니라 거래·가격, 기업·사업, 시장동향, 절차·공고의 네 가지 활용 목적을 우선 노출하고 원천 type은 server-side mapping으로 보존한다.
- 통합검색, 카테고리, DB 색인, 오늘의 시장기사, 회사, 기관자금, 매각절차 workspace 구현
- 문서, 실거래, 이벤트, 자산, 회사 등 유형별 detail projection 구현
- desktop/mobile QA와 사전 등록 이메일 인증 적용

### Phase 7 — Daily article와 content enrichment

- RSS를 Supabase main에 직접 쓰는 daily collector 구현
- Google News URL을 publisher URL로 복원한 뒤 공개 본문만 일시 추출
- `content-extractive-v1`으로 본문 기반 extractive summary와 bounded safe excerpt 생성
- V2.8 `document_enrichments`를 document version에 귀속
- 기사 전문은 저장하지 않고 요약·제한 발췌·원문 URL·hash·parser/pipeline provenance만 저장
- 추출 실패 시 제목을 요약으로 위장하지 않고 `요약 없음`으로 표시

### Phase 8 — 배포와 운영

- GitHub source lineage와 CI 구성
- Vercel production 배포와 이메일 allowlist/HMAC session 보호
- Hermes local scheduler로 daily RSS 수집 후 enrichment 연결
- local production과 live API를 desktop/mobile에서 검증

### Git 기준 구현 시점

| 일시(KST) | 주요 이력 |
|---|---|
| 2026-08-18 | CRE market intelligence workspace 최초 source commit |
| 2026-08-19 오전 | CI runtime, 인증 proxy, HTTPS cookie 범위 보정 |
| 2026-08-19 오전 | daily market article workspace와 collector 배포 |
| 2026-08-19 | V2.8 content enrichment, 유형별 structured narrative, 최신 SQLite snapshot 구성 |

Git 최초 commit 이전의 조사·schema·backfill 과정은 `docs/`, `campaigns/`, `artifacts/`, `reports/`에 보존한다.

---

## 4. 시장 탐색범위

### 4.1 국가와 지역

- 기본 국가: 대한민국
- 전국 query와 17개 시도 bundle을 교차 실행
- 지역: 서울, 부산, 대구, 인천, 광주, 대전, 울산, 세종, 경기, 강원, 충북, 충남, 전북, 전남, 경북, 경남, 제주
- 필요 시 주요 시군구와 권역을 월·자산유형·keyword bundle로 세분화

### 4.2 포함 자산유형

- 오피스·업무시설·빌딩·사옥
- 리테일·상가·쇼핑몰·판매시설
- 물류센터·창고·풀필먼트·저온창고
- 데이터센터·IDC·AI 데이터센터
- 호텔·리조트·관광숙박
- 지식산업센터
- 헬스케어·시니어
- 복합용도 시설
- 상업개발부지·토지
- 골프장·주유소 및 기타 대체자산

### 4.3 제외·조건부 포함

**기본 제외**

- 순수 주거 매매
- 주거 임대차
- 개인 주택담보·전세·신용대출
- 상장주식만의 투자
- 자산운용사 법인 M&A만 다루는 문서
- 구체 자산·프로젝트·당사자 없는 시장 일반론
- 해외자산만의 사건

**조건부 포함**

- 상업시설이 명확한 mixed-use
- 상업용 또는 PF 맥락이 명확한 주거복합 개발
- 정책·통계 자료는 개별 event가 아닌 context document

---

## 5. 카테고리와 keyword 체계

Keyword는 `자산어 × 행위어 × 단계어 × 지역어 × 기간 partition`으로 조합한다. 아래는 대표군이며 실제 권위 목록은 `rules/category-rules.json`이다.

### SALE — 매각

- 탐색어: 매각 검토, 매각 추진, 매물, 매각주관사, 티저레터, IM 배포, 예비입찰, 본입찰, shortlist, 우선협상대상자, 우협, MOU, 실사, SPA, 매매계약, 거래종결, 잔금, 소유권이전, 공매, 경매, 유찰, 재공매, 유형자산 양도
- 단계: rumor→considering→advisor selected→marketing→bid→preferred bidder→due diligence→MOU→contract→closed/failed/withdrawn
- 구분: 희망가·입찰가·계약가·closing price, 자산양수도·수익증권·기업 M&A

### LEASE — 임대·임차·이전

- 탐색어: 임대개시, 임차인모집, 임대공고, 공실, 선임대, 프리리스, 마스터리스, 임대차계약, 신규임차, 입주확정, 본사이전, 입점확정, 재계약, 증평, 감평, 퇴거
- 단계: planned→marketed→negotiating/LOI→signed→fit-out→occupied→renewed/expanded/contracted→terminated/moved out
- 구분: 건물 연면적과 실제 임차면적, 이전 검토와 계약, 시장 공실률과 개별 임대사건

### NEW_SUPPLY — 신규공급

- 탐색어: 개발계획, 신축, 재개발, 복합개발, 착공, 공사개시, 상량, 준공, 완공, 사용승인, 개장, 개관, 영업개시, 입주개시
- 단계: concept→confirmed→pre-construction→construction→topped out→completed→use approved→opened→stabilized
- 구분: 예정과 실제, 착공식과 실착공, 사용승인·준공·개관일

### PERMIT — 인허가

- 탐색어: 건축허가, 건축신고, 착공신고, 사용승인, 용도변경, 증축, 도시관리계획, 지구단위계획, 개발행위허가, 사업시행인가, 실시계획인가, 건축위원회, 환경영향평가, 조건부승인, 재심의, 보류, 부결, 변경고시, 취소, 실효
- 단계: application→review/consultation→committee→supplement→conditional approval→approval→official notice→effective/amended/revoked
- 구분: 주민열람·위원회의견과 법적 승인, 계획과 실제 접수

### PF — 프로젝트금융

- 탐색어: 부동산 PF, 프로젝트파이낸싱, 브릿지론, 본PF, 대주단, 금융주선, 본PF 전환, 만기연장, 차환, refinancing, restructuring, 기한이익상실, EOD, 연체, 부실, 책임준공, 자금보충, 채무인수
- 단계: site assembly→bridge→permit→contractor→main PF marketing/commitment/execution→construction→repayment 또는 extension/restructuring/EOD/workout
- 구분: 모집·약정·실행, 전체 보증잔액과 개별 사업장 금액

### LOAN — 대출

- 탐색어: 담보대출, 선순위·중순위·후순위, 인수금융, 대출약정, 대출실행, refinancing, 차환, 만기연장, syndication, sell-down, 채권매각, 연체, EOD, 담보권실행
- 단계: sounding→arranger→term sheet→credit approval→commitment→execution→servicing→repayment/refinancing/default
- 구분: commitment·executed·outstanding, 채권최고액과 실제 원금

### INVESTMENT — 투자·기관자금

- 탐색어: 자산편입, 취득, 양수, 현물출자, 부동산펀드, 블라인드펀드, 프로젝트펀드, 출자, 약정, 공동투자, 수익증권, 지분투자, JV, closing
- 기관어: 연기금, 공제회, 보험사, 은행, 금융지주, 기관투자자
- 단계: sourcing→due diligence→IC→commitment→first/final close→execution→asset acquisition→exit
- 구분: LP mandate, manager selection, vehicle/fund, 실제 deployment

---

## 6. 시간범위와 campaign 구분

| 영역 | 시간범위 | partition/의미 |
|---|---|---|
| 일반 7개 카테고리 backfill | 2025-01-01~2025-12-31 | 문서 발행일 기준 월 partition |
| H1 연속 조사 | 2026-01-01~2026-06-30 | 월 partition, 2025 campaign과 분리 |
| H2 July 확장 | 2026-07-01~2026-07-31 | June/H1 경계 continuity 확인 |
| 2025 adjacent-year reconciliation | 2024-10-01~2026-03-31 | 2025 사건의 선행·후속·정정 탐색 roadmap; 계획 범위 |
| Daily market article | 운영일 당일 및 최근 중첩 window | 게시시각·수집시각 KST 분리 |
| 경쟁입찰 매각절차 | 2020-01-01~2024-12-31, 2025 별도 | 연×자산용도×권역×process bundle×월 |
| 2025 매각 case-depth | 2025 선정 자산 | 자산명×입찰·funding·closing keyword |
| 기관 LP→manager | 2020-01-01~2025-12-31 | 공식 source 우선 |
| pre-2020 기관자금 | 공개적으로 찾을 수 있는 최초 기록~2019-12-31 | 2000 이전/2000~09/2010~14/2015~19 archive tier |
| 국토부 실거래 | 월별 API campaign, 최근월 중첩 재조회 | 계약일·신고/취소·수집일 분리 |
| 기업 watch | 월말 마지막 KRX 거래일 snapshot | 현재 ranking을 과거에 소급하지 않음 |
| 현재 local document 발행시각 범위 | 2020-01-02~2026-08-19 | snapshot에 저장된 document version 기준 |

시간범위의 경계는 `[start, endExclusive)`로 저장한다. 후속보도나 정정공시가 범위 밖에 있어도 이전 사건의 revision/continuity claim으로 연결하며 원 campaign checkpoint를 재사용하지 않는다.

---

## 7. 특수 탐색 campaign

### 7.1 경쟁입찰 매각절차

**자산군**

- OFFICE: 오피스, 업무용빌딩, 사옥
- HOTEL: 호텔, 리조트, 관광숙박
- LOGISTICS: 물류센터, 물류창고, 풀필먼트, 저온창고
- DATA_CENTER: 데이터센터, IDC, AI데이터센터

**process bundle**

1. `MANDATE_BID`: 매각주관사, 매각자문사, 예비입찰, 본입찰
2. `SHORTLIST_PREFERRED`: shortlist, 적격인수후보, 우선협상대상자, 우협
3. `FUNDING_CLOSING`: 입찰가격, 인수금융, 블라인드/프로젝트펀드, SPA, 종결, 잔금, 무산, 재입찰

RSS title/snippet은 candidate discovery에만 사용하고 자동 canonical event로 올리지 않는다. `campaigns/backfill-2025-sale-process-case-depth.json`에는 2025년 상세 추적 대상 자산 18건의 name query가 정의돼 있다.

### 7.2 기관자금·위탁운용사

탐색 기관군은 국민연금, 우정사업본부, KIC, 공무원연금, 교직원·행정·군인·경찰·과학기술인·노란우산·건설근로자 공제회, 한국성장금융, 한국벤처투자, 산업은행, 기업은행, HUG, 캠코, 새마을금고·신협·농협 계열 및 공개모집 보험·은행·금융지주 LP를 포함한다.

대표 query:

- `{기관} {연도} 위탁운용사 선정 공고 부동산`
- `{기관} {연도} 위탁운용사 선정 결과 대체투자`
- `{기관} {연도} 출자사업 선정 운용사 인프라`
- `site:{공식도메인} 위탁운용사 모집 선정 결과`
- `site:{공식도메인} 첨부파일 제안요청서 투자 가이드라인`

필수 조사필드는 LP, 프로그램, 공고·접수·선정일, mandate 상태, 금액 basis, manager allocation, target fund size, return metric의 gross/net, 전략·sector·geography·risk, 투자기간·fund term·leverage·deal limit, 지원/shortlist/선정 운용사, vehicle, 납입·deployment, 공식 URL·document version·정확한 인용문이다.

뉴스-only 결과는 live canonical이 아니라 verification candidate로 보존한다.

### 7.3 기업·임차·이전·시가총액

- 월말 KRX 시가총액 전체 Top 50
- 시점별 산업분류 시가총액 Top 10
- 당시 공식정책·기업투자·시장자료에서 부각된 신산업 watchlist
- 현재 기업 ranking·산업분류를 과거 사건에 소급하지 않는다.
- 기사 anchor 전 90일~후 180일의 DART, 사업·분기·반기보고서, IR, 거래소 공시를 비교한다.
- 공시 부재는 임차·이전 기사의 반증이 아니다.

---

## 8. Source와 수집정책

### 8.1 발견 source

- Google News RSS: 넓은 keyword discovery, redirect·coverage 변동 유의
- 네이버 뉴스 API: API 승인·quota 내 title/snippet discovery
- 경제지·통신사 RSS: 제공 RSS field 범위만 저장
- 딜·IB 전문매체: metadata-only, 유료벽 우회 금지
- 기업·운용사·REIT 보도자료: 당사자 주장으로 표시

### 8.2 공식·검증 source

- OpenDART·KRX KIND: 자산양수도, 차입, 보증, 담보, 출자, 정정
- 국토부 상업업무용 실거래 API: 신고 거래·취소·정정
- 건축HUB: 건축물대장·인허가·착공·사용승인
- VWorld: 주소·좌표 정규화 보조
- 리츠정보시스템·공공데이터
- 지자체 고시·공고·공보, 토지이음
- 온비드, 공공기관 입찰, LH·지역공사
- R-ONE, ECOS, FISIS 등 macro/context source
- 세움터·등기소·법원경매는 약관과 인증 범위상 수동검토 우선

### 8.3 정책코드

| 코드 | 허용범위 |
|---|---|
| `API_ALLOWED` | 공식 API 문서·quota·약관 내 자동수집 |
| `RSS_ONLY` | RSS/Atom 제공 field만 저장 |
| `PUBLIC_LOW_RATE` | robots/약관 확인 후 공개페이지 저빈도 접근 |
| `METADATA_ONLY` | title·URL·publisher·date·최소 evidence |
| `MANUAL_REVIEW` | 운영자 수동 확인 |
| `PROHIBITED` | 수집 금지 |

API key가 존재해도 해당 endpoint 권한을 의미하지 않는다. provider/endpoint별 credential smoke test가 필요하다.

---

## 9. 수집·처리 방식

```text
Versioned Search Rule
  → Search Run / partition / cursor
  → Source Document + Document Version
  → Context / Irrelevant / Event Candidate 분류
  → Asset / Project / Organization Mention
  → Field Assertion + Evidence Locator
  → Entity Resolution / Duplicate Blocking
  → Official Verification
  → Manual Review
  → Canonical Event / Relationship Ledger
  → Dashboard Projection / Briefing
```

### 9.1 Partition과 saturation

- daily RSS는 `KST 운영일 × 카테고리 × 09:15/15:15/21:15 collection slot`으로 run identity를 구분한다.
- collection slot은 현재시각 이후가 아니라 가장 최근에 도래한 scheduler fire를 사용하므로, 21:15 slot은 다음 날 09:15 전까지 유지된다.
- 같은 collection slot의 재시도는 skip해 멱등성을 지키고, 다음 slot은 같은 날짜를 다시 조회해 새 기사와 수정 version을 증분 반영한다.
- 동일 run ID는 PostgreSQL transaction advisory lock으로 직렬화하며, 동시 실행도 완료 run을 확인한 뒤 한쪽만 실제 처리한다.
- connection 설정 transaction은 먼저 commit하고 각 partition을 독립 최상위 transaction으로 처리해, partition 종료 시 advisory/row lock과 쓰기를 함께 해제한다.
- 그 외 campaign은 동일 rule·version·cursor 중복실행을 막는다.
- RSS result 100건은 saturation 신호다.
- July campaign은 90건 이상부터 recovery 필요성을 경고한다.
- 상한 근접 시 월→주→일, asset type, region, keyword bundle로 분할한다.
- 0건과 실패를 별도 상태로 기록한다.

### 9.2 Idempotency

- source identity, canonical URL, content hash, published date, partition을 사용한다.
- 같은 source version과 pipeline version의 enrichment는 재처리하지 않는다.
- parser 수정 등 명시적 재생성이 필요할 때만 `--force`를 사용한다.
- 정정공시는 기존 row overwrite가 아니라 새 document version이다.

### 9.3 관계정합화

수집 transaction commit 후 별도의 감사 가능한 run으로 관계정합화를 수행한다. 문서 수집 성공과 entity resolution 성공을 하나의 상태로 합치지 않는다.

---

## 10. 기사 본문·요약 원칙

1. Google News wrapper URL을 실제 publisher URL로 resolve한다.
2. HTTP(S) 80/443만 허용하고, 최초 URL과 모든 redirect의 DNS 결과가 전부 public global IP인지 확인한다.
3. 검증한 IP에 socket을 pin하고 HTTPS certificate는 원 hostname으로 검증해 DNS rebinding과 private·loopback·link-local·metadata endpoint 접근을 차단한다.
4. robots.txt 조회 실패·차단은 fail-closed하며 본문을 요청하지 않는다.
5. response body는 최대 2MB의 text/html·xhtml·plain만 허용하고 `trafilatura`는 다운로드가 아니라 navigation·광고 제거에만 사용한다.
6. publisher 전문은 unrestricted body로 저장하지 않는다.
7. 핵심 문장 extractive summary와 최대 900자의 safe excerpt만 저장한다.
8. 결과는 source `document_version_id`와 `pipeline_version`에 귀속한다.
9. `BODY_EXTRACTIVE`, `MODEL`, `SOURCE_SNIPPET`, `NONE`과 `FULL_TEXT`, `SAFE_EXCERPT`, `SNIPPET`, `METADATA`를 구분한다.
10. 추출불가·본문부족·robots·유료벽·JS rendering 문제는 실패상태와 error code를 남긴다.
11. title 또는 RSS snippet을 본문요약으로 위장하지 않는다.
12. summary 생성시각·method·resolved URL·content hash·parser version을 표시한다.

현재 pipeline은 `content-extractive-v1`이다. 외부 생성형 model은 도입하지 않았으며, 향후 도입 시에도 source fact와 generated text를 명확히 분리한다.

---

## 11. 실거래 분석범위

- 주거 거래는 제외한다.
- 건물면적 `≤1,000㎡`: 기본 제외
- `1,000~3,300㎡`: 검토대상
- `>3,300㎡`: 유지
- 동일 주소·거래일·금액의 거래군 합계면적이 `>3,300㎡`이면 구성행도 검토한다.
- dashboard 기본값은 `1,000억원 이상`만 표시한다.
- `1,000억원 = 100,000,000,000원`, 국토부 `dealAmount` 단위 환산을 server에서 처리한다.
- 저가거래는 사용자가 명시적으로 toggle을 켠 경우에만 포함한다.
- 공식 실거래에 없다고 지분·수익증권 거래가 없다고 판단하지 않는다.

---

## 12. 식별·중복·검증

### 12.1 자산 식별 우선순위

1. 건축물대장 관리번호
2. PNU/필지 집합
3. 정규화 도로명주소 + 동/본관
4. 좌표거리 + 자산유형 + 면적 허용오차
5. 이름·별칭은 candidate 생성에만 사용

동명 빌딩은 자동 병합하지 않는다.

### 12.2 프로젝트 식별

`정규 사업구역명 + PNU/필지 + 시행사/SPC + 개발용도`를 주요 blocking key로 사용한다. 프로젝트와 물리자산을 분리한다.

### 12.3 조직·펀드·SPC

DART corp code, 종목코드, 법인등록번호, 사업자등록번호를 우선한다. 동일 운용사의 여러 펀드·REIT·SPC를 운용사 하나로 병합하지 않는다.

### 12.4 이벤트 중복

주 카테고리, 자산/프로젝트 교집합, subtype/stage, 날짜·금액 bucket, 핵심 당사자 역할, title/evidence 유사도를 사용한다.

- 같은 단계·같은 사건: 기존 event에 evidence/assertion 추가
- 단계변경: 새 event + previous/transaction group
- 정정: supersedes 연결
- portfolio: 거래 event 하나 + 여러 event_assets
- PF와 매매계약: 별도 event + 같은 transaction group

### 12.5 검증등급

- V4 `LEGALLY_VERIFIED`: 등기·공식 실거래·법적 효력 문서
- V3 `OFFICIAL_CONFIRMED`: DART/KIND/REIT/인허가 API
- V2 `MULTI_SOURCE_CONFIRMED`: 독립 source family 2개 이상
- V1 `SINGLE_SOURCE`: 신뢰매체 또는 당사자 1개
- V0 `RUMOR_OR_UNRESOLVED`: 익명·검토·식별불가

동일 보도자료의 전재는 독립 source로 세지 않는다.

---

## 13. 수동검수와 승인

다음은 자동게시하지 않는다.

- 주소·PNU·건물번호가 불완전하거나 후보가 여러 개
- 동명 법인·SPC·fund 후보가 여러 개
- 금액·날짜·당사자·단계가 충돌
- 검토·계약·closing 상태가 불명확
- 고가·중요 사건인데 기사만 존재
- API 성공이지만 후보가 검색되지 않음
- 한 기사에 여러 자산·사건 혼재
- portfolio 일부만 식별
- 정정·철회·취소 발견
- 강한 종결상태로 승격

Canonical approval gate:

- 주 카테고리 정확히 1개
- evidence 1개 이상
- 자산 또는 프로젝트 관계 1개 이상, 없으면 예외사유
- unresolved 핵심 mention 해소 또는 override
- 핵심 검색값 선택
- duplicate 처리
- contradicted assertion 해소 또는 관리자 사유
- reviewer와 결정이력 기록

---

## 14. 데이터모델 원칙

핵심 계층:

- **Source ledger:** collection source, search rule/run, source document, document version
- **Extraction layer:** mention, claim/assertion, evidence locator, extraction run
- **Master layer:** asset, project, organization, fund/vehicle, aliases와 identifiers
- **Event layer:** event, category, stage, transition, assets/projects/participants
- **Review layer:** verification, review task/decision, approval, duplicate/merge lineage
- **Market structure:** sale process, bid round, participant, milestone
- **Institutional capital:** LP, mandate, track, manager selection, vehicle, commitment/deployment
- **Company intelligence:** point-in-time universe, rank, industry assignment, business profile, tenant/relocation relation
- **Enrichment:** version-bound summary, safe excerpt, parser/pipeline provenance
- **Classification:** governed scheme, hierarchical term, evidence-aware record assignment, drift-free serving projection

Raw discovery, candidate, approved canonical을 같은 table 상태처럼 노출하지 않는다.

공통 분류는 `classification_schemes` → `classification_terms` → `record_classifications`를 권위 구조로 사용한다. 기존 `primary_category_id`, `asset_class_id`, `document_type`, `organization_type`, `strategy_code`, `category_code`는 원본 의미와 하위 호환을 위해 유지한다. 상태·근거등급·record kind를 market category에 섞지 않으며, 상세 vocabulary 운영은 `docs/classification-taxonomy-v1.md`를 따른다.

---

## 15. Dashboard 설명 원칙

### Navigation

- 카테고리와 filter를 분리한다.
- document type selector를 중복 배치하지 않는다.
- entity click은 관련 event·asset·document를 detail drawer에서 연결한다.
- mobile에서도 drawer와 table이 가로 overflow 없이 동작해야 한다.

### 유형별 설명

- 기사: 본문 기반 요약·safe excerpt·publisher·게시/수집/생성시각
- 공시: 회사·자산·금액·목적의 deterministic summary
- 실거래: 금액·주소·계약일·면적·단가·용도·당사자·취소
- 이벤트: 단계·기준일·관련 자산·조직·근거문서
- 자산: 자산정보·관련 사건·조직·문서
- 회사: 업종·시총순위·사건·자산·임차·계약 관계
- 기관자금: LP→프로그램→금액 basis→근거등급→vehicle/deployment
- 매각절차: 매각방식·현재단계·자산·bid round·milestone·근거

Structured narrative는 보유한 field를 읽기 쉬운 문장으로 조합할 뿐, 없는 사실을 생성하지 않는다.

---

## 16. 운영 architecture와 보안

```text
RSS / OpenDART / MOLIT / Approved manifests
  → PostgreSQL writer / reconciliation worker
  → Supabase PostgreSQL market_intelligence (active serving)
  → server-only Next.js API
  → authenticated dashboard

Supabase active rows
  → deletion-free PK upsert merge
  → data/market.db (read-only local full archive)

inactive detail
  → immutable validated SQLite snapshot
  → Supabase compact historical index + archive locator
```

- browser는 DB에 직접 연결하지 않는다.
- raw SQL endpoint와 unrestricted `stored_text` 노출을 금지한다.
- DB URL·access code·session secret·API key는 server-only다.
- 실제 credential은 `C:\10137_WorkSpace\env\` 외부 파일에서 주입하고 이 폴더나 Git에 복사하지 않는다.
- `.env.example`에는 변수명만 둔다.
- 인증 cookie는 HttpOnly, SameSite=Lax, 12시간 만료, HTTPS에서만 Secure다.
- 이 전달본에는 `.env`, private key, token, connection string이 포함되지 않는다.

### 실제 daily article schedule

- Hermes local scheduler: 매일 KST `09:15`, `15:15`, `21:15`
- 실제 scheduler runner ROOT: `09. CRE DB Board`로 전환 완료
- 처리: Supabase RSS 증분 collector 성공 → Supabase document enrichment
- 같은 날짜의 3개 collection slot은 독립 실행하며, 동일 slot 재시도만 멱등적으로 skip한다.
- enrichment는 session advisory lock으로 단일실행하며, 동시 호출은 `skipped_concurrent`로 정상 종료한다.
- 본문 network fetch 동안 DB transaction을 열어두지 않고 candidate 조회와 row별 저장을 짧게 commit한다.
- SQLite snapshot refresh는 scheduler에 포함하지 않고 운영자가 명시적으로 실행하는 수동 절차로 유지한다.
- 제약: 해당 PC와 Hermes scheduler가 실행 중이어야 한다.

### 설계상 recurring cadence

- 뉴스: 1~3시간 또는 daily overlapping window
- OpenDART: 평일 당일+최근 3일 재조회
- MOLIT: 월·직전월·직전 2개월 중첩
- silent-gap recovery: 최근 14일
- 월간 마감: recovery, relation reconciliation, macro, coverage QA, backup
- 분기: query synonym/source/taxonomy/false positive 감사
- 반기·연간: campaign closure와 장기시계열 감사

실제 scheduler와 설계목표가 다를 경우 이 절에 양쪽을 함께 기록하고 운영상태를 과장하지 않는다.

---

## 17. Local full archive / Supabase active serving 운영

- `data/market.db`는 전체 이력·비활성 상세·evidence lineage를 보존하는 read-only local full archive다.
- Supabase는 웹앱용 active 상세와 `archived_serving_index` compact history를 제공한다.
- full archive 갱신은 active row를 PK upsert하며 archive-only row를 삭제하지 않는다.
- legacy overwrite refresh는 current archive snapshot이 등록된 뒤 hard guard로 중단한다.
- retire 전 immutable SQLite snapshot의 SHA-256·row count·integrity·FK를 검증한다.
- 장애 시 local archive는 조회·복원 근거이며 자동 write main으로 승격하지 않는다.

### 현재 local full archive

- 갱신시각: 2026-08-21 11:09 KST 부근
- application table: 105개
- 전체 적재행: 138,273행
- schema: 3.3.0
- `PRAGMA integrity_check`: `ok`
- FK violation: 0
- SHA-256: `047b5766a5cdb98656613c12ddd11c24c31eaa2edb01e9f1c04fb775a5e6e3bf`

대표 데이터량:

| 항목 | 수량 |
|---|---:|
| MOLIT API_RECORD | 47,264 |
| Google News RSS_ITEM | 8,094 |
| OpenDART DISCLOSURE | 2,155 |
| ARTICLE | 39 |
| BID_NOTICE | 9 |
| NOTICE | 7 |
| PRESS_RELEASE | 1 |
| organizations | 2,826 |
| canonical events | 35 |
| assets | 16 |
| LP mandates | 19 |
| classification schemes | 8 |
| classification terms | 227 |
| record classifications | 28,814 (현재 유효 28,079 / superseded archive V1 735) |
| sale processes | 16 |
| document enrichments | 200 |
| enrichment completed | 167 |
| enrichment failed | 33 |

Enrichment 세부:

- RSS article: 75 completed / 25 failed
- Disclosure: 92 completed / 8 failed

실패는 데이터 삭제나 가짜 summary로 대체하지 않는다.

### Campaign 실행 증거와 coverage 한계

- 2026년 7월 H2 campaign: 총 문서 2,389건(RSS 499, MOLIT 1,870, OpenDART 20), 97개 run 완료, 최대 게시·거래일 2026-07-31
- 2020~2025 경쟁매각: live sale process 16건, 심층조사 47건 중 승인 14건·비승격 33건
- 2020~2024 경쟁매각 Google News partition: 240/3,420 완료, **coverage 7.02%**
- 나머지 3,180 partition은 정상 0건이 아니라 upstream throttling으로 미완료다. 따라서 이 구간을 뉴스 경쟁매각 전수조사로 표현하지 않는다.

---

## 18. QA와 완료기준

### 데이터 QA

- table별 PostgreSQL/SQLite row count 일치
- SQLite integrity `ok`, FK 0
- PK·UNIQUE·CHECK·FK validation
- source version·hash·cursor·partition idempotency
- 최신 document version만 active extraction
- duplicate family, supersession, relation gap 확인
- canonical/candidate 분리

### Application QA

- Python unit/integration tests
- frontend component/API contract tests
- ESLint
- Next.js production build
- 인증 전/후 HTTP smoke
- desktop와 390px mobile screenshot·overflow 검증
- live Vercel API에서 summary, safe excerpt, provenance 확인

### Campaign 완료식

```text
source coverage recorded
+ extraction completed
+ entity resolution completed
+ relation reconciliation completed
+ unresolved gaps recorded
+ canonical/candidate segregation checked
+ integrity/FK/duplicate/idempotency QA passed
```

---

## 19. 알려진 한계

1. 일부 언론사는 robots, paywall, JavaScript rendering 또는 markup 때문에 본문추출이 실패한다.
2. extractive summary는 원문 핵심문장을 보존하는 1단계이며 분석형 abstractive summary는 아니다.
3. RSS는 discovery source이지 법적 확정 source가 아니다.
4. 국토부 실거래는 지분·수익증권·일부 간접거래를 포괄하지 않는다.
5. pre-2020 LP 자료는 오래된 첨부와 domain 변경으로 archive gap이 존재한다.
6. canonical event·asset 수는 raw 문서 수보다 훨씬 적으며, 이는 보수적 승인정책에 따른다.
7. company tenant/relocation watch 일부는 collector 구현 준비상태이며 모든 계획이 현재 자동운영 중인 것은 아니다.
8. Hermes scheduler는 local PC 의존성이 있다.
9. SQLite 300MB 이상 파일은 일반 Git remote의 단일파일 제한을 넘을 수 있다. 이번에는 사용자의 요청에 따라 **로컬 Git commit**에 포함하며, 원격 push 전 Git LFS 또는 artifact storage 정책을 별도로 정해야 한다.
10. 원본 repository의 미커밋 enrichment 변경은 이 전달본에 포함했지만 source commit SHA만으로 완전 재현되지 않으므로 `migration-manifest.json`을 함께 확인한다.
11. article enrichment는 robots.txt 조회 실패도 fail-closed하므로 공개 source라도 일시적 네트워크 오류 때 실패율이 높아질 수 있다. 실패는 요약으로 위장하지 않고 후속 재시도 대상으로 남긴다.
12. 2020~2024 경쟁매각 RSS coverage는 7.02%이며 미완료 3,180 partition이 남아 있다.

---

## 20. 폴더 구성과 재현

| 경로 | 내용 |
|---|---|
| `web/` | Next.js dashboard, server API, auth, 유형별 detail UI |
| `data/market.db` | 최신 read-only SQLite sub snapshot |
| `db/v2/` | V2.8 통합 schema와 PostgreSQL/SQLite migration |
| `collector/` | RSS·DART·MOLIT·manifest ingestion/reconciliation logic |
| `scripts/` | migration, Supabase probe, snapshot refresh, article collector/enrichment |
| `operations/hermes/` | repository 밖 scheduler runner의 secret-free portable 사본 |
| `tests/` | Python schema·migration·collector·enrichment tests |
| `rules/` | 7개 category keyword·stage taxonomy |
| `campaigns/` | 기간별·주제별 탐색 campaign 정의 |
| `config/` | 자산·지역·LP·manifest policy/schema |
| `fixtures/` | 승인·candidate test/research fixture |
| `docs/` | system contract, source matrix, review, operations, runbook |
| `artifacts/` | migration·coverage·QA·분석 산출물 |
| `reports/` | 실행·분석 report |
| `migration-manifest.json` | source lineage, 복사정책, 제외항목, SQLite hash |
| `principle.md` | 본 통합 원칙 |

### Dashboard local 실행

```bash
cd web
npm ci
npm test
npm run lint
npm run build
```

실행 시 실제 secret은 프로젝트 외부 env에서 주입한다. 이 전달본에는 credential이 없다.

### Python test

```bash
uv run --with pytest python -m pytest -q
```

### Supabase active→local full archive merge

```bash
uv run --with 'psycopg[binary]' python scripts/merge_supabase_active_into_full_archive.py --activate
```

실행 전 외부 `.env.supabase.local`이 필요하며 secret을 log나 Git에 출력하지 않는다.

---

## 21. 변경관리

1. category/keyword 변경은 rule version과 campaign version을 함께 올린다.
2. schema 변경은 SQLite integrated schema, PostgreSQL migration, SQLite migration, tests를 함께 수정한다.
3. collector 변경은 idempotency·date boundary·source policy test를 선행한다.
4. dashboard 계약 변경은 server projection·TypeScript contract·UI test를 함께 수정한다.
5. Supabase 변경 후 active row를 local full archive에 deletion-free merge하고 hash·row count·integrity를 갱신한다.
6. 공식 source 정정은 기존 document/assertion을 삭제하지 않는다.
7. credential, raw article body, local DB를 일반 public Git/Vercel source에 올리지 않는다.
8. 본 `principle.md`의 현재상태·한계·snapshot 수치를 함께 갱신한다.

---

## 22. 권위 근거파일

- `docs/01-system-contract.md`
- `docs/02-source-matrix.md`
- `docs/03-review-policy.md`
- `docs/08-recurring-research-operations-plan.md`
- `docs/09-supabase-main-sqlite-sub-runbook.md`
- `rules/category-rules.json`
- `campaigns/backfill-2025.json`
- `campaigns/backfill-2026-h1.json`
- `campaigns/backfill-2026-h2-july.json`
- `campaigns/backfill-2020-2024-bid-process.json`
- `campaigns/backfill-2025-bid-process.json`
- `campaigns/backfill-2025-sale-process-case-depth.json`
- `campaigns/backfill-2020-2025-lp-manager-selections.json`
- `campaigns/backfill-pre-2020-lp-manager-selections.json`
- `campaigns/company-tenant-relocation-marketcap-watch.json`
- `db/v2/schema.sql`
- `scripts/collect_daily_rss_supabase.py`
- `scripts/enrich_document_content.py`
- `scripts/merge_supabase_active_into_full_archive.py`
- `scripts/stage_active_serving_archive_index.py`
- `scripts/retire_supabase_collection_history.py`
- `web/src/lib/server/document-intelligence.ts`
- `web/src/lib/server/daily-articles.ts`
- `migration-manifest.json`

이 문서와 근거파일이 충돌할 경우, source별 구체 query·schema field는 해당 versioned JSON/SQL/code를 우선하고 본 문서는 통합 운영원칙으로 갱신한다.
