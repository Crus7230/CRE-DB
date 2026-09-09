# CRE DB 신규 Supabase 전환 · GitHub/Vercel 릴리스 인수인계

> 기준일: 2026-09-09. 이 문서는 배포 직전 상태와 남은 production gate를 기록한다. 생성형 AI/LLM은 범위 밖이며, 스마트 조회와 기사 근거 검색은 고정 API 및 사전 구축 색인을 사용하는 결정론적 조회다.

## 현재 결론

- 신규 Supabase compact snapshot의 적재와 독립 readback, 로컬 웹 QA, 격리 release checkout 검증은 완료됐다.
- 최종 배포 경로는 **GitHub `Crus7230/CRE-DB`의 `main` push → 기존 Vercel `cre-db` 연동 자동 배포** 하나뿐이다.
- 로컬 checkout을 대상으로 `vercel deploy`, `vercel --prod`, `--skip-domain`을 실행하지 않는다. 별도 staged production deployment와 수동 promote 단계도 사용하지 않는다.
- Vercel CLI `59.13.1`의 `whoami`는 `cruslee00-6855`로 확인됐고, project/team/root/GitHub branch 연결도 read-only preflight로 일치했다.
- Windows Git Credential Manager에는 GitHub `Crus7230` 자격이 저장돼 있으며 push dry-run이 통과했다. 인증 차단은 없다.
- 현재 production 환경과 alias는 아직 변경되지 않았다. 배포 담당 D가 env 8개 적용·readback 및 최종 push/deploy 결과를 보고하기 전에는 완료로 간주하지 않는다.
- 현재 rollback 대상은 `dpl_5xDokCmsUozCt4K31USiDVywHv34`이며 READY, production alias `cre-db.vercel.app`에 연결돼 있다.
- 현재 release source는 `8d6d8d3`까지 준비됐고, 최종 commit·`main` push·Vercel production 배포는 아직 남아 있다.

## 고정 대상

| 항목 | 값 |
| --- | --- |
| GitHub | `Crus7230/CRE-DB` |
| 배포 branch | `main` |
| Vercel project | `cre-db` / `prj_1DTajzRAaw2IbqffiAwN2aZWC5Bb` |
| Vercel team | `team_ZraFevjGRitnuj6w5suDl9Cs` |
| Vercel project root | `web` |
| Vercel CLI/account | `59.13.1` / `cruslee00-6855` |
| Production URL | `https://cre-db.vercel.app` |
| 현재 rollback deployment | `dpl_5xDokCmsUozCt4K31USiDVywHv34` |
| 신규 Supabase ref | `rjalzmmiqhrdmhojbxsk` |
| 최종 dataset version | `cre-20260909T060407Z-5c55a7cb58de` |
| schema version | `1.1.0` |
| source freshness | `2026-09-09T06:04:07Z` |
| 격리 release checkout | `.codex_tmp/cre-release-20260909` |

## 완료된 release source 검증

- canonical/source parity: `211/211`, mismatch `0`.
- source match: `182`.
- 최종 웹 테스트: `77 files / 312 passed / 1 skipped`.
- 격리 release checkout에서 production build, lint, TypeScript check, secret scan, forbidden/conflict scan이 모두 통과했다.
- 데이터·백업·raw·artifact/report/log·env·credential·`.vercel`·`node_modules`·`.next*`는 릴리스 source에서 제외한다.
- source authority는 검토된 manifest와 SHA-256 대조 결과이며, dirty canonical 전체를 무차별 복사하지 않는다.

이 완료 상태는 로컬·격리 checkout 검증이다. GitHub push와 Vercel production 결과를 의미하지 않는다.

## 신규 Supabase 최종 snapshot

### 데이터 범위

현재 dashboard serving 대상은 전체 archive가 아니라 아래 9개 compact table이다.

| 논리 데이터 | 행 수 |
| --- | ---: |
| articles | `2,145` |
| article_details | `2,145` |
| article_search_documents | `2,145` |
| article_dates | `498` |
| article_topics | `1,103` |
| macro_series | `19` |
| macro_monthly | `4,471` |
| permit_monthly | `90,907` |
| market_pulse | `1` |

