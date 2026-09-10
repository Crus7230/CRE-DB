# CRE DB Supabase/GitHub/Vercel release checklist — 2026-09-09

## 고정 release 경로

- [x] GitHub source: `Crus7230/CRE-DB`
- [x] production branch: `main`
- [x] Vercel project: `cre-db` / `prj_1DTajzRAaw2IbqffiAwN2aZWC5Bb`
- [x] Vercel team: `team_ZraFevjGRitnuj6w5suDl9Cs`
- [x] Vercel root: `web`
- [x] Vercel CLI/account: `59.13.1` / `cruslee00-6855`
- [x] GitHub GCM account: `Crus7230`; push dry-run 통과
- [x] current production rollback: `dpl_5xDokCmsUozCt4K31USiDVywHv34`, READY
- [x] production URL: `https://cre-db.vercel.app`
- [x] final commit `75f3660fd3567a5bcfde6253d226819296814914`을 `main`에 non-force push하여 기존 GitHub integration으로 Vercel production 배포

정상 경로는 **production env readback → GitHub `main` push → 기존 Vercel integration 자동 배포**다. 로컬 source 직접 `vercel deploy`, `--prod --skip-domain`, 별도 staged production deployment, 정상 경로의 수동 promote는 금지한다.

## 현재 완료 증적

- [x] release source `75f3660fd3567a5bcfde6253d226819296814914` 확정 및 push 완료
- [x] canonical/source parity `213/213`
- [x] mismatch `0`
- [x] source match `182`
- [x] web tests: test files `78 passed / 1 skipped`, tests `315 passed / 1 skipped`
- [x] 격리 release checkout production build (`BUILD_ID=n9IqUAwm21rICcDoAymMR`)
- [x] lint
- [x] TypeScript check
- [x] secret/forbidden/conflict scan
- [x] database/backup/raw/artifact/env/credential/build cache 제외

## Supabase gate

- [x] project ref `rjalzmmiqhrdmhojbxsk`
- [x] dataset `cre-20260909T060407Z-5c55a7cb58de`
- [x] schema `1.1.0`
- [x] source freshness `2026-09-09T06:04:07Z`
- [x] current dashboard serving articles `2,145`; 전체 raw archive가 아님
- [x] compact table 9개 전수 semantic parity
- [x] RLS `15/15`
- [x] invalid constraints `0`
- [x] 승인 subject `3`, unknown 거부
- [x] 독립 `pg_database_size=61,549,715 B`
- [x] publisher report `pg_database_size=61,516,947 B`; 동일 snapshot의 물리 변동으로 설명
- [x] `cre_news=20,021,248 B`
- [x] `cre_timeseries=29,933,568 B`
- [x] `cre_system=303,104 B`
- [x] `article_search_documents=4,136,960 B`

운영 의미:

- [x] 자동 snapshot publisher/scheduler를 연결하지 않음
- [x] 어느 한 serving content라도 달라지면 현재 publisher는 9개 table 전체를 새 version으로 적재
- [x] no-op은 schema/table hash/count/lineage/facet을 포함한 전체 identity가 동일할 때만 성립
- [x] update 실패 시 pre-activation semantic gate와 transaction rollback으로 이전 active 유지
- [x] 이번 release에서 DB 재발행 불필요

## 로컬 web QA

검증 URL은 `http://127.0.0.1:3015`이다. `localhost`로 기록하지 않는다.

- [x] v4 server PID `41084`
- [x] BUILD_ID `NBLbFsREXkgUMaKUHDMX1`
- [x] 최신기사·시계열자료·스마트 조회 3개 tab
- [x] address/company smart API
- [x] desktop/mobile responsive web visual QA
- [x] evidence results `8`
- [x] title matches `8`
- [x] duplicate blockquotes `0`
- [x] mobile collapsed height `44px`
- [x] warm news `4.3ms`
- [x] warm macro `11.4ms`
- [x] warm pulse `6.3ms`
- [x] warm permits `3.9ms`
- [x] web-only 범위 확인; mobile은 responsive viewport QA이며 APK/native QA가 아님

로컬 warm 수치는 production 또는 cold DB benchmark가 아니다.

## Production env 8개 — push 전 필수

D가 아래 정확히 8개만 production target에 추가/갱신하고, 값은 출력하지 않는다.

- [x] `SUPABASE_URL`
- [x] `SUPABASE_SECRET_KEY`
- [x] `SUPABASE_PROJECT_REF=rjalzmmiqhrdmhojbxsk`
- [x] `DASHBOARD_DATA_PROVIDER=supabase`
- [x] `VWORLD_KEY`
- [x] `DATA_GO_KR_KEY`
- [x] `DART_API_KEY`
- [x] `KRX_API_KEY`

기존 production 4개는 보존한다.

- [x] 보존 대상 확인: `TURSO_AUTH_TOKEN`
- [x] 보존 대상 확인: `TURSO_DATABASE_URL`
- [x] 보존 대상 확인: `SUPABASE_DB_URL`
- [x] 보존 대상 확인: `DASHBOARD_SESSION_SECRET`
- [x] 신규 8개를 production-only로 적용하고 exact-value readback `8/8`
- [x] 신규 URL/ref 일치와 provider=`supabase`를 값 노출 없이 검증
- [x] 환경 엔트리 `5 → 13`; 기존 4개 이름에 해당하는 비대상 identity 5개가 삭제·변경되지 않았음을 확인
- [x] 환경 적용 자체가 deployment를 만들지 않았음을 확인

