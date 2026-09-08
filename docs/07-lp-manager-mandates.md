# 국내 LP 위탁운용사 선정 원장 V2.5

## 목적

공개 위탁운용 절차를 통해 LP가 특정 운용사에 제공한 자본 source와 실제 fund·REIT·SPC·실물자산 딜 투입을 연결한다.

```text
LP → mandate → track → selected manager → fund/REIT → disclosed deployment → sale process/event/asset
```

## 금액 해석

다음 금액은 서로 대체할 수 없다.

- `PROGRAM_TOTAL`: 프로그램 전체 공고 규모
- `LP_COMMITMENT_TOTAL`: LP 전체 출자·약정액
- `TRACK_LP_COMMITMENT`: 전략 track별 출자·배정액
- `ALLOCATION_PER_MANAGER`: 운용사당 예정 배정액
- `SELECTION_LP_COMMITMENT`: 특정 선정 운용사에 귀속된 확인 배정·약정액
- `TARGET_FUND_SIZE`: LP 외부자금·GP 출자를 포함할 수 있는 목표 펀드규모
- `MANAGER_COMMITMENT`: GP 자기출자
- `CO_INVESTMENT_RESERVE`: 공개된 공동투자 별도 재원

## 잔여 source projection

`v_lp_mandate_source_balance`는 다음 조건을 모두 충족할 때만 숫자를 표시한다.

1. source가 `SELECTION_LP_COMMITMENT`
2. source 금액이 `EXACT`
3. deployment가 `LP_SOURCE_DEPLOYMENT`
4. deployment 금액이 `EXACT`
5. 양쪽 통화가 동일
6. 양쪽 모두 `APPROVED`

결과명은 source 단계에 따라 `UNTRACED_AWARDED_NOT_CONFIRMED_COMMITTED_OR_AVAILABLE` 또는 `UNTRACED_COMMITTED_NOT_CONFIRMED_AVAILABLE`이다. 이는 **확인된 딜에 아직 연결하지 못한 금액**이지, 운용 가능한 dry powder 또는 미집행약정액의 확정값이 아니다. 비용, reserve, 환헤지, follow-on, 취소·감액, 회수·재투자 조건이 공개되지 않으면 `AVAILABLE_CAPITAL`로 표시하지 않는다.

## 승인 manifest gate

- 상태가 `APPROVED`
- reviewer와 approver가 모두 기록됨
- 공식 공고·첨부·결과·공시 원문의 `exact_text` 보존
- canonical amount는 정규화 decimal string과 원문 표현을 함께 보존
- guideline raw text가 source exact text의 실제 substring
- 선정 운용사 이름만 같다는 이유로 특정 딜을 연결하지 않음
- vehicle·시점·금액 또는 명시 문구가 맞을 때만 deployment 승인
- news title/snippet은 importer 입력 불가

## 검증정보와 추측성 정보의 분리

claim별로 다음 세 레이어를 사용한다.

1. `CANONICAL_VERIFIED`
   - 공식 공고·결과·공시·규제 filing·감사보고서 또는 거래 당사자 원문으로 claim 자체가 확인됨
   - 승인 manifest와 live authority DB 적재 가능
   - 기사는 보조 출처로 함께 보존할 수 있으나 단독 canonical 근거가 될 수 없음
2. `VERIFICATION_CANDIDATE`
   - 기사·리서치·검색 snippet·업계 보도로 발견됐으나 공식 원문이 아직 없음
   - `artifacts/lp-mandate-speculative/` 또는 `fixtures/lp-mandate-candidates/`에 별도 보관
   - `verification_needed`, `last_checked_at`, `source_family`, `resolution_status`를 기록
3. `REJECTED_OR_CONTRADICTED_ARCHIVE`
   - 반증·철회·오탐·범위 제외 자료
   - 삭제하지 않고 이유와 반증 source를 남겨 재발견·재검토 가능하게 함

공식 RFP가 mandate와 guideline을 검증하더라도 기사에만 나온 선정사는 별도 candidate다. 반대로 기사 claim과 일치하는 공식 선정결과가 발견되면 공식 claim을 canonical로 승격하고 기사는 corroboration provenance로 유지한다. 전재 기사 여러 건은 독립 검증으로 세지 않는다.

정책은 연도에 종속되지 않는다. `2020~2025`는 현재 campaign 범위일 뿐이며, 동일 gate를 2020년 이전에도 적용한다. 오래된 자료가 웹에서 발견되지 않았다는 사실은 해당 mandate가 없었다는 근거가 아니므로 era별 `SOURCE_ARCHIVE_GAP`을 coverage에 기록한다.

## Import

```bash
python collector/approved_lp_mandate_manifest.py \
  data/market.db fixtures/approved-lp-mandates/<manifest>.json \
  --dry-run

python collector/approved_lp_mandate_manifest.py \
  data/market.db fixtures/approved-lp-mandates/<manifest>.json \
  --allow-live
```

