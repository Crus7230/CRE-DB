# Dashboard 팀 접근 인증

## 반드시 구분할 보안 경계

현재 로그인은 사전에 등록된 이메일 **주소 문자열**을 확인하는 allowlist 방식이다. 메일함 소유 여부를 확인하지 않으므로, 승인된 주소를 아는 사람은 그 주소를 입력해 세션을 발급받을 수 있다.

> 이 방식은 이메일 OTP, magic link, 회사 SSO와 같은 사용자 본인 인증이 아니다. 민감 데이터를 공개 인터넷에서 제공하기 전에는 OTP/SSO를 추가하거나 private network 또는 배포 플랫폼 access protection 뒤에 두어야 한다. 로그인 횟수 제한은 대입 공격을 줄일 뿐 이메일 소유 확인을 대신하지 않는다.

제품에서 이메일-only 방식을 명시적으로 유지하는 동안에는 이를 "메일 인증" 또는 "본인 확인"으로 설명하지 않는다.

## 현재 runtime 흐름

1. client가 `{email}`을 `POST /api/auth/login`으로 전송한다.
2. server가 4 KiB body 제한을 적용하고 이메일을 trim/lowercase/형식 검증한다.
3. Turso의 `dashboard_login_rate_limits`에서 HMAC 처리한 IP/account key를 한 statement로 갱신한다. 15분 창의 10번째 시도부터 15분 차단한다.
4. `dashboard_access_allowlist`에서 활성·미철회·미만료 이메일을 parameterized query로 확인한다.
5. 성공 시 opaque `access_subject_id`와 발급·만료 시각만 담은 HMAC session을 발급한다. 이메일은 cookie에 넣지 않는다.
6. proxy는 보호 요청마다 session 서명·만료를 검증하고 현재 subject 허용 상태를 확인한다. 승인 성공만 함수 메모리에 30초 캐시하므로 철회 반영은 warm instance에서 최대 30초 지연될 수 있다.
7. 인증·권한 DB 장애나 rate-limit 갱신 실패는 fail closed `503`으로 처리한다. 잘못된 이메일과 비승인·철회·만료 이메일은 같은 generic `401`을 사용한다.

Session cookie 계약:

- 이름: `cre_db_session`
- 속성: HttpOnly, SameSite=Lax, HTTPS/production Secure
- 최대 수명: 12시간
- browser에는 DB URL, Turso token, raw 이메일 allowlist를 제공하지 않음

## Server-only 환경변수

- `TURSO_DATABASE_URL`: `libsql://...` Turso database URL
- `TURSO_AUTH_TOKEN`: remote Turso token; `file:` URL의 로컬 smoke에서만 생략 가능
- `DASHBOARD_SESSION_SECRET`: 32 bytes 이상 HMAC secret
- `TURSO_QUERY_TIMEOUT_MS`: 선택, 1,000~30,000ms; 기본 8,000ms
- `TURSO_ENV_FILE`: 선택, 로컬 중앙 authority file을 바꿀 때만 사용

로컬 기본 authority는 `C:\10137_WorkSpace\env\.env.personal.txt`이며 credential을 repo나 앱 폴더로 복사하지 않는다. Vercel production은 `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `DASHBOARD_SESSION_SECRET`을 server environment로 직접 제공한다. 어떤 credential에도 `NEXT_PUBLIC_` 접두사를 사용하지 않는다.

## Migration-first 준비

Turso는 PostgreSQL schema namespace를 사용하지 않는다. Web 배포 전에 다음 additive migration으로 unqualified auth table을 준비한다.

```text
db/turso/migrations/001_dashboard_security.sql
```

생성되는 운영 table:

- `dashboard_access_allowlist`
- `dashboard_login_rate_limits`

승인 이메일 적용은 변경 권한이 명시적으로 승인된 운영 환경에서만 실행한다. 이메일 목록과 승인자는 source나 문서가 아니라 process environment로 전달한다.

```powershell
$env:DASHBOARD_APPROVED_EMAILS_JSON='["person@example.com"]'
$env:DASHBOARD_APPROVED_BY='operator-id'
node web/scripts/manage-dashboard-access.mjs audit
node web/scripts/manage-dashboard-access.mjs apply
```

`audit`은 읽기 전용이다. `apply`는 auth table을 확인·준비하고 요청 이메일을 활성화한 뒤 readback하며, 요청 목록 밖의 다른 active approval이 있으면 암묵적으로 변경하지 않고 중단한다.

## Revoke, restore, incident response

철회와 복구는 승인된 Turso 운영 절차에서 bind parameter를 사용해 수행하고 결과를 다시 조회한다. 의미 계약은 다음과 같다.

```sql
-- Revoke
UPDATE dashboard_access_allowlist
SET is_enabled=0,
    revoked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
    revoked_by=?
WHERE email_normalized=?;

-- Restore
UPDATE dashboard_access_allowlist
SET is_enabled=1,
    approved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
    approved_by=?,
    revoked_at=NULL,
    revoked_by=NULL,
    access_expires_at=NULL
WHERE email_normalized=?;
```

철회는 새 로그인을 즉시 막고, 기존 session은 proxy의 positive authorization cache 때문에 최대 30초 뒤 차단될 수 있다. `DASHBOARD_SESSION_SECRET` 회전은 모든 기존 session을 무효화하므로 incident response에 사용할 수 있다.

## 데이터 및 배포 경계

- auth table은 시장 archive/candidate 자료가 아니라 Turso의 별도 운영 상태다.
- 승인 이메일 PII를 SQLite archive, compact serving build, browser bundle, Android resource, analytics export, test fixture에 포함하지 않는다.
- serving publisher는 auth table을 덮어쓰거나 제거하지 않는다.
- 공개 인터넷의 민감 서비스라면 OTP/SSO 또는 별도 access protection이 확인되기 전까지 이메일-only 화면을 충분한 사용자 인증으로 간주하지 않는다.
- 배포 후에는 비로그인 API `401`, 비승인 로그인 generic `401`, 인증 DB 장애 `503`, 승인 세션과 revoke 반영을 각각 확인한다.
