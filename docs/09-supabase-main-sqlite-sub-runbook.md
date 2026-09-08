# Local full archive / Supabase active serving 운영계약

## 1. 역할

| 계층 | 위치 | 역할 | 평시 write |
|---|---|---|---|
| Full archive | `data/market.db` | 전체 이력·원문·비활성 상세·lineage의 로컬 권위 저장소 | 검증된 merge만 허용 |
| Immutable snapshot | `backups/archive-snapshots/*.db` | retire 전 복원 기준, SHA-256 고정본 | 금지 |
| Active serving | Supabase `market_intelligence` | 웹앱용 active 상세와 compact historical index | 수집·review·serving write 허용 |
| Compact history | `archived_serving_index` | 비활성 항목의 검색용 최소 metadata와 archive locator | archive staging에서만 허용 |

Supabase를 전체 이력 원장으로 간주하지 않는다. 비활성 상세를 Supabase에서 retire하더라도 로컬 full archive와 immutable snapshot에는 남아야 한다.

## 2. Active 정책

기간 cutoff는 사용하지 않는다. 상태를 기준으로 한다.

- 문서: `CRE_REVIEW` 및 active 관계 closure
- 이벤트: `ACTIVE`
- 기관자금 mandate: `DISCOVERED`, `TRACKING`, `REVIEW`, `OPEN`, `ACTIVE`, `ALLOCATED`, `SELECTED`
- 매각절차: `DISCOVERED`, `TRACKING`, `REVIEW`, `OPEN`, `ACTIVE`, `MARKETING`, `BIDDING`, `PREFERRED_BIDDER`, `DUE_DILIGENCE`, `CONTRACTED`
- 수집: active job별 최신 run과 진행 중 run
- review: `PENDING`, `IN_PROGRESS`

canonical dependency 또는 열린 review가 있는 상세 row는 leaf retire 대상으로 보지 않는다.

## 3. 자격증명

- 중앙 파일: `C:\10137_WorkSpace\env\.env.supabase.local`
- 필수 변수: `SUPABASE_DB_URL`, `SUPABASE_DB_SCHEMA`
- secret을 프로젝트·artifact·로그·Git에 복사하지 않는다.

## 4. Full archive 갱신

Supabase active row를 기존 full archive에 **삭제 없이 upsert**한다.

```bash
uv run --with 'psycopg[binary]' python scripts/merge_supabase_active_into_full_archive.py --activate
```

검증 조건:

- application table coverage 일치
- 모든 table에 PK 존재
- 기존 table row count 감소 없음
- `PRAGMA integrity_check = ok`
- `PRAGMA foreign_key_check = 0`
- trigger와 FTS 재구성
- 활성화 직전 기존 `market.db` backup 생성

`refresh_sqlite_sub_from_supabase.py`는 전환 전 legacy 도구다. current validated archive snapshot이 존재하면 hard guard로 중단한다. 이 도구를 강제로 재사용하면 archive-only row가 소실될 수 있다.

## 5. Retire 절차

1. SQLite backup API로 full archive 후보 생성
2. table coverage·row count·integrity·FK 검증
3. SHA-256 계산
4. `archive_snapshots`에 `VALIDATED` current snapshot 등록
5. compact index dry-run 및 row 수 검토
6. `archived_serving_index` staging
7. search/index가 archive row를 읽고 live detail 호출을 차단하는지 실제 PostgreSQL smoke test
8. in-flight collector가 없는지 확인
9. 명시 승인 후 transaction retire
10. read-back, `VACUUM FULL ANALYZE`, API regression test

## 6. 검색 계약

- compact row는 current + validated snapshot에 연결돼야 한다.
- 같은 `record_kind/record_id`가 index에 있으면 compact index가 검색 결과를 승계한다.
- `MACRO_OBSERVATION`은 현재 통합검색 계약에서 제외한다.
- archived 결과는 `ARCHIVED_LOCAL`이며 live typed detail API를 호출하지 않는다.
- drawer에는 원래 상태, 출처, 날짜, 요약, archive locator, snapshot SHA-256을 표시한다.

