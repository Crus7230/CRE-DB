# CRE DB 신규 Supabase 전환 · GitHub/Vercel 릴리스 인수인계

> 기준일: 2026-09-10. 이 문서는 GitHub 연동 production 배포 결과와 남은 검증 gate를 기록한다. 생성형 AI/LLM은 범위 밖이며, 스마트 조회와 기사 근거 검색은 고정 API 및 사전 구축 색인을 사용하는 결정론적 조회다.

## 현재 결론

- 신규 Supabase compact snapshot의 적재와 독립 readback, 로컬 웹 QA, 격리 release checkout 검증은 완료됐다.
- production 환경변수는 사용자 승인 후 검토된 8개만 암호화 저장했고, 8/8 exact-value readback과 비대상 환경 엔트리 5개 보존을 확인했다.
- release commit `75f3660fd3567a5bcfde6253d226819296814914`를 GitHub `Crus7230/CRE-DB`의 `main`에 non-force fast-forward push했고, 기존 Vercel GitHub integration이 production deployment `dpl_7zm6YEqTsqRbhUJyigd22RF7Xe7a`를 생성했다.
- 신규 deployment는 READY이며 alias control-plane에서 `cre-db.vercel.app`이 해당 deployment를 가리키는 것을 확인했다.
- 로컬 checkout을 대상으로 `vercel deploy`, `vercel --prod`, `--skip-domain`을 실행하지 않는다. 별도 staged production deployment와 수동 promote 단계도 사용하지 않는다.
- 데이터·시계열·스마트 조회의 production 확인은 통과했지만, 동시 로그인 검증에서 rate-limit consume 단계의 `503`이 1회 발생해 인증 원인은 조사 중이다. 후속 단독 UI 로그인·조회는 성공했고, 전체 production QA 완료로는 아직 표시하지 않는다.
- rollback 대상 `dpl_5xDokCmsUozCt4K31USiDVywHv34`는 READY 상태로 보존돼 있다.

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
| 기능 QA 기준 commit | `75f3660fd3567a5bcfde6253d226819296814914` |
| 기능 QA 기준 deployment | `dpl_7zm6YEqTsqRbhUJyigd22RF7Xe7a` / `cre-ly7aod9sj-grus-projects-dc1b5fb9.vercel.app` |
| deployment READY | `2026-09-10T09:44:05.815+09:00` |
| 현재 rollback deployment | `dpl_5xDokCmsUozCt4K31USiDVywHv34` |
| 신규 Supabase ref | `rjalzmmiqhrdmhojbxsk` |
| 최종 dataset version | `cre-20260909T060407Z-5c55a7cb58de` |
| schema version | `1.1.0` |
| source freshness | `2026-09-09T06:04:07Z` |
| 격리 release checkout | `.codex_tmp/cre-release-20260909` |

## 완료된 release source 검증

- canonical/source parity: `213/213`, mismatch `0`.
- source match: `182`.
- 최종 웹 테스트: test files `78 passed / 1 skipped`, tests `315 passed / 1 skipped`.
- 격리 release checkout에서 production build(`BUILD_ID=n9IqUAwm21rICcDoAymMR`), lint, TypeScript check, secret scan, forbidden/conflict scan이 모두 통과했다.
- 후속 후보는 로그인 실패 로그를 고정 allowlist의 `stage/errorClass/errorCode/upstreamStatus/timeoutMs`로만 구조화하며 메시지·stack·body·header·URL·env·email·key·cookie는 기록하지 않는다. 인증 응답과 rate-limit/allowlist 동작은 변경하지 않는다.
- 데이터·백업·raw·artifact/report/log·env·credential·`.vercel`·`node_modules`·`.next*`는 릴리스 source에서 제외한다.
- source authority는 검토된 manifest와 SHA-256 대조 결과이며, dirty canonical 전체를 무차별 복사하지 않는다.

위 commit/deployment는 기능 QA 기준점이다. 후속 telemetry와 이 문서를 함께 담는 commit은 자기 SHA/deployment ID를 문서 안에 다시 적어 재배포를 반복하지 않으며, 최종 식별자는 Git `main` log와 Vercel alias readback을 기준으로 한다. production 기능 검증의 완료 여부는 아래의 별도 현황을 따른다.

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

## Production 환경 적용 결과

production 환경의 이름/target을 먼저 읽고, 아래 **정확히 8개 승인 key**만 production target에 설정했다. 값은 출력·문서화하지 않았으며 8개 모두 저장값과 source 값의 ordinal exact readback을 통과했다.

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

변경 전 환경 엔트리는 5개, 변경 후는 13개다. 기존 `TURSO_AUTH_TOKEN`, `TURSO_DATABASE_URL`, `SUPABASE_DB_URL`, `DASHBOARD_SESSION_SECRET` 4개 이름에 해당하는 비대상 엔트리 5개의 identity는 모두 그대로 보존됐다. 환경 적용 자체는 deployment를 만들지 않았고, 이후 별도 GitHub `main` push가 배포를 시작했다.

