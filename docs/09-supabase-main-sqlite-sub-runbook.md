# Supabase main / SQLite sub 운영계약

## 1. 역할

| 계층 | 위치 | 역할 | 평시 write |
|---|---|---|---|
| Main | Supabase PostgreSQL `market_intelligence` | 권위 원장, canonical·raw·claim·review·relationship ledger | 허용 |
| Sub | `data/market.db` | main에서 만든 검증 snapshot, 로컬 조회·분석·복구 후보 | 금지 |
| Backup | `backups/*.db` | SQLite backup API 시점 보존본 | 금지 |

`data/market.db`가 최신 main보다 앞서거나 다른 값을 가진 경우 그 차이는 자동 승격하지 않는다. main을 기준으로 sub를 다시 만든다.

## 2. 자격증명

- 중앙 파일: `C:\10137_WorkSpace\env\.env.supabase.local`
- 필수 변수: `SUPABASE_DB_URL`, `SUPABASE_DB_SCHEMA`
- `SUPABASE_DB_URL`은 Session pooler URI를 사용한다.
- 비밀번호·URL·secret key를 프로젝트, artifact, 로그, Git에 복사하지 않는다.

연결 확인:

```bash
uv run --with 'psycopg[binary]' python scripts/probe_supabase_postgres.py
```

## 3. 초기 이관

```bash
python scripts/migrate_sqlite_to_supabase.py dry-run
uv run --with 'psycopg[binary]' python scripts/migrate_sqlite_to_supabase.py migrate
```

안전장치:

1. live SQLite는 직접 전송하지 않고 backup API snapshot을 만든다.
2. target schema가 존재하면 기본적으로 중단한다.
3. `--replace`는 불완전 schema를 검토하고 재생성할 때만 사용한다.
4. PostgreSQL `public` schema와 기존 Supabase 객체는 수정하지 않는다.
5. FTS5 내부 table은 복사하지 않고 PostgreSQL 검색 view로 재구성한다.
6. 완료 artifact: `artifacts/supabase-initial-migration-result.json`

base-table COPY가 모두 커밋된 뒤 constraint/view 단계만 실패했다면 원본 snapshot과 target row count를 먼저 대조하고 다음으로 재개한다.

```bash
uv run --with 'psycopg[binary]' python scripts/migrate_sqlite_to_supabase.py finalize
```

`finalize`는 table별 row count가 다르면 중단하며 재전송을 임의로 진행하지 않는다.

## 4. Local sub 갱신

후보 생성만 수행:

```bash
uv run --with 'psycopg[binary]' python scripts/refresh_sqlite_sub_from_supabase.py
```

후보는 `data/market.sub.candidate.db`에 생성된다. 다음 검증이 모두 통과해야 한다.

- PostgreSQL/SQLite table별 row count 일치
- `PRAGMA integrity_check = ok`
- `PRAGMA foreign_key_check = 0`
- SQLite trigger·view·FTS 재구성

검증 후 원자 교체까지 수행:

```bash
uv run --with 'psycopg[binary]' python scripts/refresh_sqlite_sub_from_supabase.py --activate
```

활성화 직전 기존 `data/market.db`는 SQLite backup API로 `backups/market-pre-sub-activation-*.db`에 보존한다. 결과는 `artifacts/supabase-to-sqlite-replica-result.json`에 기록한다.

## 5. Write·충돌 정책

- 정상 write: Supabase main만 허용한다.
- SQLite sub write: 자동 병합하지 않는다.
- 동일 PK 충돌: Supabase main 우선.
- correction: 기존 append-only 원문·version을 덮지 않고 main에서 새 version/revision을 만든다.
- 삭제: 일반 hard delete를 sync 신호로 사용하지 않는다. lifecycle/status 또는 명시적 tombstone 정책을 사용한다.
- SQLite에서 발견된 긴급 수정은 근거와 변경 내용을 별도 review task로 만들고 main에서 다시 적용한다.
- legacy SQLite collector는 PostgreSQL writer adapter 적용 전 운영 경로에서 중지한다. 테스트 시에는 복제본/staging DB만 사용한다.

## 6. Watermark·감사

전체 snapshot 방식의 watermark는 다음 3개를 함께 기록한다.

1. main refresh 시작·완료 UTC
2. table별 row count
3. 생성 SQLite SHA-256

증분 sync를 도입하기 전에는 `updated_at`만으로 삭제·정정을 추론하지 않는다. 증분 전환 시 revision sequence와 tombstone table을 먼저 추가한다.

## 7. 장애·fallback

### Supabase 일시 장애

- SQLite sub를 read-only 조회에 사용한다.
- 운영 수집 write는 큐잉하거나 중지한다.
- SQLite를 자동 승격하지 않는다.

### 명시적 SQLite 비상 승격

다음 조건을 모두 충족해야 한다.

1. 사용자 승인
2. 승격 시각과 Supabase 마지막 성공 watermark 기록
3. SQLite 별도 working copy 생성
4. 복구 후 양쪽 diff·충돌 검토
5. main 재적재 및 검증 후 SQLite를 다시 sub로 재생성

### 이관 실패

- PostgreSQL schema를 main으로 선언하지 않는다.
- 기존 SQLite와 pre-migration backup을 보존한다.
- 실패 schema를 inventory한 뒤에만 `--replace`로 재실행한다.

## 8. 완료 기준

```text
PostgreSQL 인증·CREATE 권한 확인
+ base table·row count 일치
+ PK·unique·CHECK·FK 검증
+ view·trigger·FTS 생성
+ 대표 raw/version/review/relationship/LP 표본 대조
+ Supabase read/write smoke test
+ Supabase→SQLite candidate 재생성 및 무결성 확인
+ 기존 SQLite 전용 운영 writer 차단 또는 adapter 전환
```