## 7. 복원

- 기준 snapshot ID와 SHA-256을 먼저 대조한다.
- snapshot을 working copy로 복원하고 integrity/FK를 재검사한다.
- archived locator의 table/PK가 실제 row를 가리키는지 확인한다.
- 필요한 상세만 Supabase active schema에 재수화하고 전체 archive를 덮어쓰지 않는다.

## 8. 금지사항

- Supabase active subset으로 `market.db` 전체 교체
- current validated snapshot 없이 hard delete
- 기간만으로 active 여부 판정
- canonical dependency·열린 review가 있는 row의 leaf 삭제
- compact metadata를 기존 상세 계약인 것처럼 반환
- checksum·row count 검증 없이 archive 완료 선언

## 9. Analytics 3.5.0 적용

대상 migration은 `3.4.0_keyword_analytics.sql` → `3.4.1_insight_signals.sql` → `3.5.0_model_interpretations.sql` 순서다. migration과 Local 90일 serving sync는 하나의 PostgreSQL transaction에서 실행한다.

승인 전 rollback rehearsal:

```bash
uv run --with 'psycopg[binary]' python scripts/apply_analytics_v350_supabase.py \
  --report artifacts/analytics-v350-supabase-rehearsal.json
```

통과 조건:

- transaction 내부 schema `3.5.0`
- rollback 후 persisted schema가 적용 전 version과 동일
- staged row와 transaction 내부 target row 수 일치
- credential·connection string을 report/log에 기록하지 않음
- Local authority는 read-only 유지

**사용자 명시 승인 후에만** 적용한다.

```bash
uv run --with 'psycopg[binary]' python scripts/apply_analytics_v350_supabase.py \
  --apply --report artifacts/analytics-v350-supabase-apply.json
```

적용 후 schema version·row count·index·Web authenticated API를 read-back한다. 그 다음에만 Vercel production을 배포하고 desktop/mobile smoke를 수행한다. 일일 Supabase sync marker는 production smoke 완료 후 별도 활성화한다.

## 10. Analytics rollback

migration은 additive이므로 Web 장애 시 우선 Vercel을 직전 deployment로 rollback하고 Supabase sync marker를 비활성화한다. 기존 3.3.0 Web은 신규 analytics table을 참조하지 않아 3.5.0 schema와 공존할 수 있다.

- apply transaction 실패: script가 전체 rollback하므로 별도 schema 조작 금지
- apply 성공 후 Web 장애: Vercel만 rollback하고 3.5.0 table은 보존
- analytics 데이터 오류: sync 중단 후 Local backup·rehearsal report와 비교; raw/canonical table은 수정하지 않음
- 신규 table drop 또는 schema version downgrade: 별도 snapshot과 사용자 승인 없이는 금지
- 재적용: Local authority 검증 후 `--sync-only --apply` 사용

## 11. 2026-08-31 운영 연결 정리

이 절은 기존 스키마 3.5.0의 **일상 데이터 갱신** 계약이다. 신규 schema migration이나 Web/APK 배포를 수행하지 않는다.

### 실제 실행 경로

- 기사 수집: 기존 Hermes 예약(09:15·15:15·21:15 KST)을 유지한다.
- 설치 위치의 `daily_cre_articles.py`는 `operations/hermes/daily_cre_articles_entrypoint.py`와 같은 작은 진입 스크립트다. 실제 로직은 저장소의 `operations/hermes/daily_cre_articles.py`에서만 관리한다. 변경 전 설치본은 `daily_cre_articles.pre-canonical-20260831.py.bak`으로 보존했다.
- 기사 처리 순서: 수집 → 본문 보강 → CRE 범위판정·검토용 분류. 본문 일부 추출 실패가 분류를 막지 않으며 최종 로그에는 `PARTIAL`과 실패 건수를 남긴다. 수집/분류 프로세스 실패는 nonzero 종료한다.
- 분석: 기존 Windows `\CRE DB\Daily Analytics Refresh`(매일 06:30 KST)의 VBS·CMD 경로를 유지한다. CMD는 `uv`의 psycopg 실행환경으로 `run_market_refresh_pipeline.py --apply --allow-live-db --sync-if-enabled`를 실행한다.

