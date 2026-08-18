# 발견·검증 소스 매트릭스

## 1. 소스 역할

| 역할 | 정의 |
|---|---|
| 발견 | 시장 사건 후보를 빠르게 찾는 채널. 단독으로 법적 확정하지 않음 |
| 당사자 확인 | 거래·사업 당사자의 공식 보도자료·공시 |
| 공식 검증 | 정부·거래소·법적 공시·실거래·인허가 정보 |
| 시장 맥락 | 금리·공실률·거래량 등 집계 통계. 개별 이벤트 증거가 아님 |
| 수동 확인 | 자동수집이 부적절하거나 공개 API가 없는 업무 시스템 |

## 2. 발견 채널

| 소스 | 역할 | 권장 정책 | 비고 |
|---|---|---|---|
| 네이버 뉴스 검색 API | 국내 뉴스 키워드·날짜순 발견 | API_ALLOWED | 앱 등록·키·호출한도 필요, 전문 미제공 |
| Google News RSS 검색 | 검색식별 신규 기사 발견 | RSS_ONLY | 커버리지·리다이렉트 변동, 검증원 아님 |
| 한국경제 부동산 RSS | 기사 발견 | RSS_ONLY | 제목·요약·링크·발행시각 중심 |
| 서울경제 부동산 RSS | 기사 발견 | RSS_ONLY | 기사 이용조건 별도 준수 |
| 연합뉴스 RSS | 속보·교차발견 | RSS_ONLY | 재배포 조건 준수 |
| 파이낸셜뉴스 부동산 RSS | 기사 발견 | RSS_ONLY | RSS 범위 변동 점검 |
| BIG Kinds | 검색·중복 비교 | MANUAL_REVIEW | 로그인·이용조건·API 제공범위 확인 전 자동화 금지 |
| 딜·IB 전문매체 | 비공개 매각·PF·투자 조기신호 | METADATA_ONLY | 더벨, 딜사이트, 인베스트조선, 시그널, 마켓인 등. 유료벽 우회 금지 |
| 기업·운용사·리츠 보도자료 | 당사자 주장·일정·규모 | PUBLIC_LOW_RATE | 자기주장임을 표시하고 공식 검증과 구분 |

## 3. 공식·보강 소스

| 소스 | 주요 카테고리 | 검증 내용 | 한계/정책 |
|---|---|---|---|
| OpenDART | 매각·PF·대출·투자 | 자산 양수도, 차입, 채무보증, 담보, 출자, 정정공시 | 비상장 SPC·사모 계약 공백. API_ALLOWED |
| KRX KIND | 매각·PF·대출·투자 | 상장사 공시 상태·시각 교차확인 | KRX Open API와 역할 구분. PUBLIC_LOW_RATE/API 조건 확인 |
| 국토부 상업업무용 실거래 API | 매각·투자 | 종결 거래의 계약월·금액·위치·용도 | 신고·정정 시차, 지분·수익증권 거래 누락 가능. API_ALLOWED |
| 건축HUB 건축물대장 | 전 카테고리 | 주소·용도·면적·사용승인·건물 식별 | 서비스별 승인·쿼터 확인. API_ALLOWED |
| 건축HUB 건축인허가 | 신규공급·인허가·PF | 허가·착공·사용승인 단계 | 금융약정 자체는 검증하지 못함. API_ALLOWED |
| VWorld | 전 카테고리 | 주소 정규화·좌표·공간 식별 보조 | 동일 자산 확정은 복합키 필요. API_ALLOWED |
| 리츠정보시스템·공공데이터 | 매각·대출·투자 | 리츠 자산·영업·투자보고서·차입 | 보고 시점 차이. API_ALLOWED/PUBLIC_LOW_RATE |
| 토지이음 | 인허가·PF·신규공급 | 용도지역·지구·도시계획 제한 | 대량 자동수집보다 공개 API·수동 확인 우선 |
| 지자체 고시·공고·공보 | 인허가·신규공급·매각·임대 | 결정·인가·변경·취소의 법적 근거 | 지자체별 포맷 상이. 공개 RSS/API 우선 |
| 세움터 | 인허가·신규공급 | 건축행정 단계 수동 확인 | 공개범위·인증·약관 준수, 내부 API 역공학 금지 |
| 환경영향평가 정보지원시스템 | 인허가 | 초안·본안·협의 단계 | 운영환경 TLS·접근정책 별도 확인 |
| 온비드 | 매각·임대 | 공공·압류·신탁 매각 및 대부 입찰 | 허용 API/공개화면 범위 내 수집 |
| 법원경매정보 | 매각·PF·대출 | 경매 사건·기일·낙찰 수동 검증 | MANUAL_REVIEW 권장, 자동화·우회 금지 |
| 인터넷등기소 | 매각·대출·투자 | 소유권·근저당 설정/말소 | 유료·업무시스템, 수동 확인. 채권최고액≠원금 |
| LH청약플러스·지역공사 | 임대·신규공급 | 공공상가·업무시설 공급·임대 공고 | 기관별 공고 형식 상이 |
| ALIO·기관 입찰공고 | 매각·임대 | 공공기관 자산 매각·대부 | 기관별 원문 연결 필요 |
| 한국부동산원 R-ONE | 임대·시장맥락 | 공실률·임대료·시장지표 | 개별 자산 이벤트 원천 아님 |
| 한국은행 ECOS | PF·대출·시장맥락 | 기준·시장·대출금리 | 개별 거래 검증 불가 |
| 금감원 FISIS·금융위/금감원 자료 | PF·대출 | 업권 익스포저·정책·건전성 | 개별 사업장 공개 제한 |
| FreeSIS·SEIBro | 투자·대출 | 펀드통계·유동화증권 보조 | 사모 계약 상세 제한 |