## 실행된 production 경로

1. Vercel CLI `59.13.1`, account, project/team/root, GitHub repo/branch, 기존 production deployment를 다시 readback했다.
2. 승인된 production env 8개만 적용하고 exact readback 8/8 및 비대상 5개 보존을 확인했다.
3. clean release commit `75f3660fd3567a5bcfde6253d226819296814914`와 원격 기준 `eef5faf4a773f3b6080e852380ba6cfcac05c5db`를 확인했다.
4. GitHub `Crus7230/CRE-DB`의 `main`에 non-force fast-forward push하고 원격 SHA를 다시 읽었다.
5. GitHub 연동 deployment `dpl_7zm6YEqTsqRbhUJyigd22RF7Xe7a`의 source가 `git`, branch가 `main`, commit SHA가 위 release commit과 동일함을 확인했다.
6. deployment READY와 alias control-plane의 `cre-db.vercel.app` 연결을 확인했다.
7. production smoke/visual QA를 수행했고, 아래의 인증 1회 오류와 미실행 항목 때문에 전체 완료 판정은 보류했다.

금지 사항:

- 로컬 source를 `vercel deploy` 또는 `vercel --prod`로 직접 배포하지 않는다.
- 별도 `--skip-domain` staged production deployment를 만들지 않는다.
- staged deployment를 수동 promote하는 절차를 정상 release 경로로 사용하지 않는다.
- env 전체 삭제/재생성, 기존 session secret 교체, credential 출력, DB 재발행을 하지 않는다.

## Production 검증 현황과 rollback

확인 완료:

- 허용 email의 desktop 로그인과 후속 단독 UI 로그인·조회 성공.
- 최신기사 desktop `7`, mobile `7` 표시.
- 시계열자료 macro series `13`과 거래·인허가 chart 표시.
- address/company smart lookup 모두 `passed=true`, error `0`.
- mobile horizontal overflow `0`.
- production 로그의 `5xx`는 `2026-09-10T09:44:50.458+09:00` 동시 로그인 요청 1건뿐이며, `09:47 KST` 이후 1회 추가 조회에서는 `5xx=0`이었다.

열린 항목과 경계:

- 위 `POST /api/auth/login`은 `503`과 `Dashboard login rate limit failed`를 기록했다. `dashboard_consume_login_attempts`를 호출하는 rate-limit consume 단계이며 allowlist lookup 실패나 정상적인 `429` 차단은 아니다.
- 후속 단독 로그인은 성공했다. Supabase read-only 통계에서 PostgreSQL이 감지한 deadlock 기록은 `0`이었으나, 이것만으로 lock wait나 애플리케이션 timeout을 배제할 수 없으며 직접 원인은 아직 확정하지 않았다.
- production 비허용 email 거부와 반복 인증 probe는 아직 실행하지 않았다.
- 전체 visual harness는 mobile hydration 시점의 disabled click에서 중단됐으므로 전체 통과로 표시하지 않는다. 위 mobile row 수와 overflow는 실제 확인 결과다.
- 관련 local auth test `16`개는 통과했지만 production auth 검증을 대신하지 않는다.
- 신규 Supabase 자동 수집·자동 snapshot publish 예약은 연결하지 않았다. 현재 `2026-09-09` snapshot은 수동 게시 상태다.

현재는 핵심 data와 smart lookup이 정상이고 후속 단독 로그인이 성공했으므로 자동 rollback하지 않았다. 인증 오류가 재현되거나 QA gate가 실패하면 신규 Supabase를 수정하지 않고 rollback deployment `dpl_5xDokCmsUozCt4K31USiDVywHv34`를 Vercel control plane에서 복구한 뒤 production alias를 readback한다. 이는 로컬 source 직접 재배포가 아니다.

## 아직 완료되지 않은 항목

- [x] production env 8개 apply/exact readback 및 비대상 5개 보존
- [x] release commit `75f3660fd3567a5bcfde6253d226819296814914`
- [x] GitHub `main` non-force push와 원격 SHA readback
- [x] GitHub-triggered Vercel deployment READY
- [x] production alias control-plane readback
- [x] deployment·commit·rollback 증적 기록
- [ ] 동시 로그인 rate-limit consume `503` 원인 확정 및 필요한 최소 조치 검토
- [ ] production 비허용 email/반복 인증 검증
- [ ] 중단된 전체 production visual harness 재완료
- [ ] manifest/data RPC의 dataset version과 freshness production readback
- [ ] 최종 production QA 판정

위 항목을 모두 확인하기 전에는 릴리스를 완료로 보고하지 않는다.
