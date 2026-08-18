# V2 SQLite 누적 원장 데이터 계약

## 1. 목적

웹 기사·공시·고시·API에서 발견한 한국 상업용 부동산 정보를 단순 본문 검색 결과가 아니라 **식별 가능한 엔터티·typed claim·시장 이벤트·시계열 관측치**로 누적한다. 초기에는 목록과 타임라인을 제공하고, 데이터가 쌓인 후 동일 원장에서 통계를 계산한다.

V2는 기존 PostgreSQL Stage 1 스키마를 수정한 버전이 아니다. 로컬 서버 없이 운영하는 SQLite 권위 원장으로 새로 설계한다.

## 2. 전체 계층

```text
Search job / Macro job
  → Collection run
    → Source document version
      → Extraction run
        → Mention span
          ├─ 자산명·프로젝트명·회사명·지역·자산군
          └─ 날짜·금액·면적·비율·수량
        → Mention relation / Typed claim
          → Canonical asset / project / organization / region
            → Event mention
              → Canonical market event
                → Event transition history

Macro source
  → Macro series
    → Observation vintage
      → Daily / weekly snapshot
```

## 3. 절대 원칙

1. 원문과 추출 결과를 분리한다.
2. 전체 형태소 토큰을 무조건 저장하지 않는다. 식별·검증에 필요한 **mention span**을 권위 추출 단위로 쓴다.
3. 원문 표현과 정규화 값을 동시에 보존한다.
4. 가격·면적·날짜는 숫자 하나가 아니라 의미와 단위를 포함한 claim으로 저장한다.
5. 기사 한 건은 0개·1개·여러 이벤트를 포함할 수 있다.
6. 동일 이벤트는 여러 문서의 주장을 가질 수 있다.
7. 자산, 개발사업, 회사는 서로 다른 마스터다.
8. 회사의 역할은 회사 마스터가 아니라 이벤트 참여관계에 저장한다.
9. 예정·추정·호가·감정가·계약가·종결가는 서로 다른 의미다.
10. 매크로 수정치는 기존 관측값을 덮어쓰지 않고 vintage로 추가한다.
11. 승인 전 추출값과 승인 후 표준값을 모두 보존한다.
12. 모든 통계는 승인된 이벤트와 명시된 기준일을 사용한다.

## 4. 토큰화와 의미 추출

### 4.1 저장하지 않아도 되는 것

일반적인 전체 문장 토큰화 결과는 모델 재현이나 검색 인덱스가 꼭 필요하지 않으면 DB 권위 데이터로 저장하지 않는다.

```text
[용인] [남사] [데이터센터] [본] [PF] [6,200] [억원] [약정]
```

이 토큰 배열만으로는 `6,200억원`이 사업비인지 PF 약정액인지 알 수 없다.

### 4.2 저장해야 하는 것

```text
MENTION PROJECT     "용인 남사 데이터센터"  span 0..13
MENTION EVENT_STAGE "본PF 약정"              span 14..20
MENTION MONEY       "6,200억원"              span 21..29

RELATION
  subject: 용인 남사 데이터센터
  predicate: PF_COMMITMENT_AMOUNT
  object: 6,200억원
```

mention에는 다음을 저장한다.

- `mention_type`
- 원문 `surface_text`
- 정규화 전후 값
- 문자 시작·종료 위치
- 문장 번호
- 추출 모델·규칙 버전
- confidence
- 연결된 canonical master
- resolution 상태와 근거

### 4.3 Typed claim

가격·면적·날짜는 다음처럼 저장한다.

```text
subject_kind       PROJECT
subject_id         project_123
predicate_code     PF_COMMITMENT_AMOUNT
value_type         MONEY
numeric_value      620000000000
currency_code      KRW
unit_code          KRW
raw_value          "6,200억원"
value_qualifier    AGREED
certainty_code     REPORTED
valid_time_start   2026-08-13
evidence_mention   mention_456
```

면적 예시:

```text
predicate_code     GROSS_FLOOR_AREA
numeric_value      82430
unit_code          M2
raw_value          "연면적 8만2,430㎡"
area_scope         WHOLE_ASSET
```

매각 가격 예시:

```text
ASKING_PRICE       희망가
APPRAISAL_VALUE    감정평가액
BID_PRICE          입찰가
CONTRACT_PRICE     계약 체결가
CLOSING_PRICE      거래 종결가
PRICE_ESTIMATE     언론·시장 추정가
```

