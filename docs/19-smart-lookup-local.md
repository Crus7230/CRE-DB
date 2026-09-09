# 스마트 조회 로컬 운영 메모

## 1. 범위와 데이터 경계

스마트 조회는 사용자가 검색 버튼을 누른 때에만 공식 외부 API를 호출하는 요청형 기능이다. 최신기사와 시계열 자료가 사용하는 Turso/SQLite 데이터베이스를 대체하거나 갱신하지 않으며, 조회 결과도 현재 데이터베이스에 저장하지 않는다.

처리 흐름은 다음과 같다.

1. 로그인한 사용자가 주소, 회사명 또는 종목코드를 입력한다.
2. 서버가 공식 원천에서 주소·법인 후보를 찾는다.
3. 사용자가 동명이인 또는 유사 주소 후보를 선택한다.
4. 서버가 선택 결과를 검증한 뒤 상세 원천을 호출한다.
5. 화면은 원천별 상태, 응답 확인 시각, 자료 기준일을 구분해 표시한다.

## 2. 사용 API와 권한

| 영역 | 공식 원천 | 사용 기능 | 서버 환경변수 | 별도 권한·주의사항 |
| --- | --- | --- | --- | --- |
| 주소 후보 | VWorld 주소검색 API | 도로명·지번 후보와 PNU 확인 | `VWORLD_KEY` | API 키와 등록 도메인 정책을 확인해야 한다. |
| 건축물 | 국토교통부 건축HUB 건축물대장 | 총괄표제부·표제부 공개 항목 | `DATA_GO_KR_KEY` | 공공데이터포털 활용신청과 서비스키 승인이 필요하다. 소유자·전유부 개인정보는 조회하지 않는다. |
| 법인 후보 | OpenDART 고유번호 | 회사명·영문명·종목코드·DART 고유번호 후보 | `DART_API_KEY` | 전체 고유번호 ZIP을 사용하므로 첫 cold 조회가 상대적으로 느릴 수 있다. |
| 기업 상세 | OpenDART 기업개황·공시검색 | 기업개황과 최근 1년 공시 최대 10건 | `DART_API_KEY` | 공시 원문은 DART 공식 뷰어로 연결한다. |
| 상장 기본정보 | KRX Open API | KOSPI·KOSDAQ·KONEX 종목 기본정보 | `KRX_API_KEY` | 인증키 발급 외에 각 서비스 이용신청 승인이 필요하다. **실시간 주가 API가 아니다.** |

공식 안내:

