# V2.2 확장형 측정정보 스키마 계약

## 1. 문제

상업용 부동산의 면적은 하나의 속성이 아니다.

```text
토지·대지
- 토지면적
- 필지면적
- 대지면적
- 사업부지면적
- 개발가능면적
- 조경면적

건축·법정
- 건축면적
- 연면적
- 용적률 산정 연면적
- 지상·지하 연면적

층·공간
- 층별면적
- 기준층면적
- 바닥판면적
- 전용면적
- 공용면적
- 사용가능면적

임대·영업
- 임대가능면적
- 순임대면적
- 총임대면적
- 임차면적
- 공실면적

물류
- 상온·저온·냉동 적재면적
- 하역면적
- 도크면적
- 램프면적
- 물류 사무공간

데이터센터
- 화이트스페이스
- 데이터홀
- 서버실
- MMR·통신실
- 전기실
- 기계실
- 지원공간
```

이를 자산 테이블의 고정 컬럼으로 만들면 다음 문제가 발생한다.

1. 새 섹터·용어가 등장할 때마다 migration 필요
2. 같은 개념의 유사용어가 별도 컬럼으로 중복
3. 층·동·단계·구역별 값 표현 불가
4. 계획·실측·건축물대장·임대차 기준 값 충돌
5. 총합·부분합·포함·제외 관계 추적 불가

## 2. 설계 원칙

### 2.1 정의와 값을 분리

```text
measurement_definitions    무엇을 측정하는지
measurement_facts          실제 측정값
```

새 면적 종류는 컬럼을 추가하지 않고 `measurement_definitions` 행을 추가한다.

### 2.2 계층과 관계를 분리

분류 계층은 유사 개념을 묶는다.

```text
AREA
├─ LAND_SITE_AREA
├─ REGULATORY_BUILDING_AREA
├─ FLOOR_SPACE_AREA
├─ LEASING_OCCUPANCY_AREA
├─ LOGISTICS_FUNCTIONAL_AREA
├─ DATA_CENTER_FUNCTIONAL_AREA
├─ RETAIL_FUNCTIONAL_AREA
└─ HOSPITALITY_LIVING_AREA
```

계층만으로 표현하기 어려운 관계는 별도 relation으로 둔다.

```text
SAME_AS
CLOSE_TO
COMPONENT_OF
OVERLAPS
EXCLUDES
DERIVED_FROM
REPLACES
```

### 2.3 측정 종류와 측정 범위를 분리

```text
measurement definition = FLOOR_AREA
spatial unit           = A동 3층
```

```text
measurement definition = DATA_HALL_AREA
spatial unit           = A동 3층 데이터홀 1
```

층별면적을 위해 `floor_1_area`, `floor_2_area` 컬럼을 만들지 않는다.

### 2.4 공간 단위를 계층화

```text
자산·프로젝트
└─ 부지
   ├─ A동
   │  ├─ 지하 2층
   │  ├─ 지상 1층
   │  └─ 지상 3층
   │     ├─ 데이터홀 1
   │     ├─ 전기실
   │     └─ 램프
   └─ B동
```

공간 단위 유형도 사전으로 확장한다.

```text
SITE / PARCEL / BUILDING / WING / FLOOR / UNIT / ZONE
WAREHOUSE_ZONE / STORAGE_ZONE / RAMP / DOCK
DATA_HALL / SERVER_ROOM / ELECTRICAL_ROOM / MECHANICAL_ROOM
```

### 2.5 핵심 분류와 부가 차원을 분리

측정 종류 자체는 `measurement_definition_id`로 분류한다. 층·단계·측정기준·온도대처럼 조합 가능한 속성은 dimension으로 둔다.

```text
measurement_fact_dimensions
- FLOOR_LABEL = 3F
- PROJECT_PHASE = PHASE_1
- MEASUREMENT_STANDARD = BUILDING_REGISTER
- TEMPERATURE_ZONE = FROZEN
- TENANCY_SCOPE = EXCLUSIVE
```

동적 dimension은 자유 JSON이 아니라 정의·선택값·typed value로 검증한다.

### 2.6 원문값과 표준값을 모두 보존

```text
raw_value                  1만평
value_decimal_text         10000
source_unit_code           PYEONG
normalized_value_decimal   33057.85
normalized_unit_code       M2
comparator_code            ABOUT
normalization_version      area-conversion-v1
```

`REAL`은 필터·차트 편의값으로만 사용하고 decimal 문자열을 권위값으로 남긴다.

### 2.7 출처별 충돌값을 보존

