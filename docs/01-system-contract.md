# Stage 1 시스템 계약

## 1. 목적

대한민국 상업용 부동산 시장을 `SALE`, `LEASE`, `NEW_SUPPLY`, `PERMIT`, `PF`, `LOAN`, `INVESTMENT` 카테고리별로 주기 검색한다. 검색 결과에서 여러 자산·프로젝트·기업 사건을 발견하고, 원문 근거·공식 검증·수동 승인 이력을 보존하여 이벤트 DB로 확정한다.

## 2. 권위 원칙

1. 수집의 출발점은 자산 목록이 아니라 **버전이 있는 카테고리 검색 규칙**이다.
2. 기사·공시·고시는 사실 자체가 아니라 사건을 주장하는 `source_document`다.
3. 문서 한 건은 0개 이상의 `event_candidate`를 만들 수 있다.
4. 후보는 자산·프로젝트·관계자 mention을 먼저 만들고, 표준 마스터와 후행 연결한다.
5. 승인 이벤트는 원본 후보·근거·상충 값을 삭제하지 않는다.
6. 한 이벤트는 여러 카테고리·프로젝트·자산·관계자와 연결될 수 있다.
7. 한 자산은 시간에 따라 여러 이벤트에 반복 등장할 수 있다.
8. 검색 실패, 무결과, API 미승인, API 무응답, API 불일치, 출처 미언급을 구분한다.
9. 사람이 승인해도 근거 품질이 낮으면 confidence를 1.0으로 올리지 않는다.
10. 권리 근거가 없는 기사 전문은 영구 저장하지 않는다.

## 3. 전체 흐름

```text
Search Rule Registry
  ↓
Search Run
  ↓
Source Document + Search Lineage
  ↓
Document Classification
  ├─ 시장 일반론/통계 → context document
  ├─ 무관/오탐 → rejected candidate
  └─ 구체 사건 → 1..N event candidates
        ↓
Asset / Project / Entity Mention Resolution
        ↓
Duplicate Event Blocking + Similarity
        ↓
Official API Verification
        ↓
Manual Review
        ↓
Canonical Event Approval
        ↓
Published Feed / Map / Briefing
```

## 4. 단계 계약

### Stage A — 카테고리 검색

**입력**
- 활성 검색 규칙과 버전
- 카테고리·행위어·자산어·지역 묶음
- 소스별 수집 정책과 cursor

**출력**
- `search_runs`
- 결과 URL·순위·검색 스니펫
- 완료·부분성공·실패·무결과 상태

**필수 QA**
- 동일 규칙·동일 cursor의 중복 실행 방지
- 검색 결과 0건과 호출 실패 분리
- 검색 키·토큰을 쿼리 원문이나 로그에 저장하지 않음

### Stage B — 원문 등록

**입력**
- 검색 결과, RSS 항목, 공식 API 문서

**출력**
- canonical URL과 내용 해시 기준 문서 버전
- 제목·발행사·발행/수집 시각·문서 유형
- 접근·저장·재사용 정책
- 최소 근거 문장 또는 허용된 원문 저장 위치

**필수 QA**
- URL만으로 문서 버전을 덮어쓰지 않음
- 전재·수정본은 문서 그룹으로 연결
- 로그인·CAPTCHA·유료벽 우회 금지

### Stage C — 후보 추출

**입력**
- 원문 메타데이터, 스니펫, 허용된 본문 또는 공시 원문

**출력**
- 문서별 0..N `event_candidates`
- 복수 카테고리 확률
- 자산·프로젝트·관계자 mention 0..N
- 날짜·금액·면적 등 field assertion과 근거 locator

**필수 QA**
- 구체 자산·프로젝트·당사자 근거 없는 시장 일반론은 이벤트 생성 금지
- `계획`, `추진`, `약정`, `실행`, `종결` 상태 구분
- 기사 한 건을 자산 한 건으로 가정하지 않음

### Stage D — 식별 및 중복 후보

**입력**
- 원문 mention, 주소·좌표·식별번호, 기존 마스터

**출력**
- resolved / candidate_match / ambiguous / unresolved 상태
- 동일 사건 후보 pair와 similarity feature

**필수 QA**
- 빌딩명만 같으면 자동 자산 병합 금지
- 법인·펀드·SPC를 이름 유사도만으로 병합 금지
- 프로젝트와 물리 자산 분리
- 포트폴리오 거래는 상위 사건 1개와 복수 자산 관계로 표현

### Stage E — 공식 검증

**입력**
- 후보 assertion, 표준 자산·프로젝트·기업 식별자

**출력**
- provider·endpoint·요청 fingerprint별 검증 실행
- confirmed / contradicted / not_found / inconclusive
- assertion별 검증 연결

**필수 QA**
- HTTP 성공을 사실 confirmed로 처리하지 않음
- API 미검색을 사실 부재로 처리하지 않음
- 실거래 신고가 지분·수익증권 거래를 포괄한다고 가정하지 않음
- 등기 채권최고액을 실제 대출원금으로 저장하지 않음

### Stage F — 수동 검수 및 승인

**입력**
- 후보, 근거, 중복 후보, API 검증, 상충 assertion

**출력**
- 승인·수정요청·기각·병합 결정
- 선택 assertion과 결정 사유
- canonical event와 후보 lineage

**승인 게이트**
- 주 카테고리 정확히 1개
- 근거 1개 이상
- unresolved 핵심 mention 없음 또는 예외 사유
- 이벤트 자산/프로젝트 1개 이상 또는 명시적 예외
- 확인된 중복 후보 미처리 없음
- 핵심 필드 충돌 시 override 사유
- event approval 기록

## 5. 상태 모델

### 검색 실행

`queued → running → completed | partial | failed`

### 후보

`discovered → extracted → needs_resolution → ready_for_review → approved | rejected | merged`

### 검증

`unverified → pending → verified | contradicted | inconclusive`

### 검수

`unreviewed → in_review → approved | rejected | changes_requested`

### 이벤트 게시

`draft → approved → published → withdrawn | merged`

이 네 상태축은 합치지 않는다.

## 6. 운영 주기 목표

- 1~3시간: 뉴스 검색·Google News RSS·단계변화 키워드
- 매일: DART·KIND·공식 보도자료·지자체 고시
- 주 1회: 건축 인허가·착공·사용승인·실거래 후행 매칭
- 월 1회: 등기 수동확인 큐, 장기 미해결 우협·대출만기·PF 재검토

주기는 소스 약관·호출한도와 운영 비용에 따라 규칙별로 조정한다.

## 7. 산출물 구분

**공식 산출물**
- 승인 이벤트
- 선택 assertion
- 모든 대안 assertion
- 근거와 API 검증
- 자산·프로젝트·관계자 연결
- 검수 및 병합 이력

**내부 체크포인트**
- raw search response
- 검색 cursor
- extraction payload
- 임베딩·유사도 feature
- 재시도 로그

**현재 구현 상태**
- 본 문서·규칙 JSON·SQL 스키마: 작성
- 실제 수집기·분류기·검수 UI·스케줄러: 미구현
