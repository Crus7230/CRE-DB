# Database authority

## Current authority: V2.7 SQLite

서버 없이 누적 운영하는 권위 스키마는 다음 파일이다.

```text
db/v2/schema.sql
db/v2/seed.sql
db/v2/init_db.py
db/v2/validate_schema.py
db/v2/backup_db.py
docs/04-v2-sqlite-data-contract.md
docs/05-v2-measurement-model.md
docs/06-post-collection-relationship-resolution.md
```

### 생성

```bash
python db/v2/init_db.py data/market.db
```

기존 DB는 기본적으로 덮어쓰지 않는다. 실제 운영 데이터가 없는 초기화 상황에서만 명시적으로 `--force`를 사용한다.

### 일관된 백업

실행 중인 WAL DB의 `.db` 파일만 복사하지 않는다. SQLite backup API를 사용한다.

```bash
python db/v2/backup_db.py data/market.db backups/market-2026-08-15.db
```

백업 DB와 함께 `.manifest.json`이 생성되며 schema version, 파일 크기, SHA-256, `quick_check`, foreign key 검사 결과를 기록한다.

### V2.6 → V2.7 migration

```bash
python db/v2/migrate_2_7.py data/market.db
```

CLI가 backup API 백업을 먼저 만들고 migration 후 schema version, relationship rule, integrity, foreign key를 검증한다.

### 수집 후 관계정합화

권위 collector·extractor·manifest importer는 commit 후 자동 실행한다. 운영자가 전체 공백을 재평가할 때만 수동 실행한다.

```bash
python -m collector.post_collection_relationships data/market.db --allow-live
```

### 검증

```bash
cd db/v2
python validate_schema.py
```

검증기는 임시 DB에 다음 종단 흐름을 실행한다.

```text
가상 문서
→ 프로젝트·회사·날짜·금액·면적·단계 mention span
→ mention relation
→ canonical project·organization resolution
→ typed claim
→ 자산·프로젝트·동·층·구역 공간 계층
→ measurement definition·typed measurement fact·dimension
→ 상충 측정값 selection·파생값 lineage
→ canonical event·transition
→ macro observation revision
→ weekly snapshot
→ FTS·view 조회
```

테스트 데이터는 모두 가상이며 실제 시장정보가 아니다.

## V2 모듈

| 계층 | 주요 테이블 |
|---|---|
| 분류·단위 | `asset_classes`, `event_categories`, `event_stages`, `units`, `predicate_definitions` |
| 측정 분류 | `measurement_definitions`, `measurement_definition_aliases`, `measurement_definition_relations`, `measurement_applicability` |
| 공간 계층 | `spatial_unit_types`, `spatial_units`, `spatial_unit_aliases` |
| 동적 차원 | `measurement_dimension_definitions`, `measurement_dimension_options`, `measurement_fact_dimensions` |
| 표준 마스터 | `regions`, `organizations`, `assets`, `projects` 및 aliases |
| 수집 | `collection_sources`, `collection_jobs`, `collection_runs` |
| 문서 | `source_documents`, `document_versions`, `document_families`, `document_fts` |
| NLP | `extraction_runs`, `document_tokens`, `mentions`, `mention_fragments`, `mention_values`, `mention_relations` |
| 식별 | `mention_resolutions` |
| 관계정합화 | `predicate_relationship_rules`, `relationship_resolution_runs`, `v_relationship_gaps` |
| 출처별 주장 | `event_mentions`, `claims`, `claim_arguments`, `claim_evidence` |
| 실제 사건 | `events`, `event_assets`, `event_projects`, `event_participants`, `event_transitions` |
| 채택값 | `fact_selections` |
| 측정값 | `measurement_facts`, `measurement_fact_selections`, `measurement_derivations`, `measurement_derivation_inputs` |
| 매크로 | `macro_series`, `macro_releases`, `macro_observations` |
| 스냅샷 | `snapshots`, `snapshot_macro_items`, `snapshot_event_states`, `snapshot_metrics` |
| 검수·감사 | `review_tasks`, `duplicate_candidates`, `merge_history`, `audit_log` |

## Deprecated V1

다음 파일은 초기 PostgreSQL/Supabase 개념검증본이며 신규 운영 DB에 적용하지 않는다.

```text
db/schema.sql
db/seed.sql
```

V1은 기록과 비교를 위해 보존한다. V2와 함께 같은 DB에 적용하면 안 된다.
