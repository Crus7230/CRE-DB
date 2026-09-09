# CRE Market Intelligence Explorer

Supabase의 version-published compact serving dataset을 purpose-specific RPC로 조회하는 Next.js 대시보드입니다. 로컬에서는 검증된 분리 SQLite snapshot을 read-only fallback으로 유지합니다.

## 주요 화면

- **최신기사**: 게시일·주제별 기사와 사용자 실행형 사전 색인 근거 검색, 원문·게시일·발췌 확인
- **시계열자료**: 거래시장 pulse, 한국·미국 공식 금리 13개, 서울 건축 인허가
- **스마트 조회**: 기존 주소·기업 외부정보 조회

## 구조

```text
Browser
  → POST /api/auth/login {email}
  → Supabase fixed authorization RPC
  → shared IP/account rate-limit RPC
  → signed 12-hour cre_db_session cookie
  → authenticated dashboard API
  → Next.js Node runtime
  → project-ref + published dataset-version cache namespace
  → bounded public facade RPC
  → private cre_system / cre_news / cre_timeseries schemas
```

- 브라우저는 Supabase URL이나 service key를 받지 않습니다.
- `sb_secret_...` key는 server-side `apikey` header로만 전송하며 JWT Authorization header로 사용하지 않습니다.
- arbitrary SQL RPC는 없고 public schema에는 bounded dashboard facade만 둡니다.

- 보호 요청은 opaque subject ID의 승인 성공만 함수 메모리에 30초간 보관합니다. 거부·DB 오류는 캐시하지 않고 fail closed하며, 권한 철회와 `access_expires_at` 반영은 이미 승인된 warm instance에서 최대 30초 지연될 수 있습니다.
- data response는 `private, no-store`이며 공유 데이터 재사용은 인증 후 server-side cache에서만 수행합니다.
- manifest와 data RPC는 같은 `dataset_version`으로 고정되어 atomic publish 중 혼합 snapshot을 만들지 않습니다.
- process cache는 bounded LRU/singleflight이고 Next Data Cache가 instance 간 재사용을 담당합니다.
- 근거 검색은 lexical/search-term index 기반 결정론적 조회이며 생성형 답변을 만들지 않습니다.
- raw document body는 반환하지 않고 최신 version의 title과 snippet만 사용합니다.
- 쓰기·승인·검수 기능은 제공하지 않습니다.

## 로컬 실행

로컬에서는 다음 중앙 파일만 서버 runtime에서 읽습니다.

```text
C:\10137_WorkSpace\env\.env.personal.txt
```

앱 폴더로 credential file을 복사하지 않습니다. 중앙 authority file에는 `DASHBOARD_DATA_PROVIDER=supabase`, `SUPABASE_URL`, `SUPABASE_PROJECT_REF`, `SUPABASE_SECRET_KEY`를 한 묶음으로 둡니다. DB adapter는 이 묶음을 읽지만 파일 내용을 `process.env`로 가져오지는 않으므로 세션 서명값은 실행 process에 별도로 제공합니다. 일부 DB 값만 process environment로 덮어써 authority를 혼합하지 않습니다.

```powershell
npm install
$env:DASHBOARD_SESSION_SECRET='<32-byte 이상 local 전용 값>'
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

- `DASHBOARD_DATA_PROVIDER=supabase`: hosted runtime의 필수 provider 선택
- `SUPABASE_URL`: credential이 포함되지 않은 `https://<project-ref>.supabase.co` URL
- `SUPABASE_PROJECT_REF`: `SUPABASE_URL`과 동일해야 하는 명시적 project ref
- `SUPABASE_SECRET_KEY`: server-only secret key. `apikey` header에만 사용
- `DASHBOARD_SUPABASE_RPC_SCHEMA=public`: bounded facade RPC schema. 다른 값은 거부
- `DASHBOARD_QUERY_TIMEOUT_MS`: RPC 전체 요청·응답 body 제한시간(기본 8초)
- `DASHBOARD_SESSION_SECRET`: 12시간 `cre_db_session` HMAC 서명용 32-byte 이상 server secret
- `DASHBOARD_ENV_FILE`: 로컬에서만 중앙 authority file 경로를 바꿀 때 지정

