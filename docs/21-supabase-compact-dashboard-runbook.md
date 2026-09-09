# 신규 Supabase compact dashboard 운영 기록

기준 시각은 2026-09-09이며, 신규 프로젝트 ref는 `rjalzmmiqhrdmhojbxsk`이다. 최종 active dataset은 `cre-20260909T060407Z-5c55a7cb58de`, source freshness는 `2026-09-09T06:04:07Z`, schema/package version은 `1.1.0`이다. 기존 Supabase와 Turso, 원본 `data/market.db`, 수집 예약은 변경하지 않았다.

## 저장 범위와 행 grain

| 논리 테이블 | 행 grain | 최종 행수 | 용도 |
|---|---|---:|---|
| `article_dates` | dataset + 기사일 | 498 | 날짜 목록과 일별 사전 합계 |
| `articles` | dataset + document | 2,145 | 목록·근거검색에 필요한 최소 기사 projection |
| `article_details` | dataset + document | 2,145 | 현재 상세 drawer payload |
| `article_topics` | dataset + document + topic | 1,103 | topic facet/filter |
| `article_search_documents` | dataset + document | 2,145 | 문서별 2글자 literal token `text[]`; GIN 조회 |
| `macro_series` | dataset + series | 19 | 계열 정의·출처·단위 |
| `macro_monthly` | dataset + series + month | 4,471 | 월별 거시 관측치; 현재 UI는 13개 계열 표시 |
| `permit_monthly` | dataset + month + event + district + asset + action | 90,907 | 서울 source 및 `IN_SCOPE` 필터 조합용 월 fact |
| `market_pulse` | dataset | 1 | 고정 범위 시장 pulse 사전 계산 payload |

현재 dashboard serving 대상 기사 2,145건·날짜 498개·topic 1,103개를 전부 유지했다. 전체 archive의 raw `source_documents`를 올렸다는 뜻은 아니다. 원본 인허가 월 집계 94,716행 중 현재 dashboard 계약인 서울 source + `IN_SCOPE` 90,907행을 유지했다. MOLIT current 17,995 raw 거래행은 상세 drill-down에 쓰이지 않으므로 올리지 않고, 기존 TypeScript SQL 의미를 보존한 pulse payload 한 행으로 계산했다.

올리지 않은 항목은 raw archive, source history, MOLIT raw 거래, permit hot detail, 대형 중복 JSON, embedding/vector이다. 검색은 생성형 AI가 아니라 기사 `search_text` trigram, 문서별 2글자 token GIN, topic/date/publisher 사전 facet으로 처리한다.

## 물리 구조와 접근 계약

물리 테이블은 RLS가 활성화된 private schema `cre_news`, `cre_timeseries`, `cre_system`에만 둔다. `anon`과 `authenticated`에는 schema/table 권한이 없고, web server의 `service_role`만 아래 bounded `public` RPC를 호출한다.

- `dashboard_serving_manifest()`
- `dashboard_daily_articles(p_date, p_limit, p_dataset_version)`
- `dashboard_article_detail(p_document_id, p_dataset_version)`
- `dashboard_macro_timeseries(p_dataset_version)`
- `dashboard_permit_timeseries(p_group_by, p_from, p_to, p_event_type, p_asset_type, p_district, p_construction_action, p_dataset_version)`
- `dashboard_market_pulse(p_dataset_version)`
- `dashboard_contextual_evidence_search(q, filters, top_k, p_dataset_version)`
- `dashboard_authorize_subject(p_subject_id)` / `dashboard_find_authorized_subject(p_email)`
- `dashboard_consume_login_attempts(p_keys)` / `dashboard_clear_login_attempts(p_keys)`

모든 data RPC는 manifest에서 읽은 dataset version을 선택 인자로 받아 같은 snapshot을 읽고 응답에도 `datasetVersion`을 돌려준다. evidence UI 계약은 실제 반환수 `returned`(최대 8)와 `truncated`를 기준으로 하며 `total`을 완전한 페이지네이션 수치로 사용하지 않는다. `%`와 `_`는 literal로 escape한다. 2글자 후보는 `article_search_documents.terms @> ARRAY[lower(q)]`, 3글자 이상은 `articles.search_text` trigram에서 먼저 document id를 뽑은 뒤 기사 PK로 결합한다.

