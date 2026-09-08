# 서울 상업용 건축인허가 데이터셋 운영계약

## 목적

서울시 건축인허가 원문을 업무·물류·데이터센터·호텔·리테일·복합용도 관점으로 분류하고, 건축허가·실제착공·사용승인 흐름을 월별 건수와 연면적으로 제공한다.

## Source precedence

| 역할 | Source | 식별자 | 비고 |
|---|---|---|---|
| 권위 월별 series·초기 full snapshot | 서울 열린데이터광장 건축인허가 기본개요 | `SEOUL_BUILDING_PERMIT`, `OA-22404`, `vBigKcrPmsrgst` | 1회 최대 1,000행, 매일 갱신 |
| 코드·지번·정정 도착 증분 보강 | 국토교통부 건축HUB 건축인허가정보 | `BUILDING_HUB`, data.go.kr `15136267`, `getApBasisOulnInfo` | 법정동 partition, `startDate/endDate`는 `crtnDay` 생성일 기준 |
| 법정동 partition roster | 행정안전부 행정표준코드관리시스템 | `법정동 코드 전체자료` | 서울·존재·하위코드≠`00000`, 467개 법정동 |

서울시와 건축HUB의 source record key는 서로 다르다. crosswalk가 승인되기 전 두 source를 합산하지 않는다. `v_cre_building_permit_monthly`는 `source_id`를 필수 차원으로 둔다. 기본 시장 시계열은 `source_id='src_seoul_building_permit'`를 사용한다.

## 분류 계약 `cre-permit-v1`

### 핵심 포함

- `OFFICE`: 업무시설
- `LOGISTICS`: 창고시설·물류시설·운수시설
- `DATA_CENTER`: 데이터센터·전산센터·IDC 명시
- `HOTEL`: 숙박시설·호텔
- `RETAIL`: 판매시설·근린생활시설·위락시설

### 검토 queue

- `REVIEW_MIXED`: 복합용도·주상복합 또는 비주거 주용도에 주거 세대 신호가 함께 존재
- `REVIEW_DATA_CENTER`: 방송통신시설이지만 데이터센터 문구가 없음
- `REVIEW_OTHER`: 공장·교육연구·의료·문화집회·운동·자동차시설 등 대체 상업용 후보 또는 미매핑 비주거 용도
- `REVIEW_UNKNOWN`: 주용도 공란

### 제외

- `EXCLUDED_RESIDENTIAL`: 단독·공동·다가구·다세대·연립·기숙사
- `EXCLUDED_NONCOMMERCIAL`: 종교·교정군사·묘지·동식물·자원순환·발전시설 등

후보 원문은 content version으로 보존한다. 제외 행은 snapshot별 자치구·주용도·제외 사유·건수·연면적 집계를 보존한다. 분류규칙 변경 시 과거 분류를 덮어쓰지 않고 새 `rule_version`을 추가한다.

## 공급 action

| 원문 건축구분 | `construction_action` | 신규 공급 해석 |
|---|---|---|
| 신축 | `NEW_SUPPLY` | 신규 공급 |
| 증축 | `AREA_EXPANSION` | 면적 증가 |
| 개축·재축·대수선 | `REDEVELOPMENT` | 재개발·리포지셔닝 |
| 용도변경 | `USE_CONVERSION` | 신규 공급과 분리 |
| 기타 | `OTHER` | 별도 검토 |

## 월별 event 정의

`v_cre_building_permit_events`는 다음 실제 날짜만 사용한다.

- `PERMIT`: 건축허가일
- `ACTUAL_START`: 실제착공일
- `USE_APPROVAL`: 사용승인일

`planned_start_date`와 `delayed_start_date`는 pipeline forecast용 원문 필드로 보존하지만 실제 공급 flow 집계에는 포함하지 않는다.

`v_cre_building_permit_monthly` 차원:

- `source_id`
- `event_month`
- `event_type`
- `district_name`
- `asset_type`
- `scope_status`
- `construction_action`

측정값:

- `permit_count`
- `total_floor_area_m2`
- `missing_area_count`

## Local authority schema

Feature version은 `schema_meta.building_permit_schema_version='1.0.5'`이다. global `schema_version=3.5.0`은 기존 analytics 호환성을 위해 변경하지 않는다.