- [VWorld 오픈API](https://www.vworld.kr/dev/v4api.do)
- [국토교통부 건축HUB 건축물대장정보 서비스](https://www.data.go.kr/data/15134735/openapi.do)
- [OpenDART 고유번호](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018)
- [OpenDART 기업개황](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002)
- [OpenDART 공시검색](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
- [KRX Open API 이용방법](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp)
- [KRX Open API 서비스 목록](https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd)

## 3. 시간과 상태의 해석

- `응답 확인 시각(checkedAt)`은 해당 원천 응답 또는 캐시 자료를 서버가 확인한 시각이다.
- `자료 기준일(asOf)`은 원천 자료 자체의 기준일이다. 응답 확인 시각과 같다는 뜻이 아니다.
- KRX 카드는 기준일의 종목 기본정보다. 현재가, 체결가 또는 실시간 시세로 해석하면 안 된다.
- 최근 KRX 기준일 자료가 비어 직전 수신일로 내려간 경우, 원인은 휴장일뿐 아니라 원천 적재 지연일 수도 있다. 화면은 휴장으로 단정하지 않는다.
- OpenDART 고유번호의 `modify_date`는 각 법인의 목록 수정일이다. 전체 목록 생성 시각이나 모든 기업의 공통 기준일이 아니다.
- `정상`, `자료 없음`, `연결·승인 필요`, `오류`, `시간 초과`는 서로 다른 상태다. 자료 없음은 연결 실패를 의미하지 않는다.

## 4. 캐시와 제한

- 통합 결과 캐시는 모든 출처가 `정상` 또는 `자료 없음`일 때만 5분간 보관한다. 최대 96개 결과와 24개 동시 원천 작업으로 제한한다.
- OpenDART 고유번호 목록은 모듈 내에서 6시간 재사용하고, 갱신 실패 시 24시간 이내의 마지막 정상 목록만 이전 수신 자료임을 표시해 사용할 수 있다. 동시 첫 요청은 한 번의 다운로드로 합친다.
- KRX 종목 기본정보 목록은 정상 응답 12시간, 빈 응답 10분을 재사용하며 최대 24개 항목으로 제한한다. 최근 평일 후보는 최대 4개까지만 확인한다.
- 각 외부 요청은 최대 15초, 전체 조회는 최대 35초, 한 조회의 원천 요청은 최대 18회, 응답 본문은 최대 16 MiB다. 화면의 최종 대기 한도는 45초다.
- 위 캐시는 서버리스 인스턴스의 메모리 캐시다. 인스턴스 간에 공유되지 않으며 cold start 또는 새 인스턴스에서는 공식 원천을 다시 호출할 수 있다.
- 원천 일부가 시간 초과되더라도 먼저 완료된 카드와 원천별 상태는 보존한다.

## 5. 보안 경계

- API 키는 서버에서만 읽는다. `NEXT_PUBLIC_` 환경변수, 브라우저 응답, 선택 토큰, 로그에 넣지 않는다.
- 운영 배포는 Vercel 런타임 secret을 사용한다. 로컬은 명시한 `SMART_LOOKUP_ENV_FILE` 또는 기존 외부 환경파일을 읽을 수 있지만 키 파일을 저장소에 복사하지 않는다.
- 외부 요청은 허용된 공식 HTTPS 호스트만 가능하고 리다이렉트는 따르지 않는다. 네이티브 오류와 키가 포함된 원천 URL은 응답·로그에 다시 노출하지 않는다.
- 후보 선택 토큰은 15분 HMAC 서명이며 정규화한 검색어와 로그인 subject에 결합된다. 다른 사용자, 다른 검색어 또는 변조된 토큰은 상세 조회에 사용할 수 없다.
- `/api/lookup`은 세션, 현재 승인 subject, same-origin, JSON 본문 크기, 사용자별 분당 요청 수를 검사한다. 응답은 `private, no-store`다.
- 승인 subject 재확인은 정상 승인만 최대 30초 캐시한다. 권한 취소 반영에는 최장 약 30초가 걸릴 수 있고, 권한 DB 장애 시에는 닫힌 상태로 실패한다.

### 이메일 승인 방식의 한계

현재 로그인은 입력한 이메일이 승인 목록에 있는지만 확인한다. 메일함으로 인증 링크나 OTP를 보내지 않으므로 **입력자가 실제 메일 소유자인지는 증명하지 않는다.** 승인된 주소를 아는 사람이면 접속을 시도할 수 있어 내부 제한 시험에만 적합하다. 외부 공개 또는 민감정보 운영 전에는 회사 SSO/OIDC나 이메일 OTP·매직링크로 소유권 확인을 추가해야 한다.

## 6. 로컬 검증

관련 자동 테스트:

- [HTTP 허용목록·크기·오류 경계](../web/src/lib/server/smart-lookup-http.test.ts)
- [입력 검증·선택 토큰·통합 캐시](../web/src/lib/server/smart-lookup.test.ts)
- [OpenDART·KRX 회사 조회](../web/src/lib/server/smart-lookup-company.test.ts)
- [VWorld·건축물대장 주소 조회](../web/src/lib/server/smart-lookup-address.test.ts)
- [보호 API·Origin 검사](../web/src/app/api/lookup/route.test.ts)
- [검색 UI 상태·후보·부분 성공](../web/src/components/smart-api-search.test.tsx)

저장소 루트에서 `web` 작업 디렉터리로 이동한 뒤 실행한다.

```powershell
Set-Location web
npm test -- src/lib/server/smart-lookup-http.test.ts src/lib/server/smart-lookup.test.ts src/lib/server/smart-lookup-company.test.ts src/lib/server/smart-lookup-address.test.ts src/app/api/lookup/route.test.ts src/components/smart-api-search.test.tsx
npx tsc --noEmit
npm run lint
```

### 실제 원천 QA 기록

2026-09-08 로컬에서 서울시청 도로명 주소→동별 건축물 2건, 005930 삼성전자→기업개황·최근 공시·KRX 기본정보를 실조회했다. KRX 수신 기준일은 2026-09-07이었다. 건축HUB의 간헐적 총괄표제부 연결 오류 때에도 수신된 동별 카드를 유지하고 부분 실패를 표시하는 것을 확인했다. 모바일 390px과 데스크톱 맞춤 화면·가로 넘침 검사를 통과했다.

분리 DB 연결·원래 프로젝트 위치의 빌드와 전체 회귀 결과 및 실행/갱신 절차는 [현재 상태](20-local-smart-search-and-split-status.md)를 참고한다. 인증키와 서명 토큰은 QA 산출물에 기록하지 않았다.
