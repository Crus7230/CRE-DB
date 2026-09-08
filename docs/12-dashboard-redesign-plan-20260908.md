# CRE DB 대시보드 개편 계획 — 2026-09-08

## 목적과 완료 기준
최신 CRE 기사를 주제별로 빠르게 찾고, 공식 거래·금리·공급 시계열을 같은 기준으로 읽는 업무 화면으로 개편한다. 사용자가 승인한 범위는 현재 상태 분석, 레퍼런스 조사, 코드·필요 DB 구조 수정, 자체 QA, 운영 문서, 데이터별 예약, cre-db.vercel.app 배포, 로컬·원격 커밋이다. 프런트엔드와 데이터 구현은 gpt-5.6-sol / ultra 서브에이전트에 배정하고 root가 통합·시각 검수·배포를 담당한다.

완료 조건은 기능 테스트·빌드·데이터 정합성·desktop/mobile 시각 검수, 실계정 온라인 로그인 및 API readback, 예약 등록/실행 증거, secret 없는 커밋이다. 실패·미완료를 정상 0건으로 표시하지 않는다. 온라인 DB 제한 때문에 통과하지 못한 검증은 로컬 통과와 구분해 미완료로 기록한다.

## 1. 현재 상태 분석
- Next.js 16.3.1 + React 19 + TypeScript, Pretendard 로컬 폰트, lucide 아이콘.
- 현재 주화면은 최신기사 / 시계열자료 두 개. 시계열 안에는 서울 비주거 거래와 한국·미국 금리.
- globals.css에 과거 화면별 규칙이 누적돼 navigation과 mobile 규칙이 여러 번 재정의된다.
- 기사 위 masthead·탭·hero·통계·필터가 쌓여 실제 제목 노출이 늦다. 제목/출처/시간/분류의 시각적 계층을 재정리한다.
- 기사는 CRE 범위 판정 후 관리형 MARKET_CATEGORY를 연결한다. 자동 후보 분류와 사람의 승인, 원문 사건 확정은 서로 다른 상태다.
- 2026-09-07 최신일 표본 11건 중 7건은 자동분류, 4건은 분류 없음. 이 표본의 완성된 요약은 0건이므로 생성 요약을 있는 것처럼 표시하지 않는다.
- 최신기사 SQL은 날짜 축소 전 전체 문서 버전·범위 이력을 순위화한다. 이전 실측 원격 1.7~1.9초, 로컬 0.71~0.90초; 일자 우선 조회 실험은 4.2ms. 실제 변경 후 결과·시간 재검증.
- 탭 전환 시 데이터가 소멸하고 다시 fetch한다. 금리 API 응답은 13개 series / 4,467개 월 관측값 / 약 338KB이며 no-store가 재요청을 강제한다.
- Turso 환경변수 이름은 운영 Production/Preview에 존재한다. 9월 8일 `BLOCKED / SQL read operations are forbidden`을 확인했다. 사용자 화면은 읽기 2.63B / 500M, 저장 474.64MB / 5GB로, 저장용량이 아니라 월간 읽기 한도 문제다. 사용자는 무료 유지 및 새 DB 별도 검토를 선택했다. 10월 1일 전에는 원격 발행·반복 probe를 하지 않고 로컬 갱신과 코드 배포를 분리한다. 인증은 우회하지 않는다.
- 기존 Windows 예약 `\CRE DB\Daily Analytics Refresh`는 매일 06:30. 9월 8일 이전 Supabase merge 단계에서 ConnectionTimeout, LastTaskResult 1.
- 로컬 main과 origin/main 이력은 갈라져 있고 CRE 및 다른 대시보드 미커밋 작업이 많다. 전체 reset/pull을 하지 않고 배포용 원격 기준 체크아웃에서 CRE 변경만 통합한다.

