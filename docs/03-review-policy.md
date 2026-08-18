# 검증·중복·수동검수 정책

## 1. 세 축을 분리

| 축 | 질문 | 예시 |
|---|---|---|
| Confidence | 추출·식별·출처를 고려할 때 얼마나 믿을 수 있는가 | 0.82 |
| Verification | 외부 공식자료가 주장을 확인했는가 | verified / contradicted |
| Review | 사람이 확인하고 어떤 결정을 했는가 | approved / changes_requested |

`confidence=0.98`이어도 `review=unreviewed`일 수 있고, 제한된 근거를 인지한 사람이 `confidence=0.60`인 사건을 승인할 수도 있다.

## 2. 검증 등급

| 등급 | 명칭 | 기준 |
|---|---|---|
| V4 | LEGALLY_VERIFIED | 등기 소유권이전, 공식 실거래, 법적 효력 공시 등으로 핵심 사건 확인 |
| V3 | OFFICIAL_CONFIRMED | DART/KIND/리츠보고서/인허가 API 등에서 핵심 내용 확인 |
| V2 | MULTI_SOURCE_CONFIRMED | 서로 독립적인 출처 2개 이상이 자산·당사자·단계를 일치 보도 |
| V1 | SINGLE_SOURCE | 신뢰 매체 또는 당사자 자료 1개, 공식 확인 없음 |
| V0 | RUMOR_OR_UNRESOLVED | 익명 인용, 검토·소문 단계, 핵심 자산 식별 실패 |

동일 보도자료 전재는 독립 출처로 세지 않는다.

## 3. 필드 단위 assertion

동일 필드의 상충 값을 덮어쓰거나 평균내지 않는다.

```text
transaction_price
├─ 기사 A: 3,200억원 / extracted / V1
├─ 기사 B: 약 3,000억원 / extracted / V1
└─ DART: 3,180억원 / api / V3 / selected
```

각 assertion은 다음을 보존한다.

- 원 값과 정규화 값
- 단위와 금액 정의
- 근거 문서·문장·페이지·JSON path
- derivation: extracted / api / calculated / manual / merged
- confidence
- verification status
- review status
- 현재 선택값 여부

## 4. 자동 수동검수 전환 조건

다음 중 하나면 자동 게시하지 않고 검수 큐로 보낸다.

- 주소·PNU·건축물관리번호가 불완전하거나 자산 후보가 복수
- 동명 법인·SPC·펀드 후보가 복수
- 금액·날짜·당사자·단계가 출처 간 충돌
- 거래가 검토인지 계약인지 종결인지 불명확
- 기사만 있고 공식 검증이 없는 고가·중요 사건
- API는 성공했지만 후보가 검색되지 않음
- 하나의 기사에 여러 자산·여러 사건이 혼재
- 포트폴리오 거래인데 일부 자산만 식별
- 동일 사건 유사도 점수가 자동 병합 임계구간
- 공식 정정·철회·취소 문서 발견
- `CLOSED`, `TITLE_TRANSFERRED`, `USE_APPROVED`, `MAIN_PF_EXECUTED` 등 강한 종결 상태로 승격

## 5. 자산 식별

자동 일치 우선순위:

1. 건축물대장 관리번호
2. PNU/필지 집합
3. 정규화 도로명주소 + 동/본관
4. 좌표거리 + 자산유형 + 면적 허용오차
5. 이름·별칭은 후보 생성에만 사용

이름만 같은 자산은 자동 병합하지 않는다. 주소가 불완전하면 `possible_same_asset` 검수로 보낸다.

## 6. 프로젝트 식별

프로젝트와 물리적 자산을 분리한다.

```text
정규 사업구역명
+ PNU/필지 집합
+ 시행사 또는 SPC
+ 개발용도
```

이 조합을 주요 blocking key로 사용한다. 프로젝트 명칭 변경이나 시행사 교체가 있더라도 필지와 인허가 lineage가 동일하면 같은 프로젝트 이력 후보로 연결한다.

## 7. 기업·펀드·SPC 식별

- DART corp_code, 종목코드, 법인등록번호, 사업자등록번호 우선
- 법인 표기·공백·기호·국영문 별칭은 정규화
- 동일 운용사의 여러 펀드·리츠·SPC를 운용사 하나로 병합 금지
- 명칭 유사도만 높은 후보는 수동 검수

## 8. 이벤트 중복 탐지

자연키 unique constraint로 이벤트를 강제하지 않는다. 같은 자산에서 같은 날 여러 실제 사건이 있을 수 있다.

Blocking feature:

```text
주 카테고리
+ 자산/프로젝트 ID 교집합
+ 이벤트 subtype/stage
+ 날짜 버킷
+ 금액 버킷
+ 핵심 당사자 역할 교집합
+ 제목/근거 문장 유사도
```

후속 기사 처리:

- 같은 단계·같은 사건: 기존 canonical event의 evidence와 assertion 추가
- 단계 변경: 새 이벤트를 생성하고 `previous_event_id` 또는 `transaction_group_id` 연결
- DART 정정: 이전 기록 삭제 금지, `supersedes_event_id` 연결
- 포트폴리오: 거래 이벤트 1개 + 여러 `event_assets`
- 대출약정과 매매계약: 별도 이벤트 + 같은 transaction group

## 9. 비파괴 병합

병합 절차:

1. survivor event 선택
2. 카테고리·자산·프로젝트·관계자 관계 upsert
3. 모든 후보·근거·assertion을 survivor에 연결
4. 충돌 assertion은 모두 보존하고 선택값만 재결정
5. duplicate는 `merged` 상태와 survivor ID 기록
6. 병합자·시각·필드별 결정사유 저장

금지:

- duplicate hard delete
- 약한 근거 assertion 삭제
- 대표 출처 하나로 모든 출처 덮어쓰기
- 충돌 금액·날짜 평균내기

## 10. 카테고리별 핵심 오탐

### 매각·투자
- 우협·MOU·SPA·잔금·소유권이전을 각각 분리
- 매각 희망가·입찰가·계약가·실거래가 구분
- 기업 M&A와 부동산 자산/지분 거래 구분
- 수익증권 양수도와 건물 소유권 이전 구분

### 임대
- 주거 전월세·단기숙박 제외
- 시장 공실률·임대료 해설만 있으면 개별 이벤트 생성 금지
- 이전 검토와 임대차 체결 구분
- 건물 연면적과 실제 임차면적 구분

### 신규공급·인허가
- 준공 예정과 실제 준공 분리
- 착공식과 실착공 분리
- 사용승인·준공·개관 날짜 분리
- 위원회 조건부 의결과 최종 법적 허가 분리
- 주민열람·공람은 승인 완료가 아님

### PF·대출
- 사업장·주소·SPC·시행사 중 구체 단서가 없으면 시장 일반론
- 총 PF 보증잔액을 개별 사업장 금액으로 배분 금지
- 대주단 모집·약정·실행 분리
- 채권최고액과 실제 원금·잔액 구분
- 펀드 만기와 담보대출 만기 구분

## 11. 승인 게이트

canonical event 승인 전 필수:

- 카테고리 1개 이상, 주 카테고리 정확히 1개
- evidence 1개 이상
- 자산 또는 프로젝트 1개 이상, 없으면 예외사유
- unresolved 핵심 mention 없음 또는 override 사유
- event title/date 등 검색 핵심값 선택
- confirmed duplicate 미처리 없음
- 핵심 contradicted assertion 해소 또는 관리자 override
- event approval review 기록

승인은 서비스 트랜잭션 또는 deferred constraint trigger에서 강제한다.
