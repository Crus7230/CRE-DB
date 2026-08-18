# CRE Market Intelligence Explorer

Supabase PostgreSQL의 `market_intelligence` schema를 읽기 전용으로 검색·색인 탐색·테이블 조회하는 Next.js 대시보드입니다.

## 주요 화면

- **통합검색**: 키워드·자료유형·기간 검색과 상세 drawer
- **카테고리 테이블**: 실제 DB category key로 필터링한 행·열 조회
- **DB 색인**: 이벤트 카테고리, 자산 유형, 문서 유형, 기관 유형, LP 상태, 매각 상태 탐색

색인에서 분류를 선택하면 해당 category table로 바로 이동합니다.

## 구조

```text
Browser
  → GET /api/search (allowlisted filters only)
  → Next.js Node runtime
  → BEGIN READ ONLY + 15s statement_timeout
  → Supabase PostgreSQL / market_intelligence
```

- 브라우저는 DB URI나 Supabase service credential을 받지 않습니다.
- raw SQL endpoint는 없습니다.
- 검색어·유형·기간·페이지 값은 고정 SQL의 bind parameter로만 전달됩니다.
- raw document body는 반환하지 않고 최신 version의 title과 snippet만 사용합니다.
- 쓰기·승인·검수 기능은 제공하지 않습니다.

## 로컬 실행

로컬에서는 다음 중앙 파일만 서버 runtime에서 읽습니다.

```text
C:\10137_WorkSpace\env\.env.supabase.local
```

앱 폴더로 `.env.supabase.local`을 복사하지 않습니다.

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

운영 runtime에는 다음 중 하나만 서버 secret으로 제공합니다.

- `SUPABASE_DB_URL`: dashboard 전용 PostgreSQL connection string
- `SUPABASE_ENV_FILE`: 로컬 중앙 env 파일을 사용할 때만 지정

`NEXT_PUBLIC_` 접두사로 DB 설정을 만들지 않습니다.

## 권장 read-only PostgreSQL role

아래 SQL은 관리자 검토 후 `market_intelligence` schema에만 적용합니다. `<runtime-role>`과 비밀번호는 secret manager에서 별도로 생성하며 source나 문서에 기록하지 않습니다.

```sql
CREATE ROLE market_dashboard_reader NOLOGIN;
GRANT CONNECT ON DATABASE postgres TO market_dashboard_reader;
GRANT USAGE ON SCHEMA market_intelligence TO market_dashboard_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA market_intelligence TO market_dashboard_reader;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA market_intelligence TO market_dashboard_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA market_intelligence
  GRANT SELECT ON TABLES TO market_dashboard_reader;

-- 별도로 생성한 LOGIN role에만 상속
GRANT market_dashboard_reader TO <runtime-role>;
ALTER ROLE <runtime-role> SET default_transaction_read_only = on;
ALTER ROLE <runtime-role> SET statement_timeout = '15s';
```

현재 앱도 모든 검색을 `BEGIN READ ONLY` transaction에서 실행하지만, 운영에서는 별도 최소권한 role을 함께 적용하는 것이 원칙입니다.

## Supabase 운영 주의

- 이 앱은 Supabase Data API나 browser SDK가 아니라 server-side PostgreSQL Session pooler 연결을 사용합니다.
- 따라서 custom schema exposed setting이나 RLS에 의존하지 않습니다.
- 인터넷 공개 시 앱 앞단에 SSO 또는 private network 접근제어를 추가해야 합니다. 현재 소스에는 사용자 인증을 포함하지 않습니다.
- `public` schema를 변경하거나 초기화하지 않습니다.