서로 덮어쓰지 않는다.

## 5. 표준 마스터

### 5.1 Asset

물리적 건물·토지·시설이다.

- canonical name
- 도로명·지번주소
- 법정동 코드
- 좌표
- 건축물관리번호
- 필지키
- 자산군·세부유형
- 별칭과 이전 명칭

### 5.2 Project

개발·리모델링·복합사업·포트폴리오 등 사업 단위다.

- 하나의 프로젝트가 여러 필지·건물 포함 가능
- 같은 건물이 여러 시점의 프로젝트와 연결 가능
- 프로젝트 전체 면적을 개별 건물 면적으로 복사 금지

### 5.3 Organization

회사, SPC, 펀드, 리츠, 금융기관, 정부기관 등이다.

- canonical name
- 법인번호·사업자번호
- DART corp code·종목코드
- 별칭·영문명·브랜드명

`매도자`, `매수자`, `임차인`, `대주`, `차주`, `시행사`, `시공사`는 조직 속성이 아니라 이벤트별 role이다.

### 5.4 Region

행정구역을 문자열만으로 저장하지 않는다.

- 국가
- 시도
- 시군구
- 읍면동
- 법정동 코드
- 상위 지역 ID
- 시장 권역(CBD, GBD, YBD 등)은 별도 region set으로 연결

## 6. Event와 Event mention

### Event mention

한 문서가 주장한 사건이다.

- 문서·추출 실행
- 사건 유형과 단계 후보
- 언급된 날짜
- 원문 evidence span
- 자산·프로젝트·참여자 mention
- 추출 confidence

### Canonical event

여러 문서가 말하는 동일한 실제 사건이다.

```text
하나의 매각주관사 선정
├─ 전문매체 기사
├─ 운용사 보도자료
└─ 후속 기사
```

### Event transition

현재 상태를 덮어쓰지 않고 전이를 누적한다.

```text
SALE_REVIEWED
→ ADVISOR_SELECTED
→ PRELIMINARY_BID
→ PREFERRED_BIDDER_SELECTED
→ CONTRACT_SIGNED
→ CLOSED
```

각 전이에 `effective_date`, `announced_at`, `expected_date`, `evidence`, `confidence`, `review_status`를 저장한다.

## 7. 날짜 의미

다음 날짜는 반드시 분리한다.

| 필드 | 의미 |
|---|---|
| `published_at` | 문서 발표 시각 |
| `collected_at` | Hermes 수집 시각 |
| `event_date` | 실제 사건 발생일 |
| `effective_date` | 법적·계약상 효력일 |
| `expected_date` | 예정일 |
| `period_start/end` | 통계 관측 대상 기간 |
| `released_at` | 매크로 통계 발표일 |
| `vintage_at` | 해당 버전 수집·발표 시점 |
| `approved_at` | 수동 검수 승인 시각 |

날짜 정밀도도 `DAY`, `MONTH`, `QUARTER`, `YEAR`, `RANGE`, `UNKNOWN`으로 저장한다.

## 8. 매크로 시계열

### Series

지표 정의는 관측값과 분리한다.

```text
series_code       BOK_BASE_RATE
metric_code       INTEREST_RATE
frequency         EVENT
unit_code         PERCENT
region_id         KOREA
asset_class_id    NULL
adjustment_code   NONE
```

상업용 부동산 지표 예시:

- 기준금리·국고채·회사채·CD·COFIX
- 거래량·거래금액
- 임대료·공실률·cap rate
- 건축허가·착공·준공·사용승인 면적
- 신규공급·예정공급
- PF 연체율·대출잔액
- 건설비지수·지가·소비·고용

### Observation vintage

```text
series_id       vacancy_gbd_office
period_start    2026-04-01
period_end      2026-06-30
numeric_value   2.7
unit_code       PERCENT
released_at     2026-07-20
vintage_at      2026-07-20
revision_no     0
```

수정 발표가 나오면 같은 기간에 `revision_no = 1`을 추가한다. 기존 행을 수정하지 않는다.

## 9. 주기적 스냅샷

### Raw snapshot

일간·주간 실행 당시의 관측 가능한 상태를 고정한다.

- snapshot date/time
- cadence
- collection run
- 포함된 macro observation vintage
- 포함된 승인 이벤트 상태
- 생성 로직 버전

### Aggregate snapshot