## Commit·push gate

- [x] 지정 source manifest에 telemetry 신규 파일 2개 포함, canonical/source parity `213/213`, mismatch `0`
- [x] `git diff --check`
- [x] 개인·전역 env의 credential 값 17개와 outgoing blob 105개 대조: secret `0`, forbidden `0`
- [x] final commit SHA `75f3660fd3567a5bcfde6253d226819296814914`
- [x] clean release checkout과 push refspec target `main` 확인
- [x] `Crus7230/CRE-DB main` non-force fast-forward push
- [x] 원격 `main` SHA가 local final commit과 동일한지 readback

## GitHub-triggered Vercel gate

- [x] push로 생성된 Vercel deployment `dpl_7zm6YEqTsqRbhUJyigd22RF7Xe7a` 식별
- [x] deployment source=`git`, ref=`main`, commit SHA가 push SHA와 동일
- [x] project/team/root가 고정 대상과 동일
- [x] deployment READY (`2026-09-10T09:44:05.815+09:00`)
- [x] alias control-plane에서 `cre-db.vercel.app`이 신규 deployment를 가리킴
- [x] 기존 rollback deployment `dpl_5xDokCmsUozCt4K31USiDVywHv34` READY 보존

직접 Vercel source deploy 명령을 실행하지 않는다.

## Production API/auth/visual QA

- [ ] anonymous protected API `401`
- [ ] `Cache-Control: no-store`
- [x] 허용 email login 성공; 후속 단독 UI 로그인·조회도 성공
- [ ] 비허용 email 거부
- [x] 최신기사 tab: desktop `7`, mobile `7`
- [x] 시계열자료 tab: macro series `13`, 거래·인허가 chart 표시
- [x] 스마트 조회 tab: address/company `passed=true`, error `0`
- [ ] article detail ID/title 일치
- [ ] evidence results/title matches `8/8`
- [ ] duplicate blockquotes `0`
- [x] address smart API
- [x] company smart API
- [ ] manifest/data RPC version `cre-20260909T060407Z-5c55a7cb58de`
- [ ] cache/source/auth timing headers
- [x] recent production error log: 동시 로그인 1건이 `503` / `Dashboard login rate limit failed`; `09:47 KST` 이후 1회 추가 조회는 `5xx=0`
- [ ] desktop responsive web
- [ ] mobile responsive web 및 collapsed `44px`; 전체 harness는 hydration 시점 disabled click으로 중단
- [x] 확인한 mobile 화면의 horizontal overflow `0`; 전체 console/harness 완료는 미확정

인증 경계:

- 동시 로그인 `503`은 `dashboard_consume_login_attempts`의 rate-limit consume 단계다. allowlist lookup 실패나 정상적인 `429` 차단이 아니다.
- 후속 단독 로그인·조회는 성공했다. Supabase read-only 통계에서 PostgreSQL이 감지한 deadlock 기록은 `0`이지만, 이것만으로 lock wait나 애플리케이션 timeout을 배제할 수 없으며 직접 원인은 미확정이다.
- production 비허용 email과 반복 인증 probe는 아직 실행하지 않았다.
- 관련 local auth test `16`개는 통과했지만 production 검증을 대신하지 않는다.
- 신규 Supabase에는 자동 수집·자동 snapshot publish 예약이 없고 `2026-09-09` snapshot을 수동 게시한 상태다.

후속 telemetry 후보는 고정 allowlist의 `stage/errorClass/errorCode/upstreamStatus/timeoutMs`만 기록하고 메시지·stack·body·header·URL·env·email·key·cookie를 기록하지 않는다. 인증 응답과 rate-limit/allowlist 동작은 변경하지 않는다. 이 문서에 적힌 `75f3660`/`dpl_7zm...`은 기능 QA 기준점이며, telemetry+문서 commit의 최종 SHA/deployment ID는 자기 참조 재배포를 피하기 위해 Git `main` log와 Vercel alias readback으로 확인한다.

## 완료 기록

- [x] GitHub final commit SHA `75f3660fd3567a5bcfde6253d226819296814914`
- [x] push 완료 `2026-09-10 09:43 KST`
- [x] Vercel deployment `dpl_7zm6YEqTsqRbhUJyigd22RF7Xe7a` / `cre-ly7aod9sj-grus-projects-dc1b5fb9.vercel.app`
- [x] READY `2026-09-10T09:44:05.815+09:00`
- [x] production alias readback
- [x] env 8개 exact readback 및 비대상 identity 5개 보존 증적
- [ ] Supabase dataset/freshness readback
- [ ] production QA 결과
- [x] rollback deployment `dpl_5xDokCmsUozCt4K31USiDVywHv34` READY 기록

실패 시 DB를 변경하거나 로컬 source를 재배포하지 않는다. Vercel control plane에서 `dpl_5xDokCmsUozCt4K31USiDVywHv34`를 복구하고 production alias를 readback한다.