Live import 전에는 SQLite backup API snapshot을 생성한다. importer는 stable-ID content conflict, FK 오류, partial write를 rollback하며 반복 import 시 신규 행이 0이어야 한다.

## 주요 테이블

- `lp_mandates`
- `lp_mandate_tracks`
- `lp_mandate_guidelines`
- `lp_mandate_selections`
- `lp_mandate_selection_members`
- `lp_mandate_selection_vehicles`
- `lp_mandate_amounts`
- `lp_mandate_deployments`

## 조회 view

- `v_lp_mandate_deal_sources`: LP→운용사→vehicle→딜 연결
- `v_lp_mandate_source_balance`: 검증된 LP 배정액 대비 공개 확인 deployment 및 미추적액

## 후속 문서 기반 선정 판단

공식 선정 결과가 아직 없어도 기사·기관 문서·거래 당사자 문서에서 동일 기관 자금의 입찰 또는 집행이 확인될 수 있다. 이때 결과는 canonical selection에 바로 넣지 않고 assessment claim으로 보존한다.

```text
기관·mandate → 동일 track·vintage → 후속 문서 → vehicle·deal → 운용사 역할 → 판정
```

판정 단계는 다음과 같다.

| 판정 | 필수 근거 | 해석 |
|---|---|---|
| 공식 선정 | 기관 공식 결과가 운용사를 직접 명시 | canonical selection |
| 집행 기반 선정 유추 | 동일 LP·mandate·track, 후속 약정·집행, vehicle 또는 deal, 운용사 identity, 직접 원문, 상충 없음 | 공식 결과는 아니지만 선정 가능성이 높은 reviewable inference |
| 입찰 참여 | 동일 LP 자금과 운용사의 지원·shortlist·입찰 연결 | 참여 사실일 뿐 선정 아님 |
| 검토 필요 | 기사상 선정 보도 또는 일부 연결만 존재 | 공식 결과나 집행 교차검증 필요 |

입찰 참여만으로 선정 유추를 만들지 않는다. `COMMITTED`, `EXECUTED`, `REALISED`처럼 자금 사용이 실제 단계로 진행됐고 기관·track·vehicle/deal·운용사가 모두 연결될 때만 집행 기반 유추가 가능하다. 자금 basis는 반드시 `LP_SOURCE_DEPLOYMENT`여야 하며 `FUND_EQUITY_DEPLOYMENT`, GP 자기자금, 공동투자금, 출처 미상 자금은 선정 유추 근거로 쓰지 않는다. 다른 vintage나 전략일 가능성, 운용사가 GP가 아니라 단순 입찰 컨소시엄 구성원일 가능성, 자기자금과 기관자금의 혼재가 있으면 `CONTRADICTION_NOTE`를 남기고 판단을 보류한다.

assessment claim은 다음 predicate를 사용한다.

- `LP_MANDATE_MANAGER_BID_PARTICIPANT`
- `LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT`

필수 argument는 `MANDATE_CODE`, `MANDATE_TRACK`, `FOLLOW_UP_ACTION`, `FUNDING_BASIS`, `INFERENCE_RULE_VERSION`이며, `LINKED_VEHICLE` 또는 `LINKED_DEAL` 중 하나 이상을 저장한다. 필요하면 `CONTRADICTION_NOTE`도 함께 보존한다. 선정 유추 claim은 `certainty_code=INFERRED`, `extraction_method=CALCULATED`, `verification_status=VERIFIED`, `review_status=ACCEPTED`를 모두 충족해야 화면에서 `집행 기반 선정 유추`로 표시된다. 그 전에는 `검토 필요`로만 보이며 `lp_mandate_selections`로 승격하지 않는다. `SUPERSEDED`, `CORRECTED`, `REJECTED`, `CONTRADICTED` 상태는 유추 합계에서 제외하거나 검토 대상으로 내린다.

판단 순서는 결정론적으로 고정한다.

1. 기관 공식 공고·프로그램 문서와 mandate code를 확인한다.
2. 동일 vintage·전략의 정확한 track을 연결한다. track이 없거나 다르면 판단을 보류한다.
3. 후속 원문에서 `APPLIED`·`SHORTLISTED` 또는 `COMMITTED`·`EXECUTED`·`REALISED`를 구분한다.
4. 기관 출처 자금(`LP_SOURCE_DEPLOYMENT`)과 vehicle 또는 deal을 연결한다.
5. 해당 vehicle·deal의 실제 운용사를 식별한다.
6. 공식 결과면 `공식 선정`, 집행 조건 전체 충족이면 `집행 기반 선정 유추`, 입찰만 확인되면 `입찰 참여`, 나머지는 `검토 필요`로 표시한다.

2026-08-25 운영 DB 기준 화면 집계는 공식 선정 5건, 기사상 선정 후보 6건, LP 자금 연계 입찰 0건, 확인된 집행 0건이다. 기사상 후보는 검토 대상으로만 보이며 공식 선정 합계에 포함하지 않는다.
