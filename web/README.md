# CRE Market Intelligence Explorer

Turso/libSQL의 CRE serving database를 고정 SQL로 검색·색인 탐색·테이블 조회하는 Next.js 대시보드입니다. 기존 JSON API 응답 구조는 유지하면서 모든 server query를 SQLite/JSON1 문법으로 실행합니다.

## 주요 화면

- **시장 시계열(기본 화면)**: 한국·미국 공식 금리 13개를 Y축 없는 상대 높이 strip으로 표시하고 모든 그래프를 하나의 월 scrubber/crosshair로 연동
- **통합검색**: 키워드·자료유형·기간 검색과 상세 drawer
- **카테고리 테이블**: 실제 DB category key로 필터링한 행·열 조회
- **DB 색인**: 이벤트 카테고리, 자산 유형, 문서 유형, 기관 유형, LP 상태, 매각 상태 탐색

색인에서 분류를 선택하면 해당 category table로 바로 이동합니다.

## 구조

```text
Browser
  → POST /api/auth/login {email}
  → approved-email allowlist lookup
  → Turso shared IP/account rate limit (두 key를 한 statement로 원자적 갱신)
  → signed 12-hour cre_db_session cookie
  → GET /api/search (allowlisted filters only)
  → Next.js Node runtime
  → parameterized SQLite/JSON1 query
  → Turso/libSQL serving database
```

- 브라우저는 DB URI나 Turso auth token을 받지 않습니다.
- 승인 이메일과 login throttle state는 같은 Turso database의 `dashboard_access_allowlist`, `dashboard_login_rate_limits` table에 저장합니다.

- 보호 요청은 opaque subject ID의 승인 성공만 함수 메모리에 30초간 보관합니다. 거부·DB 오류는 캐시하지 않고 fail closed하며, 권한 철회와 `access_expires_at` 반영은 이미 승인된 warm instance에서 최대 30초 지연될 수 있습니다.
- raw SQL endpoint는 없습니다.
- 검색어·유형·기간·페이지 값은 고정 SQL의 bind parameter로만 전달됩니다.
- raw document body는 반환하지 않고 최신 version의 title과 snippet만 사용합니다.
- 쓰기·승인·검수 기능은 제공하지 않습니다.

## 로컬 실행

로컬에서는 다음 중앙 파일만 서버 runtime에서 읽습니다.

```text
C:\10137_WorkSpace\env\.env.personal.txt
```

앱 폴더로 credential file을 복사하지 않습니다.

```bash
npm install
npm run dev
```

기본 주소는 `http://localhost:3000`입니다.

## 품질 검증

```bash
npm test
npm run lint
npm run build
node scripts/visual-qa.mjs
```

`visual-qa.mjs`의 기본 대상은 `http://127.0.0.1:3001`이며 다른 주소는 `BASE_URL`로 지정할 수 있습니다.

## 운영 환경변수

운영 runtime에는 DB 연결 설정과 세션 secret을 서버 전용으로 제공합니다.

- `TURSO_DATABASE_URL`: `libsql://...` Turso database URL
- `TURSO_AUTH_TOKEN`: remote Turso 연결용 token (`file:` URL의 개발 smoke에는 생략 가능)
- `TURSO_ENV_FILE`: 기본 중앙 authority file을 바꿔야 할 때만 지정
- `DASHBOARD_SESSION_SECRET`: 12시간 `cre_db_session` HMAC 서명용 32-byte 이상 server secret


`NEXT_PUBLIC_` 접두사로 DB 설정을 만들지 않습니다.

Vercel Node 함수와 Node proxy는 `vercel.json`의 project-level `regions: ["icn1"]`을 함께 상속합니다. Next.js 16에서 deprecated된 route별 `preferredRegion` export는 사용하지 않습니다.

## 인증 table 준비

운영 DB에 대한 변경 권한이 승인된 경우에만 다음 명령으로 인증 table과 allowlist를 준비합니다. 이메일 목록과 승인자는 environment variable로만 전달하고 source나 문서에 기록하지 않습니다.

```powershell
$env:DASHBOARD_APPROVED_EMAILS_JSON='["person@example.com"]'
$env:DASHBOARD_APPROVED_BY='operator-id'
node scripts/manage-dashboard-access.mjs audit
node scripts/manage-dashboard-access.mjs apply
```

`audit`은 변경하지 않으며, `apply`는 다른 active approval이 발견되면 중단합니다. 로그인 시 IP/account 두 limiter key는 하나의 `INSERT ... ON CONFLICT ... RETURNING` statement에서 함께 갱신되고 결과가 불완전하거나 DB가 실패하면 인증을 fail closed 처리합니다.

## 팀 접근제어 배포

DB 준비 → 인증 table 확인 → 승인 이메일 등록 → web/API 배포 → client 배포 순서를 지킵니다. Production 변경과 배포는 명시 승인 전 실행하지 않습니다.

## Turso 운영 주의

- 이 앱은 browser SDK가 아니라 server-only `@libsql/client` 연결을 사용합니다.
- query module은 runtime SQL 변환 없이 각 query를 직접 SQLite/Turso 문법으로 정의합니다.
- 현재 계약은 사전 등록된 승인 이메일만 사용하는 allowlist 방식이며 메일함 OTP/SSO 계약은 아닙니다.
- login rate limit은 Turso 공유 저장소에서 IP와 account를 각각 제한하고, 인증 DB 장애 시 fail closed 처리합니다.
- API의 기존 `database` discriminator 값은 client 호환성을 위해 유지합니다.
