# Classification Taxonomy V1 운영계약

## 목적

CRE 데이터가 계속 누적되어도 자유 문자열 category가 분기하지 않도록 schema 3.3.0부터 관리형 분류체계를 사용한다. 기존 도메인 필드는 원본 의미와 하위 호환을 위해 유지한다.

## 권위 객체

- `classification_schemes`: 분류 차원과 cardinality, 적용 대상, vocabulary version
- `classification_terms`: scheme별 term, 한국어/영문 label, 계층, 유효기간, governance 상태
- `record_classifications`: 대상과 term의 다대다 연결, primary, provenance, confidence, review, validity, lineage
- `v_record_classification_summary`: 검색용 대표 분류 projection. 권위 데이터가 아닌 drift-free view

## Category와 상태 분리

다음 차원을 한 vocabulary에 혼합하지 않는다.

- record kind: DOCUMENT, EVENT, ASSET 등
- market category: SALE, LEASE, SUPPLY, PERMIT, PF, LOAN 등
- document purpose: 거래근거, 기업근거, 시장동향, 절차공고 등
- lifecycle/review status
- evidence grade
- asset class
- organization type/industry
- investment strategy
- geography

## 신규 term 추가 절차

1. 기존 scheme에 해당하는지 확인한다.
2. 기존 `term_code`와 synonym을 검색한다.
3. 재사용할 term이 없을 때만 stable `classification_term_id`와 uppercase `term_code`를 추가한다.
4. hierarchy scheme이면 부모 term을 지정한다.
5. 즉시 운영할 term만 `governance_status='ACTIVE'`로 둔다.
6. importer가 term 자유 문자열을 생성하지 않도록 controlled upsert 또는 승인 manifest를 사용한다.
7. term 추가 후 SQLite/PostgreSQL seed와 migration 경로를 함께 갱신한다.

## Assignment 계약

- 같은 대상에 복수 term 허용
- 같은 대상·scheme의 현재 primary는 최대 1개
- 기존 수동 primary가 있으면 backfill/자동분류가 덮어쓰지 않음
- 자동분류는 `classifier_version` 필수
- `assignment_role`: DIRECT, DERIVED, RELATED, MANUAL, LEGACY_BACKFILL
- 분류 근거는 `evidence_status`, 논리 evidence ID, `evidence_locator`, `lineage_json`에 기록
- 분류 무효화는 삭제보다 `valid_to` 또는 `review_status='SUPERSEDED'` 우선
- 잘못된 분류는 `REJECTED`; 원문 분류이력은 local full archive에 보존

## Vocabulary 변경

- label 수정: 같은 term 유지, vocabulary patch version 증가
- 의미 변경: 기존 term deprecate 후 신규 term 생성
- 합병: 구 term `DEPRECATED`, 신규 term assignment를 별도 생성하고 lineage 기록
- 분할: 자동 승격 금지, review queue 생성
- code 재사용 금지

## Backfill

명령은 기본 dry-run이다.

```bash
python scripts/backfill_record_classifications.py --sqlite data/market.db
python scripts/backfill_record_classifications.py --sqlite data/market.db --apply \
  --report artifacts/classification-backfill-v33-local.json
```

Supabase는 schema migration과 archive 검증 후 별도 적용한다.

```bash
uv run --with 'psycopg[binary]' python scripts/backfill_record_classifications.py \
  --supabase --apply --report artifacts/classification-backfill-v33-supabase.json
```

## Backfill source mapping V1

- `events.primary_category_id` → `MARKET_CATEGORY`, classifier `EVENT_CATEGORY_V1`
- `assets.asset_class_id` → `ASSET_CLASS`, classifier `ASSET_CLASS_V1`
- `organizations.organization_type` → `ORGANIZATION_TYPE`, classifier `ORGANIZATION_TYPE_V1`
- `organization_industry_assignments` → `INDUSTRY`, classifier `ORGANIZATION_INDUSTRY_V1`
- source-aware document type → `DOCUMENT_PURPOSE`, classifier `DOCUMENT_PURPOSE_SOURCE_V1`
- source authority → `EVIDENCE_GRADE`, classifier `DOCUMENT_EVIDENCE_SOURCE_V1`
- `lp_mandate_tracks.strategy_code` → `INVESTMENT_STRATEGY`, classifier `LP_TRACK_STRATEGY_V1`
- `lp_mandates` → `MARKET_CATEGORY:LP_MANDATE`
- `sale_processes` → `MARKET_CATEGORY:SALE`
- `archived_serving_index` → record-kind-aware `MARKET_CATEGORY`, classifier `ARCHIVED_MARKET_CATEGORY_V2`
  - EVENT: event category crosswalk
  - LP_MANDATE: `LP_MANDATE`
  - SALE_PROCESS: `SALE`
  - DOCUMENT: category code를 market category로 승격하지 않음

초기 `ARCHIVE_CATEGORY_V1`의 kind-blind assignment는 삭제하지 않고 `SUPERSEDED` 처리한다. V1에서만 만들어졌고 현재 유효 assignment가 없는 동적 market term은 `DEPRECATED` 처리한다.

## Active/archive 계약

- local SQLite는 전체 assignment와 evidence lineage의 권위 archive
- Supabase는 active assignment와 archived compact classification을 serving
- `record_classifications.source_*_id`는 active detail retire 이후에도 lineage를 보존하기 위한 논리 참조
- archived row의 category는 `record_classifications`를 우선하고 기존 `archived_serving_index.category_code`를 fallback으로 사용
- archive snapshot 자체는 과거 vocabulary version을 metadata에 기록

## 필수 QA

- schema version 3.3.0
- SQLite integrity `ok`
- FK violation 0
- current primary conflict 0
- deterministic backfill 재실행 insert 0
- target별 classified/unclassified count
- scheme·target별 assignment/primary count
- PostgreSQL search/category SQL smoke
- Python/Web 전체 tests 및 Next.js production build