승인된 3개 subject는 최초 bootstrap에서 없는 행만 넣는다. 일반 publish의 `ON CONFLICT DO NOTHING`은 원격에서 철회·만료·수정된 권한을 되살리지 않는다. rate limiter는 service-role RPC 안에서 원자 처리하며 최초 결과의 `blocked`는 반드시 boolean `false`이다.

## 원자 발행과 no-op

export는 SQLite를 `mode=ro`, `query_only=ON`, 단일 read transaction으로 읽는다. dataset identity에는 schema version, table별 content hash와 row count, lineage, facet, market-pulse SQL hash만 포함한다. source path, mtime, 파일 크기와 page count는 provenance로만 보존하므로 내용이 같고 mtime만 변한 경우 새 version을 만들지 않는다.

publish는 한 PostgreSQL transaction과 advisory lock 안에서 다음 순서를 지킨다.

1. dataset을 `LOADING`으로 만들고 모든 private table을 `COPY`한다.
2. 행수 검사 후 날짜·timestamp·numeric·JSON을 target 타입으로 정규화하여 package와 원격의 **모든 행**을 다시 읽고 table별 semantic SHA-256을 비교한다.
3. 이 pre-activation gate가 모두 통과한 경우에만 기존 active를 `RETIRED`로 바꾸고 `active_manifest`를 한 번에 전환한다.
4. 어느 단계든 실패하면 transaction 전체가 rollback되어 이전 active가 유지된다.

동일 active package 재실행은 `action=verified-existing`이며 새 version/행을 만들지 않는다. 2026-09-09 실제 재실행에서도 version count 1을 유지하면서 transaction 내부 9개 semantic gate가 모두 통과했다.

## 실행 절차

아래 예시는 저장소 root가 `09. CRE DB Board`일 때의 PowerShell 명령이다. env 파일 내용을 출력하지 않는다.

```powershell
$publisherPython = ".codex_tmp\supabase-venv\Scripts\python.exe"
$targetRef = "rjalzmmiqhrdmhojbxsk"
$poolerHost = "aws-0-ap-northeast-1.pooler.supabase.com"
$authorityFile = "C:\10137_WorkSpace\env\.env.personal.txt"

& $publisherPython scripts\export_compact_dashboard_supabase.py plan --source data\market.db
& $publisherPython scripts\export_compact_dashboard_supabase.py export --source data\market.db --output-root artifacts\supabase-compact

& $publisherPython scripts\publish_compact_dashboard_supabase.py migrate --env $authorityFile --target-ref $targetRef --pooler-host $poolerHost --migration db\v2\migrations\4.0.0_supabase_compact_dashboard.sql --apply
& $publisherPython scripts\publish_compact_dashboard_supabase.py migrate --env $authorityFile --target-ref $targetRef --pooler-host $poolerHost --migration db\v2\migrations\4.0.1_compact_search_document_terms.sql --apply

& $publisherPython scripts\publish_compact_dashboard_supabase.py publish --env $authorityFile --target-ref $targetRef --pooler-host $poolerHost --package artifacts\supabase-compact\cre-20260909T060407Z-5c55a7cb58de --auth-db data\local-access.db --activate
& $publisherPython scripts\publish_compact_dashboard_supabase.py publish --env $authorityFile --target-ref $targetRef --pooler-host $poolerHost --package artifacts\supabase-compact\cre-20260909T060407Z-5c55a7cb58de --auth-db data\local-access.db --apply --activate --report artifacts\supabase-compact\publish-report-20260909-final.json
```

첫 `publish`는 dry-run이며 `willWrite=false`를 확인한 뒤에만 두 번째 명령을 실행한다. 신규 project는 direct DB host가 IPv6-only여서 공식 Tokyo session pooler를 사용했다. publisher는 env의 project ref와 URL이 `--target-ref` 하나에만 일치하는지, pooler가 공식 hostname인지 검사하고 URI에 들어 있는 해당 신규 DB password만 사용한다. Management API token은 계정이 달라 이 ref를 보지 못했으므로 사용하지 않았다.

일반 검증은 다음과 같다.

```powershell
& $publisherPython scripts\publish_compact_dashboard_supabase.py verify-package --package artifacts\supabase-compact\cre-20260909T060407Z-5c55a7cb58de
& $publisherPython scripts\publish_compact_dashboard_supabase.py verify-remote --env $authorityFile --target-ref $targetRef --pooler-host $poolerHost --package artifacts\supabase-compact\cre-20260909T060407Z-5c55a7cb58de --report artifacts\supabase-compact\publish-report-20260909-final.json
& "..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe" -m pytest tests\test_supabase_compact_dashboard.py -q
```