- 기사 `2,145`건은 현재 dashboard serving 대상이며 전체 raw archive 기사 수가 아니다.
- raw archive/source history, MOLIT raw 거래, permit hot detail, embedding/vector는 업로드하지 않았다.
- market pulse는 현재 dashboard 범위를 로컬에서 사전 계산한 1개 payload다.
- 검색은 문서별 2글자 token `text[]` GIN과 3글자 이상 trigram 후보 색인이다.
- 9개 table의 package↔PostgreSQL 전수 semantic hash, RLS `15/15`, invalid constraint `0`, 승인 subject `3`/미승인 거부가 통과했다.

### 물리 용량

독립 최종 readback의 `pg_database_size`는 `61,549,715 B`다. publisher report의 후속 no-op 측정은 `61,516,947 B`였으며, 같은 version/행/semantic hash에서 생긴 약 32 KiB 물리 배치 변동이다. 운영 보고는 약 `61.5 MB`로 표현하되 측정 시각별 원값을 함께 보존한다.

| schema/object | table bytes | index bytes | total bytes |
| --- | ---: | ---: | ---: |
| `cre_news` | `7,380,992` | `8,855,552` | `20,021,248` |
| `cre_timeseries` | `15,368,192` | `14,516,224` | `29,933,568` |
| `cre_system` | `49,152` | `147,456` | `303,104` |
| `article_search_documents` | `1,802,240` | `2,228,224` | `4,136,960` |

스키마 합계와 전체 DB의 차이는 system catalog, extension, TOAST 등이다. 원본 SQLite 크기와 PostgreSQL 물리 크기, gzip package 크기를 직접 비교해 절감률로 표현하지 않는다.

### 발행 의미

현재 publisher는 9개 table 전체를 하나의 immutable snapshot으로 발행한다. 어느 한 source content라도 달라지면 인허가 90,907행을 포함한 9개 table 전체가 새 version으로 복사된다. no-op은 schema, 9개 table hash/count, lineage, facet 등 전체 identity가 동일할 때만 성립한다.

자동 수집·자동 publish 예약은 연결하지 않았다. 이번 릴리스 이후에도 수동 snapshot publish가 기본이며, 원격 update 실패 시 transaction 내부 pre-activation semantic gate가 active pointer 전환 전에 rollback한다. domain별 증분 version은 후속 최적화다.

## 완료된 로컬 웹 QA

검증 URL은 **`http://127.0.0.1:3015`**이다. `localhost` 표기로 대체하지 않는다.

| 항목 | 결과 |
| --- | --- |
| server | v4, PID `41084` |
| BUILD_ID | `NBLbFsREXkgUMaKUHDMX1` |
| 3개 tab | 통과 |
| smart address/company API | 통과 |
| evidence results | `8` |
| evidence title matches | `8` |
| duplicate blockquotes | `0` |
| mobile collapsed height | `44px` |
| desktop/mobile visual QA | root 실제 확인 완료 |

로컬 warm HTTP 관측값은 news `4.3ms`, macro `11.4ms`, pulse `6.3ms`, permits `3.9ms`다. 이는 production 성능도, OS/DB cache를 비운 cold benchmark도 아니다.

모바일 검증은 responsive web viewport QA다. 이번 릴리스는 web only이며 APK/native app QA 결과가 아니다.

## Production 환경 gate — main push 전에 완료

배포 담당 D가 production 환경의 이름/target을 읽고, 아래 **정확히 8개 승인 key**를 production target에 설정한 뒤 이름/target과 ref 일치를 readback해야 한다. 값은 출력·문서화하지 않는다.

