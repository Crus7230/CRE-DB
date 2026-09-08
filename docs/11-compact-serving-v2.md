# Compact Serving v2 → Turso

## 결정

- `data/market.db`는 raw payload·원문·revision·snapshot membership·분류 이력·provenance를 보존하는 권위 archive다.
- Turso에는 포털 조회에 필요한 관계와 projection만 담은 `data/market-serving-v2.candidate.db`를 게시한다.
- Supabase/PostgreSQL은 신규 serving destination으로 사용하지 않는다.
- 건축 인허가 raw/history 8개 테이블은 원격에 복제하지 않는다. 전 기간 월별 projection과 snapshot 기준 최근 60개월 상세 projection만 게시한다.
- keyword daily serving은 최신 완료 algorithm의 최근 30일만 게시한다.
- local archive와 candidate는 삭제하거나 원격 전송 중 덮어쓰지 않는다.
- publisher는 원격 table row count가 local과 일치하면 skip하고, 0행이면 적재하며, 부분 적재 mismatch이면 fail-closed한다.

## Local candidate 실측

- source: `data/market.db`
- source bytes: 1,333,522,432
- candidate: `data/market-serving-v2.candidate.db`
- candidate bytes: 393,306,112
- 감소: 940,216,320 bytes, 약 70.5%
- table: 138개
- rows: 585,411행
- 인허가 월별 projection: 94,633행
- 인허가 hot detail: 40,927행
- hot cutoff: 2021-10-01
- keyword observations: 115,419 → 26,572행
- keyword cooccurrences: 257,105 → 69,340행
- keyword serving: 2026-08-06~2026-09-04
- `PRAGMA integrity_check`: `ok`
- FK 위반: 0

최근 60개월 anchor는 레코드의 미래 예정일 최대값이 아니라 `building_permit_snapshots.source_as_of_date`다. 초기 rehearsal에서 미래 예정일 `8009-xx-xx`가 cutoff anchor가 되어 상세가 1행만 남는 오류를 발견했고 snapshot source-as-of 우선 규칙과 회귀 테스트로 수정했다.

## Build

```bash
python scripts/build_compact_serving_v2.py \
  --source data/market.db \
  --output data/market-serving-v2.candidate.db \
  --keyword-days 30 \
  --report artifacts/compact-serving-v2-turso.json
```

## Turso publication

Credential은 repository 밖의 `C:\10137_WorkSpace\env\.env.personal.txt`에서만 읽는다. URL·token은 로그·report·Git에 기록하지 않는다.

기본 publisher:

```bash
uv run --with libsql --with libsql-client \
  python scripts/publish_sqlite_to_turso_http.py \
  --source data/market-serving-v2.candidate.db \
  --env-file 'C:/10137_WorkSpace/env/.env.personal.txt' \
  --report artifacts/turso-migration-20260907.json \
  --batch-rows 500
```

운영 원칙:

1. source `integrity_check`와 `foreign_key_check` 통과
2. FK dependency graph의 부모→자식 순서로 HTTP batch 적재
3. 완성 table은 row-count 검증 후 skip
4. 0행 table만 insert
5. non-zero partial mismatch이면 자동 중단하고 수동 대사
6. data 적재 후 index·trigger·view additive 생성
7. table count·table별 row count·전체 row count를 분할 query로 검증
8. remote `integrity_check`와 `foreign_key_check` 통과
9. 핵심 최신일·projection aggregate를 별도 대사

embedded replica publisher `scripts/publish_sqlite_to_turso.py`는 fixture·복구 경로로 남기되 대량 운영 게시의 기본은 HTTP batch publisher다.

## 2026-09-07 publication 결과

- remote table: 138개
- remote rows: 585,411행
- local/remote table별 row count mismatch: 0
- remote integrity: `ok`
- remote FK 위반: 0
- document versions: 20,528행, 최신 2026-09-04
- KRX snapshot: 2026-09-03
- permit monthly: 94,633행
- permit hot detail: 40,927행
- keyword observations: 26,572행, 2026-08-06~2026-09-04
- financial macro serving: 4,467행

감사 산출물:

- `artifacts/compact-serving-v2-turso.json`
- `artifacts/turso-migration-20260907.json`
- `artifacts/turso-serving-parity-20260907.json`

## 인증 schema

Turso는 PostgreSQL schema namespace를 사용하지 않는다. 다음 unqualified table을 additive migration으로 생성한다.

- `dashboard_access_allowlist`
- `dashboard_login_rate_limits`

Migration:

```text
db/turso/migrations/001_dashboard_security.sql
```

시장 archive/candidate에는 승인 이메일 PII를 포함하지 않는다. 보안 table은 Turso에 별도 운영 데이터로 유지한다.

## 웹 read path 전환

SQLite 파일 게시만으로 전환이 끝나지 않는다. 현재 웹 SQL은 PostgreSQL 전용 문법과 `market_intelligence`/`app_security` qualifier를 사용하므로 다음을 모두 완료해야 한다.

1. `web/src/lib/server/db.ts`를 `@libsql/client` + `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`으로 전환
2. executable SQL을 SQLite/Turso 문법으로 개별 포팅
3. schema qualifier, PostgreSQL cast, JSONB aggregate/build, `DISTINCT ON`, `LATERAL`, interval, `ILIKE`, array/`ANY`, `generate_series` 제거 또는 의미 보존 재작성
4. allowlist와 atomic login rate limit을 Turso transaction semantics로 전환
5. 기존 API JSON contract 검증
6. local endpoint smoke, desktop/mobile 로그인·화면 QA
7. Vercel secret env 설정 후 production build/deploy/QA

PostgreSQL migration `db/v2/migrations/3.9.0_compact_serving_v2.sql`은 과거 Supabase-compatible 설계 기록이며 Turso에는 실행하지 않는다.

## 배포 금지 조건

- URL/auth probe 실패
- local 또는 remote integrity/FK 실패
- 138개 table 또는 585,411행 parity 불일치
- 핵심 최신일·projection aggregate 불일치
- 승인 이메일 allowlist 미이관
- executable SQL의 PostgreSQL 전용 문법 잔존
- API contract·로그인·desktop/mobile QA 미완료
- Vercel secret env 미설정
