# Post-collection relationship resolution contract

## 목적

모든 권위 수집·추출·승인 manifest import 뒤에 관계정합화를 실행한다. 원문·mention·claim을 쌓는 것으로 끝내지 않고, 근거 수준에 맞춰 identity와 canonical relation을 연결하거나 명시적 gap/review 상태로 남긴다.

## 고정 실행 순서

```text
collection/import commit
→ entity normalization
→ unique exact canonical/alias resolution
→ ambiguity review queue
→ ACCEPTED + VERIFIED claim relation promotion
→ participant / occupancy / business activity upsert
→ relationship run ledger
→ v_relationship_gaps QA
```

권위 entrypoint는 성공한 호출마다 삽입량이 0이거나 기존 run 재사용이어도 `reconcile_relationships()`를 실행한다. `tests/test_relationship_hook_contract.py`가 AST와 zero-row runtime 경로를 함께 검사한다.

## 자동연결 허용

### 조직 identity

- Unicode NFKC, case-fold, 문자·숫자 이외 구분자 제거 후 비교한다.
- canonical name 또는 `organization_aliases`에 **유일하게 exact match**될 때만 `mention_resolutions.selected=1`로 자동 확정한다.
- 같은 normalized key가 둘 이상의 조직과 일치하면 자동 선택하지 않는다.
- ambiguous candidate는 모두 보존하고 `ORGANIZATION_RESOLUTION_REVIEW` task를 만든다.
- ACTIVE canonical organization만 자동 resolution 후보로 사용한다. research candidate importer는 미등록 조직을 생성하지 않는다.
- 조건 해소 시 열린 task를 자동 종료하고, 종료 후 문제가 재발하면 새 attempt task를 만든다.
- unmatched mention은 관계를 추정하지 않고 `v_relationship_gaps`에 남긴다.

### 사건 참여자

`predicate_relationship_rules`에 등록된 규칙만 사용한다.

- claim `review_status=ACCEPTED`
- rule의 `minimum_verification_status` 충족(권위 기본 rule은 모두 `VERIFIED`)
- 명시적 organization claim argument 존재
- canonical event link 존재

네 조건이 모두 충족돼야 `event_participants`로 승격한다. 현재 자동 role은 `TENANT`, `LANDLORD`, `OWNER`, `OPERATOR`, `INVESTOR`, `BUYER`, `SELLER`다.

### 점유관계

다음 조건이 모두 있어야 `organization_property_occupancies`를 만든다.

- canonical `LEASE` 또는 `CORPORATE_RELOCATION` event
- VERIFIED claim에서 승격된 `TENANT` participant
- event에 연결된 asset 또는 project
- `source_claim_id`

단계별 상태는 reported/negotiating/contracted/occupied/cancelled로 결정론적으로 매핑한다. asset/project가 없거나 근거 claim이 없으면 점유관계를 만들지 않는다.

### 사업영역

- `BUSINESS_DOMAIN` claim
- `SUBJECT_ORGANIZATION` argument
- `ACCEPTED + VERIFIED`
- 명시적 `valid_time_start` 또는 `date_start`

네 조건이 있어야 `organization_business_activities`로 승격한다. 날짜가 없으면 `BUSINESS_ACTIVITY_RELATION_REVIEW` task를 만들고 시점을 추정하지 않는다.

## 금지

- 이름 유사도만으로 자동 identity 확정
- 기사 등장만으로 임차인·소유자·투자자 role 추정
- 명시적으로 낮춘 rule threshold가 없는 PENDING/UNVERIFIED claim의 canonical relation 승격
- 현재 회사 식별자를 과거 회사에 소급 적용
- event에 asset/project가 없는데 occupancy 생성
- 사업영역 시작일 추정

## 감사·공백

- 실행원장: `relationship_resolution_runs`
- 자동규칙: `predicate_relationship_rules`
- 공백 view: `v_relationship_gaps`
- 현재 gap code:
  - `UNRESOLVED_ORGANIZATION_MENTION`
  - `ORGANIZATION_MISSING_IDENTIFIERS`
  - `COMPANY_EVENT_WITHOUT_PARTICIPANT`

모든 upsert는 stable ID 또는 존재검사로 idempotent해야 한다. 반복 실행에서 신규 근거가 없다면 canonical relation 생성량은 0이어야 한다.

승격 근거 claim이 REJECTED·CONTRADICTED·INCONCLUSIVE 또는 rule threshold 미달로 바뀌면 자동 event participant는 제거하고, occupancy/business activity는 `SUPERSEDED`로 전환한다. collection-scoped 실행은 occupancy까지 같은 collection의 claim으로 제한한다.

## 수동 실행

```bash
python -m collector.post_collection_relationships data/market.db --allow-live
```

특정 collection run만 재평가:

```bash
python -m collector.post_collection_relationships data/market.db \
  --collection-run-id <run-id> --allow-live
```

## V2.7 migration

```bash
python db/v2/migrate_2_7.py data/market.db
```

migration CLI는 먼저 SQLite backup API로 backup과 SHA-256 manifest를 생성한다. SQL은 Python 검증 전 commit하지 않으며 schema version·integrity·foreign key·필수 rule tuple 내용을 같은 transaction에서 검증한다. 이미 적용된 DB도 재검증한다.
