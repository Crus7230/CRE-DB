# 부동산 시장 인텔리전스 정기 조사 운영계획

## 1. 현재 운영 원칙

- 권위 원장(main): Supabase PostgreSQL `market_intelligence` schema
- 로컬 sub: `data/market.db` SQLite 검증 snapshot. 평시에는 조회·분석·비상복구 후보로만 사용
- 동기화 방향: Supabase → SQLite 단방향 전체 snapshot. SQLite 변경을 자동으로 main에 올리지 않음
- 적재 방식: append-only source document/version + 보수적 canonical 승격
- 기간 의미: 문서 발행일, 사건일, 거래일, 공시일, 수집시각을 분리
- 수집 transaction commit 후 관계정합화를 별도 감사 가능한 run으로 실행
- 중복·실패·무응답을 정상 0건과 구분
- SQLite 파일 작업은 backup API와 검증된 원자 교체만 사용
- PostgreSQL 초기 이관 및 local sub 갱신 결과는 `artifacts/` JSON으로 감사 가능하게 보존
- 기존 SQLite 전용 collector는 PostgreSQL writer adapter 적용 전에는 운영 수집에 사용하지 않는다. 부득이한 실행은 별도 staging DB에서 수행하고 검증된 main 반영 절차를 거친다

## 2. 조사 주기

### 매일 06:30 KST — 뉴스 discovery

- SALE, LEASE, NEW_SUPPLY, PERMIT, PF, LOAN, INVESTMENT
- 최근 3일을 일 단위 partition으로 중첩 조회
- RSS title·publisher·URL·published-at·snippet 저장
- source identity로 중복 제거
- extraction 후 관계정합화

### 평일 08:00·18:00 KST — OpenDART

- 당일 및 최근 3일 재조회
- 유형자산 양도·양수·취득, 영업양도·영업양수
- 정정공시는 기존 row를 덮지 않고 새 document version으로 append
- 원문 실패는 1일·3일·7일 후 재시도하고 월간 마감 때 한 번 더 확인

### 매주 월요일 02:00 KST — MOLIT

- 당월·직전월·직전 2개월 재조회
- 신고 지연·취소·정정 반영
- 비주거만 분석 대상으로 유지
- 건물면적 ≤1,000㎡ 제외, 1,000~3,300㎡ 검토, >3,300㎡ 유지
- 동일 주소·일자·금액 거래군 합계가 3,300㎡를 넘으면 구성행도 검토

### 매주 일요일 03:00 KST — silent-gap recovery

- 최근 14일 결과 검사
- 검색 상한 근접, 비정상 0건, 평시 대비 급감, API/parser 불일치, 원문 실패를 재조회
- 필요 시 주·일·query bundle 단위로 partition 세분화

### 매월 5일 02:00 KST — 직전월 마감

1. RSS recovery
2. DART 원문 실패 재시도
3. MOLIT 직전월 전체 재조회
4. 최신 document version만 활성 추출
5. superseded mention 정리
6. 거래 scope 재적용
7. 매각 프로세스 후보 생성
8. 관계정합화
9. 월별 macro 생성
10. coverage·integrity·FK·중복·idempotency QA
11. SQLite backup API 월말 backup
12. 월간 coverage report 저장

### 분기 — 체계 감사

- category query·신조어·동의어
- 신규 공식 원천
- 지역코드 변경
- RSS 상한과 source-family 중복
- review queue 적체
- false positive와 scope rule
- organization·asset alias 품질
- 기관 LP mandate→manager→vehicle→deployment 추적 보고서 갱신

### 반기·연간

- 반기: campaign closure, source coverage matrix, continuity, relation gap, 전체 QA, backup
- 연간: taxonomy·공식 archive·미해결 gap 재검토와 장기 시계열 확정

## 3. Backup 보존

- 수집 전 임시 backup: 최근 4개
- 주간 backup: 최근 4주
- 월말 backup: 최근 12개월
- 분기말·연말 backup: 장기 보존
- 대형 batch 후 WAL checkpoint
- 월 1회 이상 integrity/FK 검사
- 원문·claim·version은 용량 사유로 임의 삭제하지 않음

## 4. 캠페인 완료 조건

```text
campaign_complete =
  source coverage recorded
  + extraction completed
  + entity resolution completed
  + relation reconciliation completed
  + unresolved relation gaps recorded
  + canonical/candidate segregation checked
  + FK/integrity/idempotency QA passed
```

명령 exit 0이나 문서 수집만으로 완료 처리하지 않는다.