Vercel 또는 `DASHBOARD_HOSTED_DEPLOYMENT=1` 환경은 Supabase 설정이 없거나 서로 다른 project ref를 가리키면 시작 후 첫 DB 접근에서 명확히 fail closed합니다. archive나 이전 cloud DB로 자동 fallback하지 않습니다. `NODE_ENV=production`만으로 로컬 split SQLite를 차단하지는 않습니다.

`NEXT_PUBLIC_` 접두사로 DB 설정을 만들지 않습니다.

Vercel Node 함수와 Node proxy는 `vercel.json`의 project-level `regions: ["icn1"]`을 함께 상속합니다. Next.js 16에서 deprecated된 route별 `preferredRegion` export는 사용하지 않습니다.

## 로컬 split SQLite 준비

로컬 snapshot 실행은 `DASHBOARD_DATA_PROVIDER=sqlite`를 명시하고 market/auth, news, timeseries 파일을 각각 `TURSO_DATABASE_URL`, `NEWS_DATABASE_URL`, `TIMESERIES_DATABASE_URL`에 `file:` URL로 지정합니다. `DASHBOARD_DATASET_VERSION`도 명시하여 cache namespace가 다른 snapshot과 섞이지 않게 합니다. 검증된 manifest와 auth DB 경로를 사용해 `node scripts/start-local-split.mjs --port 3005`로 실행하면 launcher가 이 값을 설정하고, 세션 secret이 없을 때 local process 전용 값을 생성합니다.

로컬 auth snapshot을 새로 준비할 권한이 있는 경우에만 다음 명령을 사용합니다. 이메일 목록과 승인자는 environment variable로만 전달하고 source나 문서에 기록하지 않습니다.

```powershell
$env:DASHBOARD_APPROVED_EMAILS_JSON='["person@example.com"]'
$env:DASHBOARD_APPROVED_BY='operator-id'
node scripts/manage-dashboard-access.mjs audit
node scripts/manage-dashboard-access.mjs apply
```

`audit`은 변경하지 않으며, `apply`는 다른 active approval이 발견되면 중단합니다. 이 스크립트는 로컬 SQLite 호환 경로용이며 hosted Supabase 승인 데이터는 migration/publish 절차에서 고정 RPC 계약으로 관리합니다. 로그인 limiter 결과가 불완전하거나 DB가 실패하면 인증을 fail closed 처리합니다.

## 팀 접근제어 배포

DB 준비 → 인증 table 확인 → 승인 이메일 등록 → web/API 배포 → client 배포 순서를 지킵니다. Production 변경과 배포는 명시 승인 전 실행하지 않습니다.

## 데이터 provider 주의

- hosted 앱은 browser SDK가 아니라 server-only Supabase REST/RPC adapter를 사용합니다.
- `sb_secret_...` key를 `Authorization: Bearer`로 보내지 않습니다. `apikey` header로만 전송합니다.
- 모든 data RPC는 먼저 확인한 `dataset_version`을 `p_dataset_version`으로 다시 전달하여 publish 전환 중에도 한 응답이 같은 version에 고정됩니다.
- 로컬 split mode만 server-only `@libsql/client`와 직접 정의된 SQLite query를 사용합니다.
- 현재 계약은 사전 등록된 승인 이메일만 사용하는 allowlist 방식이며 메일함 OTP/SSO 계약은 아닙니다.
- login rate limit은 provider의 공유 저장소에서 IP와 account를 각각 제한하고, 인증 DB 장애 시 fail closed 처리합니다.
- API의 기존 `database` discriminator 값은 client 호환성을 위해 유지합니다.