## 4. 현재 환경과의 연결 후보

`C:\10137_WorkSpace\env\.env`에는 이름 기준으로 다음 연결 후보가 확인되어 있다. 키 값은 문서·로그·DB에 기록하지 않는다.

- DART
- KRX
- data.go.kr
- 서울 열린데이터
- VWorld
- Google
- Supabase

키 존재는 개별 서비스 권한을 의미하지 않는다. 공급자·endpoint별 인증 smoke test가 필요하다. Google 일반 검색은 API 키 외 검색엔진 ID가 추가로 필요할 수 있다.

## 5. 수집 정책 enum

| 코드 | 허용 범위 |
|---|---|
| `API_ALLOWED` | 공식 API 문서·쿼터·이용조건 내 자동수집 |
| `RSS_ONLY` | RSS/Atom 제공 필드만 자동저장 |
| `PUBLIC_LOW_RATE` | robots/약관을 확인한 공개페이지 저빈도 확인 |
| `METADATA_ONLY` | 제목·URL·발행시각·최소 인용문 중심 |
| `MANUAL_REVIEW` | 자동수집하지 않고 운영자 확인 |
| `PROHIBITED` | 수집 금지 |

## 6. 저작권·약관 기준

1. 공식 API·RSS·공개 다운로드 우선
2. 로그인·CAPTCHA·유료벽 우회 금지
3. 기사 전문은 권리 근거 없이 영구 저장 금지
4. 제목·URL·언론사·발행시각·검색시각·근거 문장·해시 중심 보존
5. 첨부 고시문은 재사용 조건에 따라 파일 또는 URL·해시만 보존
6. robots.txt, API 호출한도, 재배포 허용범위를 `collection_sources`에 기록
7. 원문 삭제·수정 시 문서 버전과 접근 상태를 갱신하고 기존 근거 lineage는 보존

## 7. 주요 진입 URL

- OpenDART: https://opendart.fss.or.kr/
- KRX KIND: https://kind.krx.co.kr/
- 공공데이터포털: https://www.data.go.kr/
- 국토부 실거래 공개시스템: https://rt.molit.go.kr/
- 건축HUB 인허가 API: https://www.data.go.kr/data/15136267/openapi.do
- 건축HUB 건축물대장 API: https://www.data.go.kr/data/15134735/openapi.do
- 상업업무용 실거래 API: https://www.data.go.kr/data/15126463/openapi.do
- 리츠정보시스템: https://reits.molit.go.kr/
- 토지이음: https://www.eum.go.kr/
- 온비드: https://www.onbid.co.kr/
- 정부24 지자체 소식: https://www.gov.kr/portal/locgovNews
- 국가법령정보센터: https://www.law.go.kr/
- 한국부동산원 R-ONE: https://www.reb.or.kr/r-one/
- 한국은행 ECOS: https://ecos.bok.or.kr/api/
- 네이버 뉴스 API: https://developers.naver.com/docs/serviceapi/search/news/news.md
- Google News RSS: `https://news.google.com/rss/search?q={QUERY}&hl=ko&gl=KR&ceid=KR:ko`
