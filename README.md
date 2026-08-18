# Commercial Real Estate Market Intelligence

대한민국 상업용 부동산 시장을 매각·임대·공급·인허가·PF·대출·투자 등 **시장 카테고리별로 탐색**하고, 문서·이벤트·자산·회사·기관자금·매각절차를 관계형 intelligence로 연결하는 데이터베이스와 Next.js workspace입니다.

## 현재 구조

```text
검색·공식 API·공시·RSS 수집
  → source document / version / extraction lineage
  → event candidate 및 관계 정합화
  → event / asset / organization / capital / sale process
  → Supabase PostgreSQL (main)
  → Next.js read-only intelligence workspace
```

- **Main DB:** Supabase PostgreSQL 17, `market_intelligence` schema
- **Local snapshot:** Supabase에서 재생성하는 read-only SQLite sub
- **Web runtime:** Next.js Node runtime, server-side PostgreSQL adapter
- 브라우저에 DB URI·credential·raw SQL endpoint를 노출하지 않습니다.

## Workspace

- 카테고리 탐색과 세부 필터 분리
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

운영 또는 로컬 server runtime에 다음 중 하나를 제공합니다.

```text
SUPABASE_DB_URL=<server-side read-only PostgreSQL connection string>
# 또는 로컬 전용
SUPABASE_ENV_FILE=<absolute path to a private env file>
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

공개 배포 전에는 SSO·접근코드·private network 등 인증 계층을 추가하는 것을 권장합니다.

## Security

- SQL은 allowlisted query와 bind parameter만 사용
- read-only transaction과 statement timeout 적용
- 일반 검색에서 raw stored document body 비공개
- `.env`, DB snapshot, raw/staging data, backup은 repository 제외
