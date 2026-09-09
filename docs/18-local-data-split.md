# 로컬 serving DB 분리 운영안

## 목적과 경계

`split_local_serving_databases.py`는 canonical `market.db`의 현재 온라인 조회용 projection만 두 개의 작은 SQLite 파일로 복제한다. 원본 archive, 원천 payload, 수집 이력, 교차 도메인 스키마, 보안 테이블과 구버전은 원본에 그대로 남는다. 따라서 이 작업을 “원본 전체 DB 분리” 또는 “archive 대체”로 표현하면 안 된다.

- `news.db`: 일자·기사·분류·drawer detail과 `DAILY_ARTICLES` freshness/fingerprint
- `timeseries.db`: correction-safe MOLIT current/partition, 금융 월간값/series registry, 서울 건축 인허가 월간 집계와 각 3개 dataset freshness/fingerprint
- 원본 `market.db`: 위 serving projection의 권위 원천이자 나머지 모든 이력·운영 데이터의 유일한 archive

현재 permit API는 `serving_v2_building_permit_monthly`만 읽는다. 폭이 넓은 `serving_v2_building_permit_hot_detail`은 원본에 보존하되 split 대상에서는 제외한다. 향후 상세 route가 이 table을 실제로 사용하면 해당 SQL과 QA를 먼저 확정한 뒤 명시적으로 추가한다.

## 실행

두 경로를 항상 명시한다. `--apply`가 없으면 읽기 전용 plan이며 output directory도 만들지 않는다.

```powershell
python scripts/split_local_serving_databases.py `
  --source "C:\path\to\data\market.db" `
  --output-dir "C:\path\to\data\split"
```

검토한 plan과 원본 refresh 완료 시점을 확인한 뒤에만 실제 snapshot을 만든다.

```powershell
python scripts/split_local_serving_databases.py `
  --source "C:\path\to\data\market.db" `
  --output-dir "C:\path\to\data\split" `
  --apply
```

2026-09-08 사용자 요청에 따라 실제 `--apply`를 실행했다. 검증된 snapshot은 `data/split/20260908T094546047103Z-f25d038d`이며 news.db 10,813,440 bytes, timeseries.db 155,271,168 bytes다. 원본은 그대로 보존했다. 현재 로컬 웹의 세부 연결·실행·갱신 절차는 [현재 상태](20-local-smart-search-and-split-status.md)를 따른다.

## 안전성과 일관성

1. 원본은 SQLite URI `mode=ro`, `query_only=ON`으로 열고 한 번의 read transaction을 고정한다. 두 출력은 같은 원본 snapshot에서 생성된다.
2. table DDL과 명시 index는 원본 `sqlite_schema`에서 가져오며, 식별자는 보수적인 정규식으로 검사한다. FK는 `PRAGMA foreign_key_list`로 추적한다.
3. 예상 밖 FK parent는 자동으로 대량 복제하지 않고 실패한다. 현재 필요한 `collection_sources`, `units`, `regions`, `asset_classes`는 작은 공용 code table 전체를 복제해 self-parent와 지역/자산 계층을 보존한다. 기사 행에는 지역 필터를 적용하지 않는다.
4. `serving_dataset_freshness`와 `serving_row_fingerprints`만 output별 dataset code로 나눈다. dataset assignment는 서로 겹치지 않으며 active fingerprint 수와 serving row 수가 다르면 실패한다.
5. 각 table은 PK 순서의 type-tagged canonical row hash로 원본 선택 범위와 출력 전체를 대조한다. null, 정수 `0`, 실수 `0.0`, text와 blob을 서로 다르게 해시한다.
6. 두 DB 모두 `integrity_check`, `foreign_key_check`, 현행 news/detail/MOLIT/macro/permit join smoke SQL을 통과해야 한다.
7. 기존 DB나 snapshot directory는 덮어쓰지 않는다. 두 DB와 snapshot-local manifest가 모두 완성된 뒤 고유 snapshot directory로 승격하고, 마지막에만 `split/manifest.json`을 임시 파일에서 원자적으로 교체한다. 중간 실패 시 기존 activation manifest는 그대로다.

예상 구조는 다음과 같다.

```text
data/split/
  manifest.json                         # 현재 활성 snapshot pointer; 유일한 교체 파일
  20260908T...Z-<nonce>/
    news.db
    timeseries.db
    snapshot-manifest.json              # 불변 검증·provenance 보고서
```

## manifest와 검증 기준

manifest에는 원본 경로·크기·mtime·schema version·page count, output별 schema/content SHA-256, table별 원본/출력 row count와 content SHA-256, dataset assignment, integrity/FK 결과, runtime smoke 목록, 의도적 제외 table이 기록된다. 이는 선택된 serving row의 provenance이며 1.7GB 원본 파일 전체의 hash나 완전 분해를 의미하지 않는다.

승격 조건은 모두 참이어야 한다.

- 모든 필수 table/freshness row 존재
- dataset별 active fingerprint 수 = serving table row 수
- 각 table source/output row count와 content hash 일치
- output schema hash 일치
- `foreign_key_check` 0건, `integrity_check=ok`
- 필수 runtime smoke 전부 실행 성공
- 두 output의 dataset assignment가 서로 겹치지 않음

## 웹 routing 및 운영 주의

웹 DB adapter에도 다음 독립 라우팅을 반영하고 실제 로컬 화면에서 확인했다.

- 최신기사와 article drawer detail → `news.db`
- 거래 pulse, 금리·거시 시계열, 건축 인허가 시계열 → `timeseries.db`
- 로그인/승인 → 작은 별도 `data/local-access.db`. 현재 로컬 실행기는 archive를 연결하지 않으며 전용 news DB 사용 시 기사 상세의 archive fallback을 차단한다. 비노출 legacy API는 이번 분리 파일의 제공 범위가 아니다.

각 serving 연결은 read-only로 열고, 활성 `manifest.json`을 한 요청 도중 다시 읽어 서로 다른 snapshot을 섞지 않는다. rollback은 이전 고유 snapshot을 보존한 상태에서 검증된 이전 pointer를 같은 원자적 방식으로 복구한다. snapshot directory를 직접 수정하거나 재사용하지 않는다.