| 승인 key | 요구사항 |
| --- | --- |
| `SUPABASE_URL` | 신규 project URL |
| `SUPABASE_SECRET_KEY` | 신규 server secret |
| `SUPABASE_PROJECT_REF` | `rjalzmmiqhrdmhojbxsk` |
| `DASHBOARD_DATA_PROVIDER` | `supabase` |
| `VWORLD_KEY` | 주소 후보 조회 |
| `DATA_GO_KR_KEY` | 건축물대장 상세 |
| `DART_API_KEY` | 회사·공시 조회 |
| `KRX_API_KEY` | 상장종목 enrichment |

현재 production에 존재하는 `TURSO_AUTH_TOKEN`, `TURSO_DATABASE_URL`, `SUPABASE_DB_URL`, `DASHBOARD_SESSION_SECRET` 4개는 삭제·교체하지 않고 보존한다. 이 4개와 기타 비대상 key를 건드리지 않는다. 승인된 변경은 위 8개 production-only key의 추가/갱신뿐이다.

환경 변경 범위는 root 검토를 마쳤지만, approval reviewer가 실제 secret upload를 허용하지 않아 명시적 사용자 승인을 기다리고 있다. 승인 전에는 외부 환경을 변경하지 않으며, D의 실제 apply 및 readback 보고 전에는 `main`을 push하지 않는다.

## 유일한 production 실행 순서

1. D가 Vercel CLI `59.13.1`, account, project/team/root, GitHub repo/branch, 현재 production alias/deployment를 다시 readback한다.
2. D가 승인된 production env 8개만 적용한다.
3. D가 env 이름·target `production`, 신규 Supabase ref 일치, 기존 4개 보존을 값 노출 없이 readback한다.
4. 격리 release checkout의 최종 diff/commit SHA와 clean release 범위를 확정한다.
5. GitHub `Crus7230/CRE-DB`의 `main`에 push한다.
6. GitHub 연동으로 생성된 Vercel deployment를 식별하고 source commit SHA가 방금 push한 SHA와 같은지 확인한다.
7. deployment가 READY가 되고 `cre-db.vercel.app` alias가 새 deployment를 가리키는지 확인한다.
8. production URL에서 아래 smoke/visual QA를 수행한다.
9. 성공 시 commit SHA, deployment ID/URL/READY 시각, alias, env readback, dataset version/freshness를 기록한다.

금지 사항:

- 로컬 source를 `vercel deploy` 또는 `vercel --prod`로 직접 배포하지 않는다.
- 별도 `--skip-domain` staged production deployment를 만들지 않는다.
- staged deployment를 수동 promote하는 절차를 정상 release 경로로 사용하지 않는다.
- env 전체 삭제/재생성, 기존 session secret 교체, credential 출력, DB 재발행을 하지 않는다.

## Production 검증과 rollback

Production에서 다음을 확인한다.

- 익명 protected API는 `401` 및 `Cache-Control: no-store`.
- 허용 email login 성공, 비허용 email 거부.
- 최신기사·시계열자료·스마트 조회 3개 tab.
- 기사 상세 ID/title 일치, evidence 8개와 title 8개 일치, 중복 blockquote 0.
- address/company smart API.
- manifest와 data RPC의 dataset version이 `cre-20260909T060407Z-5c55a7cb58de`.
- source/cache/auth timing header 및 production 로그.
- desktop/mobile responsive web, collapsed height `44px`, horizontal overflow와 console error 없음.

실패하면 신규 Supabase를 수정하지 않는다. 현재 rollback deployment `dpl_5xDokCmsUozCt4K31USiDVywHv34`를 Vercel control plane에서 복구하고 production alias readback을 확인한다. 이는 로컬 source 직접 재배포가 아니다.

## 아직 완료되지 않은 항목

- [ ] D의 production env 8개 apply/readback
- [ ] 최종 release commit 생성
- [ ] GitHub `main` push
- [ ] GitHub-triggered Vercel deployment READY
- [ ] production alias 전환 readback
- [ ] production API/auth/desktop/mobile QA
- [ ] 최종 deployment·commit·rollback 증적 기록

위 항목을 모두 확인하기 전에는 릴리스를 완료로 보고하지 않는다.
