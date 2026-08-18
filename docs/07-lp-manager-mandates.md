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
