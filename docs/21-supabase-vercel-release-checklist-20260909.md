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
- [ ] final commit을 `main`에 push하여 기존 GitHub integration으로 Vercel production 배포

정상 경로는 **production env readback → GitHub `main` push → 기존 Vercel integration 자동 배포**다. 로컬 source 직접 `vercel deploy`, `--prod --skip-domain`, 별도 staged production deployment, 정상 경로의 수동 promote는 금지한다.

## 현재 완료 증적

- [x] release source `8d6d8d3` 기준 준비; final commit/push는 미완료
- [x] canonical/source parity `211/211`
- [x] mismatch `0`
- [x] source match `182`
- [x] web tests `77 files / 312 passed / 1 skipped`
- [x] 격리 release checkout production build
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

- [ ] `SUPABASE_URL`
- [ ] `SUPABASE_SECRET_KEY`
- [ ] `SUPABASE_PROJECT_REF=rjalzmmiqhrdmhojbxsk`
- [ ] `DASHBOARD_DATA_PROVIDER=supabase`
- [ ] `VWORLD_KEY`
- [ ] `DATA_GO_KR_KEY`
- [ ] `DART_API_KEY`
- [ ] `KRX_API_KEY`

기존 production 4개는 보존한다.

- [x] 보존 대상 확인: `TURSO_AUTH_TOKEN`
- [x] 보존 대상 확인: `TURSO_DATABASE_URL`
- [x] 보존 대상 확인: `SUPABASE_DB_URL`
- [x] 보존 대상 확인: `DASHBOARD_SESSION_SECRET`
- [ ] env apply 후 기존 4개와 신규 8개의 name/target 존재를 readback
- [ ] 신규 URL/ref 일치와 provider=`supabase`를 값 노출 없이 검증
- [ ] 비대상 production env가 삭제·변경되지 않았음을 확인

변경 범위의 root 검토는 완료됐지만 approval reviewer가 실제 secret upload를 허용하지 않아 명시적 사용자 승인을 기다리고 있다. 승인 전에는 외부 환경을 변경하지 않으며, 실제 D apply/readback 전에는 push하지 않는다.

## Commit·push gate

- [ ] 지정 source manifest만 final diff에 포함
- [ ] `git diff --check`
- [ ] secret/forbidden/conflict scan 재확인
- [ ] final commit SHA 기록
- [ ] `git status`와 push 대상 branch가 `main`인지 확인
- [ ] `Crus7230/CRE-DB main` push
- [ ] 원격 `main` SHA가 local final commit과 동일한지 readback

## GitHub-triggered Vercel gate

- [ ] push로 생성된 Vercel deployment 식별
- [ ] deployment source commit SHA가 push SHA와 동일
- [ ] project/team/root가 고정 대상과 동일
- [ ] deployment READY
- [ ] `cre-db.vercel.app` alias가 새 deployment를 가리킴
- [ ] 기존 rollback deployment `dpl_5xDokCmsUozCt4K31USiDVywHv34` 보존

직접 Vercel source deploy 명령을 실행하지 않는다.

## Production API/auth/visual QA

- [ ] anonymous protected API `401`
- [ ] `Cache-Control: no-store`
- [ ] 허용 email login 성공
- [ ] 비허용 email 거부
- [ ] 최신기사 tab
- [ ] 시계열자료 tab
- [ ] 스마트 조회 tab
- [ ] article detail ID/title 일치
- [ ] evidence results/title matches `8/8`
- [ ] duplicate blockquotes `0`
- [ ] address smart API
- [ ] company smart API
- [ ] manifest/data RPC version `cre-20260909T060407Z-5c55a7cb58de`
- [ ] cache/source/auth timing headers
- [ ] recent production error log
- [ ] desktop responsive web
- [ ] mobile responsive web 및 collapsed `44px`
- [ ] horizontal overflow/console error 없음

## 완료 기록

- [ ] GitHub final commit SHA
- [ ] push 완료 시각
- [ ] Vercel deployment ID/URL
- [ ] READY 시각
- [ ] production alias readback
- [ ] env 8개 readback 증적
- [ ] Supabase dataset/freshness readback
- [ ] production QA 결과
- [ ] rollback deployment 기록

실패 시 DB를 변경하거나 로컬 source를 재배포하지 않는다. Vercel control plane에서 `dpl_5xDokCmsUozCt4K31USiDVywHv34`를 복구하고 production alias를 readback한다.
