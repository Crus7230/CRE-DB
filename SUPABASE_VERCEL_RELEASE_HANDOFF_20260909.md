# CRE DB 신규 Supabase 전환 · Vercel 릴리스 인수인계

> 이 릴리스에는 생성형 AI/LLM 호출이 없다. `스마트 조회`와 기사 `색인 검색`은 고정된 외부 API 및 사전 구축 인덱스를 이용하는 결정론적 조회 경로다.

## 현재 결론

- 신규 Supabase 적재·검증과 로컬 Supabase 연동 QA는 완료됐다.
- 표준 웹 테스트는 `77 files / 311 passed / 1 skipped`, lint는 종료 코드 `0`으로 통과했다.
- 실제 UI/API 검증은 로컬 `http://localhost:3015`의 신규 Supabase 연동 서버에서 통과했다. 이는 프로덕션 검증 결과가 아니다.
- `https://cre-db.vercel.app`의 환경 변수, 배포, alias는 아직 변경하지 않았다.
- 남은 외부 차단 조건은 Vercel 인증이다. 준비 시점의 개인 환경 파일에는 `VERCEL_TOKEN`이 없고, 대시보드도 로그인 상태가 아니다.
- GitHub `Crus7230` 자격 증명도 현재 없으므로 원격 push는 별도 미완료가 될 수 있다. Vercel CLI 직접 배포는 GitHub push 없이 진행 가능하며, 그 경우 로컬 릴리스 커밋과 미push 상태를 명시한다.

## 신규 Supabase 최종 스냅샷

| 항목 | 최종 검증값 |
| --- | --- |
| project ref | `rjalzmmiqhrdmhojbxsk` |
| PostgreSQL / 연결 위치 | PostgreSQL `17.6` / Tokyo pooler |
| dataset version | `cre-20260909T060407Z-5c55a7cb58de` |
| schema version | `1.1.0` |
| source freshness | `2026-09-09T06:04:07Z` (`2026-09-09 15:04:07 KST`) |
| 전체 `pg_database_size` | `61,549,715 B` (약 `61.55 MB`, `58.70 MiB`) |
| `cre_news` | table `7,380,992 B` / index `8,855,552 B` / total `20,021,248 B` |
| `cre_timeseries` | table `15,368,192 B` / index `14,516,224 B` / total `29,933,568 B` |
| `cre_system` | table `49,152 B` / index `147,456 B` / total `303,104 B` |
| 기사 색인 객체 `article_search_documents` | table `1,802,240 B` / index `2,228,224 B` / total `4,136,960 B` |
| 무효 constraint | `0` |
| RLS | private table `15/15` 활성 |

스키마 객체 합계와 전체 DB 크기의 차이는 PostgreSQL 시스템 카탈로그·확장·TOAST 등 스키마 집계 밖 저장공간이다. 원본 아카이브나 로컬 DB를 Vercel 릴리스에 포함하지 않는다.

### 적재·조회 정합성

| 데이터셋 | 행 수 |
| --- | ---: |
| articles / article_details / article_search_documents | `2,145 / 2,145 / 2,145` |
| article_dates / article_topics | `498 / 1,103` |
| macro_series / macro_monthly | `19 / 4,471` |
| market_pulse | `1` |
| permit_monthly | `90,907` |

- 패키지와 DB의 의미 해시는 위 9개 데이터셋 모두 일치했다.
- 승인 subject는 `3`건이며 미등록 subject는 거절됐다.
- 최초 rate-limit 점검은 차단되지 않았고, 테스트 상태 정리는 완료됐다.
- 2글자 검색은 전용 terms 인덱스, 3글자 이상 검색은 trigram 인덱스를 사용하는 실행 계획을 확인했다.
- 최종 독립 검증의 fresh connection 측정은 OS 캐시를 강제로 비우지 않은 별도 DB 연결/준비 계획 측정이다: 2글자 query `75.103 ms`, trigram query `103.333 ms`. 웹 warm HTTP 수치와 혼동하지 않는다.

검증 원본은 canonical 작업 폴더의 `artifacts/supabase-compact/publish-report-20260909-final.json`에 있으나, `artifacts/`는 릴리스에서 명시적으로 제외한다.

위 표는 root 독립 검증 보고서의 최종 snapshot(`61,549,715 B`)이다. 같은 dataset version에 대한 후속 no-op `verified-existing` readback은 `61,516,947 B`였고, 차이 `32,768 B`는 system 영역의 물리 배치 변동이다. 따라서 dataset 동일성은 version/semantic hash/행 수로, 물리 용량은 보고서 측정 시각과 함께 기록한다.

## 로컬 웹 QA 증거

검증 대상은 신규 Supabase에 연결된 `http://127.0.0.1:3015`이며, 기존 포트 `3005`는 건드리지 않았다.

- 최신기사: 기사 `7`건, 카테고리 합계 `7`, 기사 상세 drawer와 색인 검색 동작 확인.
- 시계열자료: macro `13`개, permit `2025-01`~`2026-08`, market pulse 및 차트 렌더 확인.
- 스마트 조회: 주소 `서울시청`의 건축물대장 HUB 카드 `2`건, 회사 `005930`의 DART·공시·KRX 상태 정상 확인.
- desktop/mobile 모두 3개 탭, 상세 drawer, 검색 결과를 확인했고 가로 overflow와 브라우저 오류는 `0`이었다.
- 실제 렌더 증거는 canonical의 `artifacts/cre-dashboard-visual-qa.json` 등 QA 산출물에 있으며 릴리스에는 포함하지 않는다. evidence 검색은 첫 상세 API가 반환 ID/title과 일치하는 `200`이었고, 2글자 검색은 `8`건과 `truncated=true`, `%_` literal은 `200/0건`, 1글자·역순 기간·`topK=99`는 모두 `400`이었다.
- auth login은 로컬 격리 환경 밖 요청으로 `200`을 확인했다. 초기 evidence 요청의 `403`은 Next 내부 URL과 QA origin 불일치였으며 same-origin 수정 후 전체 회귀 테스트가 통과했다.