- `building_permit_snapshots`: source snapshot·cursor·quota 상태
- `building_permit_snapshot_pages`: page receipt와 replay 방지
- `building_permit_record_versions`: immutable content version·정규화 필드·raw JSON
- `building_permit_snapshot_records`: snapshot membership
- `building_permit_classifications`: versioned CRE taxonomy
- `building_permit_exclusion_summary`: 제외 모집단 감사 집계
- `v_latest_building_permit_records`: 완료 snapshot만 사용하는 최신 source record
- `v_current_cre_building_permit_records`: 후보 current classification
- `v_cre_building_permit_events`: 허가·실착공·사용승인 event; `1900-01-01`부터 현재일까지의 실제 event만 포함
- `v_cre_building_permit_monthly`: source별 월별 집계; 비현실적 면적은 합계에서 격리하고 `invalid_area_count` 제공
- `v_building_permit_event_date_quality`: 결측·1900년 이전·미래·유효 날짜 품질 집계
- `v_building_permit_area_quality`: 결측·음수·2,000,000㎡ 초과·유효 연면적 품질 집계
- `building_permit_monthly_serving`: Supabase용 compact 월별 materialization
- `building_permit_current_serving`: Supabase용 현재 상세 mart; 주소·용도·면적·event 날짜·분류·품질상태 포함, raw JSON 제외

범위 밖 날짜와 음수·2,000,000㎡ 초과 연면적은 원문·normalized fact에서 삭제하지 않고 시장 집계에서만 격리한다. Partial·running snapshot은 production view에 들어오지 않는다.

## 실행

### Migration

```bash
python scripts/apply_building_permit_migration.py --engine sqlite
python scripts/apply_building_permit_migration.py --engine sqlite --apply

# Supabase는 psycopg가 설치된 interpreter 사용
C:/Users/10137/AppData/Local/Programs/Python/Python311/python.exe \
  scripts/apply_building_permit_migration.py --engine postgres
C:/Users/10137/AppData/Local/Programs/Python/Python311/python.exe \
  scripts/apply_building_permit_migration.py --engine postgres --apply
```

Local `--apply`는 SQLite backup API 백업을 먼저 만든다. 원본 DB가 Windows readonly이면 백업 성공 후에만 readonly 속성을 해제한다.

### 서울 full snapshot

```bash
python scripts/collect_seoul_building_permits.py \
  --snapshot-kind FULL --apply \
  --report artifacts/building-permits/seoul-full-YYYYMMDD.json
```

중단·quota 오류 후 snapshot report 또는 DB의 `snapshot_id`로 재개한다.

```bash
python scripts/collect_seoul_building_permits.py \
  --resume-snapshot <SNAPSHOT_ID> --apply
```

Page receipt가 존재하는 page는 replay하지 않는다.

### 건축HUB 증분

기본 window는 어제~오늘 `crtnDay`다. 과거 허가가 오늘 정정·생성되면 과거 `archPmsDay` event로 들어간다.

```bash
python scripts/collect_buildinghub_permits.py --apply
```

quota에 맞춰 요청수를 제한하고 재개할 수 있다.

```bash
python scripts/collect_buildinghub_permits.py \
  --start-date 2026-09-01 --end-date 2026-09-02 \
  --max-requests 200 --apply

python scripts/collect_buildinghub_permits.py \
  --start-date 2026-09-01 --end-date 2026-09-02 \
  --resume-snapshot <SNAPSHOT_ID> --apply
```

Resume 시 원 snapshot의 date window와 요청 window가 같아야 한다.

### Supabase serving publish

최신 완료 snapshot만 자동 선택한다. Local SQLite에는 raw JSON·revision·membership 전체를 보존하고, 개인 Supabase에는 source·완료 snapshot provenance, `building_permit_monthly_serving`, raw JSON을 제외한 `building_permit_current_serving` 상세 mart를 게시한다. 먼저 rollback rehearsal을 수행한다.

```bash
C:/Users/10137/AppData/Local/Programs/Python/Python311/python.exe \
  scripts/sync_building_permits_serving.py

C:/Users/10137/AppData/Local/Programs/Python/Python311/python.exe \
  scripts/sync_building_permits_serving.py --apply
```

Monthly row count·상세 row count·source별 event 집계·분류/자산유형/공사행위 조합별 건수를 readback 비교한 뒤에만 commit한다.

## 검증 기준

- SQLite `PRAGMA integrity_check='ok'`
- foreign key violation 0
- snapshot 내 source record key 중복 0
- `fetched_count = source_total_count`인 full snapshot만 `COMPLETED`
- page receipt 합계와 snapshot count 일치
- source별 월별 집계; cross-source 합산 금지
- 허가일·실착공일·사용승인일 min/max 및 결측률 보고
- payload hash 변경 시 revision 증가, 원문 overwrite 금지