`prune`은 정확히 지정한 non-active `RETIRED` version만 삭제하며 active이면 거부한다. 평상시에는 active와 직전 검증판 한 개를 보존한다. 이번 bootstrap 과정에서 만든 내용 중복 시험판만 full parity 이후 명시 삭제했으며, auth subject 수 3이 전후 동일함을 검사했다. 자동 prune은 없다.

## 2026-09-09 실측

서로 다른 개념의 크기를 섞지 않는다.

| 대상 | bytes | 의미 |
|---|---:|---|
| 원본 `market.db` | 1,715,994,624 | 전체 local archive/source |
| 2026-09-08 split projection | 166,084,608 | 구 snapshot의 두 SQLite 파일 합계; 최신 source가 아님 |
| 최종 package JSONL 합계 | 39,640,232 | 압축 전 직렬화 payload 추정 |
| 최종 gzip package | 4,009,668 | 전송 파일 합계 |
| 신규 PostgreSQL `pg_database_size` | 61,516,947 | 최종 no-op 재검증 직후 전체 database 물리 크기 |

`pg_database_size`는 catalog/extension 등 compact schema 밖의 공간도 포함하며 측정 시점에 수십~수백 KB 변동할 수 있다. 직전 독립 측정은 61,303,955 bytes였다.

| schema | table bytes | index bytes | `pg_total_relation_size` 합계 |
|---|---:|---:|---:|
| `cre_news` | 7,380,992 | 8,855,552 | 20,021,248 |
| `cre_timeseries` | 15,368,192 | 14,516,224 | 29,933,568 |
| `cre_system` | 49,152 | 147,456 | 270,336 |

초기 한 posting당 한 행이던 2글자 검색 테이블은 단독으로 86,761,472 bytes였다. 문서당 `text[]` 한 행으로 바꾼 최종 `article_search_documents`는 table 1,802,240 + index 2,228,224, total 4,136,960 bytes이다.

최종 QA 결과는 private table 15개 RLS 모두 true, invalid constraint 0, 승인 3/미승인 reject, rate-limit 첫 호출 `blocked=false`, 기사 최신일 `2026-09-09` 7건, macro 13개 표시 계열, permit RPC 3개 event series, pulse 기준월 `2026-08`이다. 일별·macro·permit는 각각 전용 btree index, 2글자는 array GIN, 3글자 이상은 trigram GIN을 사용하는 candidate plan을 확인했다. 실제 server RPC execution은 대표 2글자 약 1.1~3.8ms, 3글자 약 65ms였고, 새 연결 기준 query는 약 74~106ms였다(OS page cache는 강제로 비우지 않음).

market pulse는 현재 TypeScript `getQuantitativeMarketPulse`를 실제 `market.db`에 실행한 결과와 export payload의 call, metrics, trend, concentration, coverage, quality, scope를 비교했다. SQLite/libSQL의 부동소수 문자열 표현 차이만 `max(1e-6, abs(expected) * 1e-9)` 허용오차로 비교했고 나머지는 exact parity로 통과했다.

최종 증적은 `artifacts/supabase-compact/publish-report-20260909-final.json`에 있다. 이 report의 package checksum은 파일 무결성이고, `preactivationSemanticParity`와 `verification.semanticParity`는 실제 PostgreSQL 저장값 전수 정합성으로 서로 구분한다.

## 운영 연결 방침

이번 작업에서는 자동 수집 예약이나 Vercel 환경변수를 변경하지 않는다. 현재 publisher는 **9개 테이블 전체가 하나의 snapshot**이므로 뉴스만 달라져도 인허가 90,907행을 포함한 9개 테이블을 모두 새 version으로 복사한다. no-op은 9개 테이블·lineage·facet·schema를 포함한 전체 identity가 완전히 같을 때만 성립한다. 따라서 이번에는 자동예약에 연결하지 않고 내용 변경을 확인한 뒤 수동 publish한다. 원격 update가 실패하면 이전 active는 유지된다. 향후 빈도가 높아질 때 뉴스·거시·인허가 domain version을 분리해야 반복 write를 줄일 수 있으며, 이는 이번 구현이 아닌 후속 최적화다.