## 2. 스키마와 데이터 표현
글로벌 schema 3.5.0 외에 기능별 permit 1.0.5, macro 1.0.2 등의 버전을 별도 관리한다. 현재 권위는 local SQLite archive, 원격은 Turso compact serving. 과거 Supabase 문서는 이 개편에서 현재 운영 지침과 구분한다.

| 데이터 | 원천/행 단위 | 화면 표현 | 가공 원칙 |
|---|---|---|---|
| 기사 | source_documents → document_versions → scope → record_classifications | 대표 주제별 목록, 게시시간, 출처, 자동/승인 배지, 상세 근거 | 최신 유효 버전, CRE 범위, 중복 대표 주제 하나; 다른 주제는 보조 배지 |
| 문서 요약·근거 | document_enrichments, document evidence | 실제 존재하는 요약, 원문 링크, 상세 drawer | raw JSON/전문 노출 금지, 없는 요약 생성 금지 |
| 실거래 | MOLIT 공개 신고행 및 최신 버전 | 월별 거래금액·건수·면적, 지역 구성, 신고행 상세 | 서울 비주거·면적 > 3,300㎡ 범위 명시; 거래행을 자산수로 표현하지 않음 |
| 금리 | ECOS / NY Fed / US Treasury, 13개 series | 그룹별 선그래프, 월 선택, 정확한 값·bp·출처 | 월공식값/일별 월평균 구분; 부분월 및 결측 유지 |
| 건축 인허가 | 서울 OA-22404 완료 snapshot | 허가·실착공·사용승인 월별 건수/연면적 | source별 합계; 최신 완료 snapshot, 예정일/오류면적 제외 |
| 후보·기관·기업 관계 | 후보와 승인된 정규 사건/관계 | 이번 메인 화면에서 별도 탭 확대하지 않음 | 기존 원천과 lineage 보존; 자동 추론을 확정 사실로 승격하지 않음 |

인허가 archive의 Sep 7 완료 snapshot과 serving의 Sep 2 기준 차이는 projection 갱신 때 대사한다. 실제 원격 table count와 기능별 최신일은 최종 상태 문서에 재측정해 기록한다.

## 3. 레퍼런스와 적용
아래는 공식 제품/도움말에서 확인한 표현방식이며 제품의 비공개 화면·독점 데이터·브랜드 자산을 복제하지 않는다.