향후 화면 속도를 위해 승인 이벤트로부터 계산한 지표를 저장할 수 있다.

```text
snapshot_date    2026-08-14
metric_code      EVENT_COUNT
category         SALE
region            SEOUL
asset_class       OFFICE
numeric_value     12
```

원천 이벤트를 대체하지 않으며 언제든 재계산 가능해야 한다.

## 10. 초기 목록과 향후 통계

초기 UI는 다음 view를 사용한다.

- `v_event_feed`
- `v_asset_timeline`
- `v_project_timeline`
- `v_current_event_state`
- `v_latest_macro_observation`

데이터 축적 후 다음을 추가한다.

- 월별 이벤트 건수·금액
- 단계 전환율과 소요기간
- 지역·자산군별 거래·공급·PF 규모
- 회사별 역할·활동량
- 매크로 지표와 시장 이벤트의 시차 비교

## 11. Portable HTML 연결

```text
market.db                  누적 권위 원장
market-dashboard.html      고정 UI
market-data.js             승인된 목록·타임라인·최신 매크로 export
```

HTML은 DB를 대체하지 않는다. Hermes 주기 작업은 DB에 append/upsert하고 `market-data.js`만 원자적으로 교체한다.

## 12. 승인 게이트

자동 추출이 canonical master나 확정 통계를 바로 수정하지 않는다.

```text
EXTRACTED
→ RESOLUTION_REQUIRED
→ REVIEW_READY
→ APPROVED / REJECTED
```

다음은 수동검수 대상으로 보낸다.

- 동명이 자산·회사
- 주소·필지 불일치
- 가격 의미 불명확
- 프로젝트 전체와 개별 자산 면적 혼동
- 예정일과 실제일 불명확
- 단일 비공식 출처의 종결 상태
- 매크로 단위·계절조정·기준시점 변경

## 13. V2.1 독립 검토 반영

### Claim은 n항 관계

거래를 `(subject, predicate, object)` 하나로 축소하지 않는다. `claim_arguments`에 역할별 argument를 둔다.

```text
SALE claim
├─ ASSET
├─ BUYER
├─ SELLER
├─ PRICE
├─ EFFECTIVE_DATE
└─ ADVISOR
```

`claim_evidence`는 하나의 claim에 direct·context·attribution·qualifier·contradiction 근거 mention을 여러 개 연결한다.

### 정확한 숫자와 범위

`REAL`은 통계 편의값이며 권위값은 decimal 문자열로도 보존한다.

```text
raw_value
value_decimal_text
lower_decimal_text / upper_decimal_text
comparator_code
unit_code / normalized_unit_code
normalization_version
```

### 매크로 release와 revision

```text
macro_series
→ macro_releases             발표물·원문 hash·수정 발표 계보
→ macro_observations         period·observed_on·수정 observation
→ snapshot_macro_items       특정 as-of 시점에 선택된 revision
```

- `period_start/end`: 지표가 설명하는 기간
- `observed_on`: 출처가 실제 기준일을 명시한 경우에만 입력
- `released_at`: 출처 발표시점
- `collected_at`: 시스템 확보시점
- `vintage_at`: 해당 observation revision의 내부 vintage

`macro_releases`와 `macro_observations`는 append-only trigger로 UPDATE·DELETE를 차단한다. 정정은 `revises_release_id`와 `supersedes_observation_id`를 가진 새 행으로 저장한다.

### SQLite 운영

모든 연결은 트랜잭션 전에 다음을 실행한다.

```sql
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

WAL은 단일 writer를 전제로 사용하며 실행 중 `.db` 파일을 직접 복사하지 않는다. `db/v2/backup_db.py`의 SQLite backup API로 일관된 사본과 SHA-256 manifest를 생성한다.

## 14. V2.2 확장형 측정정보

면적·용량·수량·비율 등 자산 속성은 고정 컬럼이 아니라 다음 계층으로 관리한다.

```text
measurement definition taxonomy
→ asset/project spatial hierarchy
→ typed measurement fact
→ dynamic dimensions
→ selected fact / derivation lineage
```

상세 계약과 면적 분류 기준은 [`05-v2-measurement-model.md`](./05-v2-measurement-model.md)를 권위 문서로 사용한다. 새 측정 종류는 `measurement_definitions`와 관련 사전 행을 추가하며 `ALTER TABLE`을 요구하지 않는다.
