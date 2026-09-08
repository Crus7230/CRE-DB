# Financial Macro Dataset

## 목적

상업용부동산 인허가·거래 월별 시계열과 한국·미국의 정책금리, 단기 조달금리, 국채 수익률 및 신용금리를 같은 월 축에서 비교한다. Local SQLite는 공식 원문·release·observation revision 및 재계산 권위이고, 개인 Supabase는 compact monthly serving DB다.

- Global schema version: `3.5.0` 유지
- Feature version: `financial_macro_schema_version=1.0.2`
- Migrations: `db/v2/migrations/3.7.0_financial_macro.*.sql` through `3.7.2_financial_macro_validity.*.sql`

## 공식 source

### 한국은행 ECOS

Base: `https://ecos.bok.or.kr/api`

| Series code | Native ID | Frequency | 시작 | 단위 |
|---|---|---|---|---|
| `BOK_BASE_RATE_MONTHLY` | `722Y001 / 0101000 / M` | 월 | 2000-01 | 연% |
| `KR_CD_91D` | `721Y001 / 2010000 / M` | 월 | 1991-03 | 연% |
| `KR_GOVT_BOND_3Y` | `721Y001 / 5020000 / M` | 월 | 1995-05 | 연% |
| `KR_GOVT_BOND_10Y` | `721Y001 / 5050000 / M` | 월 | 2000-10 | 연% |
| `KR_CORP_BOND_AA_MINUS_3Y` | `721Y001 / 7020000 / M` | 월 | 1987-01 | 연% |

`BOK_ECOS_API_KEY` 또는 `ECOS_API_KEY`가 있으면 사용한다. 미설정 시 2026-09-02에 실호출로 검증한 `sample` 10행 pagination을 사용할 수 있지만, 정기 운영 전 공식 ECOS key 등록을 권장한다. Provider가 공표한 월별 값을 보존하며 임의 일별 평균으로 대체하지 않는다.

### 뉴욕연방준비은행 Markets API

Base: `https://markets.newyorkfed.org/api/rates`

| Series code | Endpoint/field | Frequency | 시작 |
|---|---|---|---|
| `US_EFFR` | `unsecured/effr / percentRate` | 일 | 2000-07-03 |
| `US_FED_TARGET_LOWER` | `unsecured/effr / targetRateFrom` | 일 | 2008-12-16 |
| `US_FED_TARGET_UPPER` | `unsecured/effr / targetRateTo` | 일 | field 제공 시점부터 |
| `US_SOFR` | `secured/sofr / percentRate` | 일 | 2018-04-02 |

`revisionIndicator`를 observation metadata에 보존하고 값이 있으면 `REVISED`로 표기한다. 목표금리 상단이 없는 과거 EFFR row에는 상단값을 추정하지 않는다.

### 미국 재무부

Official feed:

`https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={YEAR}`

| Series code | XML field | Frequency | 시작 |
|---|---|---|---|
| `US_TREASURY_2Y` | `BC_2YEAR` | 일 | 1990-01-02 |
| `US_TREASURY_10Y` | `BC_10YEAR` | 일 | 1990-01-02 |
| `US_TREASURY_30Y` | `BC_30YEAR` | 일 | 1990-01-02 |
| `US_TREASURY_10Y_MINUS_2Y` | `BC_10YEAR - BC_2YEAR` | 일, 파생 | 1990-01-02 |

30년물 미발행 구간 등 원천 결측은 보간하지 않는다. 10Y-2Y는 동일 관측일에 두 원천값이 모두 있을 때만 계산한다.

## 데이터 모델

- `macro_series`: native ID, 빈도, 단위, 정의, source, region
- `macro_releases`: 수집 snapshot, artifact SHA-256, 유효일, 원문 URI
- `macro_observations`: period별 값, vintage, revision, supersession, row hash
- `v_latest_macro_observations`: period별 최신 revision
- `v_financial_macro_monthly`: 월별 공식값 또는 일별 calendar-month average
- `financial_macro_monthly_serving`: 개인 Supabase compact monthly table

같은 `series+period+row_hash`는 재삽입하지 않는다. 값이 바뀌면 revision number를 올리고 `supersedes_observation_id`로 직전 값을 연결한다.

## 월별 집계

- ECOS monthly: `PROVIDER_MONTHLY`
- NY Fed/Treasury daily: `CALENDAR_MONTH_AVERAGE`
- 부분월도 저장하되 UI에서 완료월과 구분한다.
- 결측 영업일을 0으로 채우지 않는다.
- 국채 미발행·휴일·API 결측을 선형보간하지 않는다.

## 실행

### Migration rehearsal/apply

```bash
python scripts/apply_financial_macro_migration.py --engine sqlite
python scripts/apply_financial_macro_migration.py --engine sqlite --apply
C:/Users/10137/AppData/Local/Programs/Python/Python311/python.exe scripts/apply_financial_macro_migration.py --engine postgres
C:/Users/10137/AppData/Local/Programs/Python/Python311/python.exe scripts/apply_financial_macro_migration.py --engine postgres --apply
```

### Official backfill

```bash
python scripts/collect_financial_macro.py --report artifacts/financial-macro/backfill-rehearsal.json
python scripts/collect_financial_macro.py --apply --report artifacts/financial-macro/backfill-applied.json
```

### Supabase serving publish

```bash
C:/Users/10137/AppData/Local/Programs/Python/Python311/python.exe scripts/sync_financial_macro_serving.py --report artifacts/financial-macro/supabase-sync-rehearsal.json
C:/Users/10137/AppData/Local/Programs/Python/Python311/python.exe scripts/sync_financial_macro_serving.py --apply --report artifacts/financial-macro/supabase-sync-applied.json
```

## 검증

- source별 observation 수·최초월·최신월 확인
- period별 최신 revision 단일성 확인
- row hash 중복 및 supersession chain 확인
- Local monthly와 Supabase series별 row count, min/max month, 최신값, 합계 대조
- SQLite integrity 및 FK 오류 확인