### 분석 파이프라인

1. 기존 `market.db.analytics.lock`을 전체 단계 동안 보유한다.
2. Supabase의 읽기 전용 Repeatable Read 스냅샷을 기존 전체이력의 별도 후보 DB에 upsert한다. archive-only 행과 로컬 분석 10개 테이블은 보존한다.
3. 양쪽 스키마 3.5.0, 테이블 구성, 원문 행 수, 수집 시점을 검증한다. RSS 자료가 36시간보다 오래됐거나 후보가 원본 스냅샷보다 뒤처지면 중단한다.
4. 최신 후보에서 키워드·근거 신호를 계산한다. KST 실행일 기준 90일 창을 사용하며 기존 키워드 알고리즘의 UTC 일별 bucket 의미는 유지한다.
5. SQLite integrity/FK 및 WAL checkpoint를 확인하고, PostgreSQL 전송을 먼저 rollback rehearsal한다.
6. 교체 전 원본을 백업하고 검증된 후보를 활성화한다.
7. `--sync-only`로 분석 테이블만 전송한다. 보안/스키마 DDL은 실행하지 않는다. PostgreSQL transaction advisory lock, 대상 PK·기간별 건수·근거 연결 검증을 거쳐 commit하고 최신 분석 실행기록을 다시 읽는다.

사전 검증(운영 DB commit·원본 교체 없음):

```powershell
uv run --with 'psycopg[binary]' python scripts/run_market_refresh_pipeline.py --sync --report artifacts/market-refresh-rehearsal.json
```

승인된 일회성 갱신:

```powershell
uv run --with 'psycopg[binary]' python scripts/run_market_refresh_pipeline.py --apply --allow-live-db --sync --report artifacts/market-refresh-apply.json
```

운영 API 확인 후 `data/.supabase-analytics-sync-enabled`로 일일 전송을 활성화한다. 이 파일이 없으면 `LOCAL_ONLY_SYNC_DISABLED`로 기록하며 예약 실행은 종료코드 78을 반환한다. 로컬 분석만 성공한 상태를 전체 갱신 성공으로 표시하지 않는다.

### 결과와 복구

- 단계별 실행 로그: `logs/market-refresh-pipeline.jsonl`
- 예약 실행 최신 보고서: `artifacts/market-refresh-latest.json`
- `COMPLETED`: 최신자료 병합·분석·전송 검증까지 완료
- `REHEARSED`: 별도 후보의 검증만 완료, 운영 반영 없음
- `FAILED`: 실패 단계·예외 종류를 기록. 연결문자열과 비밀번호는 기록하지 않는다.
- `ALREADY_RUNNING` / 75: 중복 실행을 차단한 정상 보류
- `LOCAL_ONLY_SYNC_DISABLED` / 78: 로컬 갱신만 완료, Supabase 전송 비활성

교체 전 실패하면 원본 DB는 그대로 유지된다. 활성화 후 전송 실패 시 최신 로컬 DB와 이전 Supabase 분석 결과를 보존하며 다음 실행에서 전송을 다시 시도한다. 실패·리허설 후보와 활성화 전 백업은 자동 삭제하지 않는다. 복구 시 해당 실행 보고서의 `activation.backup` 경로를 먼저 확인한다.

주의: 신호 0건 자체는 실패가 아니다. 최신 실행시각·입력 문서 수·전송 검증 결과를 함께 보고, 근거 다양성 등 기존 신호 생성 조건을 임의로 완화하지 않는다. 미검토 문서를 확정 사건으로 자동 승격하지 않는다.