```text
건축물대장 연면적  82,430㎡
설계도서 연면적    83,100㎡
기사상 연면적      약 8.2만㎡
```

세 값을 별도 `measurement_facts`로 유지하고 `measurement_fact_selections`가 현재 채택값을 가리킨다.

### 2.8 파생 측정값 계보

```text
총 연면적
= 지상층 면적 합
+ 지하층 면적 합
```

파생값은 계산 결과만 저장하지 않는다.

```text
measurement_derivations
measurement_derivation_inputs
```

계산식 버전과 입력 fact를 남겨 재계산할 수 있어야 한다.

## 3. 테이블 구조

### 3.1 정의 계층

```text
measurement_definitions
measurement_definition_aliases
measurement_definition_relations
measurement_applicability
```

### 3.2 공간 계층

```text
spatial_unit_types
spatial_units
spatial_unit_aliases
```

### 3.3 Dimension 계층

```text
measurement_dimension_definitions
measurement_dimension_options
measurement_fact_dimensions
```

### 3.4 값·선택·파생 계층

```text
measurement_facts
measurement_fact_selections
measurement_derivations
measurement_derivation_inputs
```

## 4. Measurement definition 필수 속성

```text
code
name_ko
parent_definition_id
dimension_code
canonical_unit_code
measurement_family
aggregation_behavior
sector_scope
is_abstract
version
valid_from / valid_to
```

### 집계 방식

- `ADDITIVE`: 공간·시간 합계 가능
- `SEMI_ADDITIVE`: 일부 차원에서만 합계 가능
- `NON_ADDITIVE`: 비율·기준층처럼 단순 합계 금지
- `RATIO`: 분자·분모 계보 필요
- `SNAPSHOT`: 특정 시점 상태값

예를 들어:

- 층별 실제 바닥면적: 공간축 합산 가능
- 기준층면적: 대표값이므로 합산 금지
- 전용률: 비율
- 임차면적: 계약·시점에 따라 중복 가능하여 무조건 합산 금지

## 5. Measurement fact의 대상

한 fact는 정확히 하나의 대상을 가진다.

```text
asset_id
project_id
spatial_unit_id
event_id
region_id
```

가능하면 층·동·구역 측정값은 `spatial_unit_id`를 사용한다. 자산 전체 값만 `asset_id`를 사용한다.

## 6. 유사용어 처리

`measurement_definition_aliases`에는 다음을 기록한다.

```text
raw term
normalized term
canonical definition
asset class context
source context
mapping confidence
requires review
valid period
```

예:

```text
상면면적
- 데이터센터 문맥: DATA_HALL_AREA 후보
- 리테일 문맥: SALES_FLOOR_AREA 후보
```

따라서 `상면`이라는 단어만 보고 전역적으로 하나의 정의에 자동 연결하지 않는다.

## 7. 구분해야 하는 축

다음은 서로 대체할 수 없는 개념이다.

- 토지면적 vs 대지면적 vs 사업부지면적
- 건축면적 vs 연면적
- 전체 연면적 vs 용적률 산정 연면적
- 총임대면적 vs 순임대면적 vs 실제 임차면적
- 전용면적 vs 공용면적
- 기준층면적 vs 특정 층 면적
- 창고면적 vs 실제 적재면적
- 램프면적 vs 도크·하역면적
- 화이트스페이스 vs 데이터홀 vs 서버실
- 계획면적 vs 허가면적 vs 준공·대장면적 vs 운영 실측면적

## 8. 새 종류 추가 절차

1. 기존 definition·alias 검색
2. 완전 동일하면 alias 추가
3. 상위 개념과 같고 세부 범위만 다르면 dimension 검토
4. 독립적인 의미·집계법·출처 기준이면 새 definition 추가
5. parent와 semantic relation 지정
6. 적용 자산군 지정
7. 원문 예시와 반례 기록
8. 검수 후 활성화

새 종류 추가 시 DDL migration은 필요하지 않다. 사전 데이터 변경만 수행한다.

## 9. 통계 원칙

통계는 `measurement_facts` 전체가 아니라 승인·채택된 값에서 계산한다.

```text
measurement_fact_selections
→ measurement_definitions
→ spatial scope
→ dimensions
→ asset class / region / as-of date
```

집계 전에 반드시 확인한다.

- 동일 자산·동·층·구역 중복 여부
- measurement definition 동일성
- 단위 정규화
- 기준시점
- planned vs actual
- source 기준
- aggregation behavior
- 파생값과 구성값의 이중 합산
