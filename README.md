# Commercial Real Estate Market Intelligence

대한민국 상업용 부동산 시장을 매각·임대·공급·인허가·PF·대출·투자 등 **시장 카테고리별로 탐색**하고, 문서·이벤트·자산·회사·기관자금·매각절차를 관계형 intelligence로 연결하는 데이터베이스와 Next.js workspace입니다.

## 현재 구조

```text
검색·공식 API·공시·RSS 수집
  → source document / version / extraction lineage
  → event candidate 및 관계 정합화
  → event / asset / organization / capital / sale process
  → local SQLite archive / dashboard serving projection
  → Turso/libSQL (compact online serving)
  → Next.js read-only intelligence workspace
```

- **Full archive:** `data/market.db`, 전체 이력·비활성 상세·evidence lineage의 로컬 권위 저장소
- **Online serving:** Turso/libSQL, `data/market-serving-v2.candidate.db`를 기반으로 한 compact 데이터. 원본과 가공본을 구분합니다.
- **Web runtime:** Next.js Node runtime, server-only `@libsql/client` adapter
- **Classification authority:** schema 3.3.0의 `classification_schemes` → `classification_terms` → `record_classifications`; 운영계약은 [`docs/classification-taxonomy-v1.md`](docs/classification-taxonomy-v1.md)
- 브라우저에 DB URI·credential·raw SQL endpoint를 노출하지 않습니다.

### 2026-09-08 개편 / 운영 상태

현재 개편은 최신기사와 시계열자료 두 화면에 집중합니다. [분석·레퍼런스·수정 계획](docs/12-dashboard-redesign-plan-20260908.md)을 기준으로 기사 대표 분류, 관측 시계열, 로컬 수집과 원격 게시를 정리합니다.

Turso는 읽기 26.3억 / 무료 5억 행 소진으로 차단됐습니다. 저장공간은 474.64MB / 5GB이며, 계정 화면의 읽기 초기화일은 2026-10-01입니다. 사용자는 무료 요금제를 유지하기로 했습니다. 로컬 원본과 가공 작업은 계속하며, 온라인 게시·실조회 성공 여부는 별도로 기록합니다. 아래의 Supabase 절차는 이전 운영 이력이며 신규 갱신 대상으로 사용하지 않습니다.

## 기존 데이터 기능과 보존 범위

- 카테고리 탐색과 세부 필터 분리
- 공통 시장 카테고리·문서 목적은 관리형 taxonomy를 우선하고 기존 도메인 분류는 하위 호환 fallback으로 유지
- 기사·공시·공고·실거래 유형별 문서 template
- 이벤트 상세: 단계·자산·참여조직·근거문서
- 자산 상세: 입지·관련 이벤트·회사·문서
- 회사 360: 시가총액·업종·이벤트·자산·문서·임차 signal
- 기관자금: LP → mandate → 금액 basis → 선정·집행 → 근거
- 매각절차: milestone → bid round → bidder → submission → decision → financing
- 실거래 기본 조회는 1,000억원 이상이며 사용자가 명시적으로 선택할 때만 저액 거래를 포함

## Repository layout

| 경로 | 역할 |
|---|---|
| `web/` | Next.js dashboard와 server API |
| `collector/` | RSS·OpenDART·MOLIT 등 수집 및 후처리 |
| `db/` | schema·seed·migration·validation |
| `scripts/` | campaign, migration, snapshot, QA utility |
| `rules/` | category·classification 규칙 |
| `campaigns/` | 재현 가능한 수집 campaign 설정 |
| `docs/` | system contract·source matrix·review policy |
| `tests/` | Python domain/schema/collector tests |

로컬 DB, staging DB, raw 수집물, backup, credential과 build artifact는 Git에 포함하지 않습니다.

## Web local setup

```bash
cd web
npm ci
npm test
npm run lint
npm run build
npm run dev
```

운영 또는 로컬 server runtime에 DB 연결 설정 중 하나와 세션 secret을 제공합니다.

```text
SUPABASE_DB_URL=<server-side read-only PostgreSQL connection string>
# 또는 로컬 전용
SUPABASE_ENV_FILE=<absolute path to a private env file>
DASHBOARD_SESSION_SECRET=<32-byte-or-longer server-only HMAC secret>
```

`NEXT_PUBLIC_` 변수에 DB credential을 넣지 않습니다.

## Quality gates

```bash
cd web
npm test
npm run lint
npm run build
node scripts/smoke-live.mjs
uv run --with playwright python scripts/qa_dashboard_ui.py
```

Python domain tests:

```bash
python -m unittest discover -s tests
```

## Deployment

이 저장소는 Next.js **server runtime**과 PostgreSQL을 사용하므로 GitHub Pages만으로는 전체 앱을 실행할 수 없습니다. Vercel, Render, Railway 또는 별도 Node server에 `web/`을 배포하고, 서버 secret으로 read-only `SUPABASE_DB_URL`을 설정해야 합니다.

배포는 PostgreSQL 전용 `app_security` migration → runtime 최소 권한 → 초기 승인 이메일 → web/API → Android 순서로 진행합니다. 승인·해제 SQL과 운영 한계는 [`docs/dashboard-email-access.md`](docs/dashboard-email-access.md)를 따릅니다. 이메일만 입력하는 MVP는 메일함 소유를 증명하지 않으므로 공개 배포 시 OTP·magic link·SSO 또는 private network를 추가해야 합니다.
운영 DSN은 owner/admin 연결이 아니라 전용 read-only LOGIN role이어야 하며, 공개 배포 전 공유 저장소 또는 hosting platform rate limit도 필요합니다.

## Security

- SQL은 allowlisted query와 bind parameter만 사용
- read-only transaction과 statement timeout 적용
- 일반 검색에서 raw stored document body 비공개
- `.env`, DB snapshot, raw/staging data, backup은 repository 제외