| 레퍼런스 | 확인한 방식 | CRE 적용 |
|---|---|---|
| [Feedly 읽기 방식](https://docs.feedly.com/article/276-how-do-i-change-the-views-of-my-feeds-and-source) | text-only/magazine/cards와 compact/comfortable | compact 목록 기본, 선택 시 한 줄 요약; 작은 메타데이터 |
| [Feedly 검색 필터](https://docs.feedly.com/article/79-how-can-i-filter-my-search-results) | 제목·본문·출처 범위 선택 | 불러온 기사 내 검색과 주제 rail, 현재 검색 범위 표시 |
| [CoStar Custom Reporting](https://www.costar.com/products/custom-reporting) | 시장·자산 지표와 검색 결과의 분석 연결 | 거래/공급 KPI → 월별 차트 → 지역/원천 표의 순서 |
| [FRED FEDFUNDS](https://fred.stlouisfed.org/series/FEDFUNDS) | 관측월·단위·빈도·갱신일·출처를 그래프와 함께 표시 | 각 시계열의 값과 기준일, 월평균/부분월 표시, 원천 링크 |
| [FRED dashboard widgets](https://fredhelp.stlouisfed.org/fred/account/dashboard-features/add-widget/) | 기간·단위와 최신 N년 설정 | 5/10/20년/전체 선택과 월 동기화 |
| [AlphaSense monitoring](https://www.alpha-sense.com/blog/product/how-to-monitor-companies/) | 모니터링 목적별 feed 모듈과 상세 확인 | 기사와 시계열 목적을 분리하고 근거를 drawer로 단계 노출 |

선택한 시각 방향: 흰 작업면, 짙은 청록 강조, 얇은 경계, amber 자동분류 표시. 콘텐츠 첫 화면을 위해 큰 hero를 없애고 masthead는 56px 안팎으로 통합한다. 제목 15~16px, 메타데이터 12~13px, 표의 숫자는 정렬해 비교를 돕는다. 불필요한 장식 이미지 대신 실제 차트·분류 막대·상태 표기를 사용한다.

## 4. 구현 계획
1. 프런트엔드: `market-explorer` 공통 header/2-tab; 기사 topic rail + dense feed + 좁은 factual aside. 1건당 대표 주제 하나로 카테고리 합계=기사수. 자동 대표 분류는 탐색에 사용하되 검토 전 표시. topic 없는 기사만 분류 대기.
2. 시간자료: 거래 KPI/차트 우선, 숫자표·방법론은 펼쳐보기. 금리 그룹 chart는 기간/월을 공유하고 exact value 표시. 인허가 API 준비 후 시계열 내부에 공급 mode 추가.
3. 성능: SQL에서 날짜·최신 버전 먼저 제한, 선택된 기사에만 summary/classification join. 실제 이전/새 결과 동치 확인. 유지되는 client state, bounded timeout, cache, API timing.
4. DB: 원천 삭제 없이 필요 projection/index/refresh metadata만 추가. 기존 table명/API와 Android 호환성을 유지하며 news API 추가값은 optional. 인허가 serving stale snapshot 갱신.
5. 수집: source-aware locked pipeline, 후보 검증 → local 활성화 → 필요한 serving만 Turso 동기화 → readback. 실패 시 직전 정상 데이터 유지.
6. 배포: Vercel 운영 env 확인 → 로컬 production build와 시각 QA → 원격 기준 isolated checkout에 CRE 변경 통합 → commit/push → Vercel production deploy → 로그인/기사/3개 시계열/모바일 QA.

## 5. 자동화 초안
실 collector와 호출 제한 검증 후 정확한 명령을 운영 문서에 기록하고 예약한다.
- 뉴스: KST 06/09/12/15/18/21시, 최근 2일 재조회, collection slot 중복 방지.
- 공식 금리: 평일 08:00 KST, 최근 관측/정정 반영. ECOS는 월공표 시계열이므로 새 값 없는 날은 정상 유지.
- 서울 실거래: 수요일 07:30 KST, 최근 3개월 재조회해 후행 신고·정정 반영. 완료된 partition을 단순히 건너뛰지 않는다.
- 서울 건축인허가: 토요일 07:30 KST, full completed snapshot 및 projection. API quota/partial은 직전 완료본 유지.
- 수집/게시 건강상태: daily 모니터링, 실제 지연/실패 때 알림.
- 기존 Supabase 연결 예약은 현 local→Turso pipeline으로 교체. 아직 자료를 제공하지 않는 source를 완료/자동화로 표시하지 않는다.

## 6. QA 체크
- 기사: 과거일·최신일·주제별 집계/실목록 동일, 자동/승인/미분류, 검색, 날짜 경계, empty/error/timeout, 원문·drawer.
- 데이터: schema/integrity/FK, source별 latest snapshot, 최신 row와 payload hash, 반복 갱신 idempotency, 부분 실패 시 마지막 정상본 유지.
- 시계열: 단위·누적/증감·부분월·결측·source scope, 임대/기업 후보를 거래 실적에 혼합하지 않음.
- 성능: remote cold/warm + API end-to-end 별도 측정. 빠른 캐시만으로 개선을 주장하지 않음.
- 화면: desktop와 390px mobile 실제 렌더, overflow, header 중복, 첫 기사/차트 viewport, keyboard focus.
- 운영: 예약 readback, 최소 1회 실제 로컬 갱신 검증, 자동화 결과 보고서 확인. 원격 publish와 온라인 데이터 최신성 QA는 Turso 읽기 제한 해제 이후 별도 통과가 필요하다.