### 로컬 warm HTTP 측정

| 경로 | 측정 |
| --- | ---: |
| news | `5.8 ms` |
| macro | `11.3 ms` |
| pulse | `6.3 ms` |
| permits | 첫 요청 `131.9 ms` → 반복 `4.8 ms` |

이 수치는 실행 중인 로컬 서버의 HTTP 관측값이며 프로덕션 수치나 OS/DB 캐시를 비운 진정한 cold DB 측정이 아니다. 응답 계약은 data RPC를 `Server-Timing: data`, 인증 RPC를 `X-CRE-Authz-Ms`로 분리해 기록한다. 데이터 API는 `private, no-store`이며 익명 `401` 계약은 자동화 테스트로 검증됐다. staged/live의 실제 익명 `401`, 로그인, cold/warm 헤더 검증은 배포 후 다시 수행해야 한다.

## 릴리스 후보의 출처와 제외 범위

- 기준: 실제 원격 `main`으로 확인한 `eef5faf4a773f3b6080e852380ba6cfcac05c5db`.
- 분리 checkout: `.codex_tmp/cre-release-20260909`.
- 로컬 branch: `codex/cre-supabase-release-20260909`.
- 1차 overlay: 보존된 기존 checkout의 정확한 31-file 3탭·스마트조회·로컬분리 delta.
- 2차 overlay: canonical `09. CRE DB Board`의 신규 Supabase runtime/cache/auth/evidence/API, 마이그레이션·export/publish·테스트·운영 문서.
- 파일 단위 authority는 `operations/release/source-delta-files.txt`로 고정하고, copy 전후 SHA-256을 대조한다.
- 제외: DB/SQLite와 journal, backup, raw, artifact/report/log, 환경 파일, credential, `.vercel`, `node_modules`, `.next`, `.next-*`, `.codex_tmp`, 임시 smoke 파일.

## 프로덕션 환경 변경 범위

root QA 승인 후 production target에서 아래 8개만 현재 authority와 동기화한다. 기존 세션 비밀과 그 밖의 환경 변수는 보존하며 전체 삭제/재생성하지 않는다.

| 키 | authority / 요구사항 |
| --- | --- |
| `SUPABASE_URL` | 개인 환경의 신규 project URL |
| `SUPABASE_SECRET_KEY` | 개인 환경의 신규 server secret |
| `SUPABASE_PROJECT_REF` | 반드시 `rjalzmmiqhrdmhojbxsk` |
| `DASHBOARD_DATA_PROVIDER` | 반드시 `supabase` |
| `VWORLD_KEY` | 기존 global 외부 API authority |
| `DATA_GO_KR_KEY` | 기존 global 외부 API authority |
| `DART_API_KEY` | 기존 global 외부 API authority |
| `KRX_API_KEY` | 기존 global 외부 API authority |

- 개인 env의 중복 정의는 값 충돌이 없다: URL·secret·publishable은 각각 2개 정의가 같은 값이고 project ref는 1개이며 신규 ref와 일치한다.
- 기존 production에 `DASHBOARD_SUPABASE_RPC_SCHEMA`가 있으면 값을 노출하지 않고 `public`인지 preflight한다. `SUPABASE_DB_SCHEMA`는 현재 runtime에서 무시되지만 삭제하지 않는다.
- `DASHBOARD_SESSION_SECRET`과 기존 모든 비대상 key는 보존한다.
- `SMART_LOOKUP_ENV_FILE`은 local-only이므로 Vercel에 넣지 않는다.

## 남은 gate와 실행 순서

1. canonical 최종 파일 목록을 manifest에 확정하고 clean staging에서 validate-only를 통과시킨다.
2. 명시 파일만 staging에 복사하고 SHA-256, full test, lint, type/build, visual 검증 및 secret/forbidden/conflict scan을 완료한다.
3. 로컬 branch에 릴리스 후보를 커밋한다. GitHub 인증이 없으면 push 미완료를 기록한다.
4. Vercel 인증이 확보되고 root가 QA 및 환경 변경을 명시 승인한 뒤, project/team/root와 기존 env 이름·target을 read-only로 확인한다.
5. 위 8개 production env만 동기화하고 metadata를 재확인한다.
6. `--prod --skip-domain`으로 alias 없는 staged production deployment를 만들고 READY까지 기다린다. 현재 `cre-db.vercel.app`은 계속 이전 배포를 가리킨다.
7. staged URL에서 익명 `401`, 허용/비허용 로그인, 3탭 API, 기사 상세·색인 검색, 주소/회사 스마트조회, version/cache/header, data/auth timing, desktop/mobile을 재검증한다.
8. root의 두 번째 promotion 승인을 받은 뒤 staged 배포를 rebuild 없이 promote한다.
9. production URL에서 같은 검증을 반복하고 deployment ID·READY 시각·alias·Supabase 버전·rollback ID를 기록한다.

이전 정상 배포 `dpl_7DWCMt1y81gDFbf4riGDQQQyCsEZ`는 rollback 대상으로 보존한다. staged 또는 live 검증 실패 시 DB를 변경하지 말고 이전 배포를 다시 promote한다.
