# CRE DB Supabase/Vercel release checklist — 2026-09-09

## Scope and immutable targets

- Production URL: `https://cre-db.vercel.app`
- Vercel project: `cre-db` / `prj_1DTajzRAaw2IbqffiAwN2aZWC5Bb`
- Vercel team: `team_ZraFevjGRitnuj6w5suDl9Cs`
- Vercel project root: `web`
- GitHub source: `https://github.com/Crus7230/CRE-DB.git`
- Verified remote `main` baseline at preparation time: `eef5faf4a773f3b6080e852380ba6cfcac05c5db`
- Isolated release checkout: `.codex_tmp/cre-release-20260909`
- Local release branch: `codex/cre-supabase-release-20260909`
- New Supabase project ref: `rjalzmmiqhrdmhojbxsk`
- Generative AI is explicitly out of scope. The smart lookup remains deterministic pre-indexing and retrieval only.

Do not modify the dirty parent repository or the 31-file source checkout in place. Do not upload databases, journals, backups, raw captures, artifacts, reports, logs, environment files, access-code files, credentials, or local build/cache directories.

## Current authority checkpoint

- Vercel link metadata matches the project/team/name above.
- The earlier production release recorded in `docs/13-dashboard-redesign-state-20260908.md` is `dpl_7DWCMt1y81gDFbf4riGDQQQyCsEZ`, READY and aliased to the production URL.
- A current `VERCEL_TOKEN` or interactive Vercel login is still required before any environment update or deployment.
- The current Windows Git Credential Manager has no reusable `Crus7230` GitHub credential. A Vercel CLI source deployment can proceed without a GitHub push; report the local commit and any unpushed state explicitly.

## Candidate assembly gate

1. Keep `source-delta-files.txt` as an exact, reviewed two-source inventory. `legacy` rows must equal the complete pre-existing three-tab/smart-lookup/local-split delta in `cre-online-redesign-20260908`; `canonical` rows point to exact current files under `09. CRE DB Board` and overlay the legacy copy. It must include the final Supabase runtime/cache/migration/export/schema-document additions—not just a new cache file.
2. Run `Prepare-CreReleaseCandidate.ps1 -ValidateOnly` first from a clean release checkout, passing both source content roots. Remote-baseline authority is checked in the release checkout; the canonical content root is intentionally not treated as a standalone Git repository. The script compares the complete legacy delta with its manifest rows, rejects forbidden paths, and hashes every listed source without copying. Remove `-ValidateOnly` only after the canonical manifest is final; copy mode verifies destination SHA-256 and runs `git diff --check`.
3. Confirm runtime imports, fonts and licenses, `package.json`, lockfile, required operational scripts, and the new schema/state documentation are present. Add a path only after explaining why the deployed runtime or release verification requires it.
4. Run all relevant unit tests, lint, TypeScript checks, production build, and visual QA from the release checkout.
5. Run `Test-CreReleaseCandidate.ps1`. Required result: secret matches `0`, forbidden paths `0`, conflict markers `0`, and `git diff --check` passed. The scanner compares credential values in memory and prints only counts and matching paths.
6. Commit locally on the scoped release branch. Push only if `Crus7230` GitHub authorization is available; a missing push does not authorize embedding credentials or changing global Git settings.

## Supabase data and permission gate

Record these values from direct readback immediately before release:

| Check | Required evidence |
| --- | --- |
| Project identity | project ref `rjalzmmiqhrdmhojbxsk`, PostgreSQL version, region/pooler |
| Dataset contract | final dataset/schema version from the canonical version marker |
| Freshness | source-specific maximum observation/published/indexed timestamps and timezone |
| News physical size | relation/index/total bytes for the news serving objects |
| Time-series physical size | relation/index/total bytes for the time-series serving objects |
| Search-index physical size | relation/index/total bytes for deterministic lookup/index objects |
| Whole database | `pg_database_size(current_database())` |
| Runtime privileges | production data RPC can execute required read paths and cannot perform DDL or direct table writes |
| Load privileges | the separate migration/load authority completed schema/load work and is not exposed to browser code |
| RPC separation | cold/warm timings are reported separately for data RPC and authentication RPC; do not combine them |

Final independent pre-release readback is dataset `cre-20260909T060407Z-5c55a7cb58de`, schema `1.1.0`, source freshness `2026-09-09T06:04:07Z`, PostgreSQL `17.6`, Tokyo pooler, and `pg_database_size=61,549,715 B`. Physical schema totals are `cre_news=20,021,248 B` (table/index `7,380,992/8,855,552 B`), `cre_timeseries=29,933,568 B` (`15,368,192/14,516,224 B`), and `cre_system=303,104 B` (`49,152/147,456 B`). The deterministic article-search object is `4,136,960 B` (`1,802,240 B` table plus `2,228,224 B` indexes). RLS is enabled on all 15 private tables and invalid constraints are `0`.

Local Supabase-backed QA on `http://127.0.0.1:3015` passed all three tabs, article detail/index search, address/company smart lookup, and desktop/mobile visual checks; the existing port `3005` was preserved. Standard regression is `77 files / 311 passed / 1 skipped`, and lint passed. Local warm HTTP observations were news `5.8 ms`, macro `11.3 ms`, pulse `6.3 ms`, and permits first request `131.9 ms` then repeat `4.8 ms`. These are not production results and not a true cold-DB benchmark; staged and live checks below remain required.

## Vercel environment gate

1. Inspect the existing project and list environment variable **keys/targets only**. Never print values.
2. The mutation manifest must contain only environment variables actually referenced by the final server runtime. Data-provider requirements are `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PROJECT_REF=rjalzmmiqhrdmhojbxsk`, and `DASHBOARD_DATA_PROVIDER=supabase`. The ref must match the URL or the runtime fails closed.
3. Apply the minimal production-only Supabase delta. Preserve `DASHBOARD_SESSION_SECRET`, existing API keys, and every unrelated environment entry. Never clear all variables.
4. Root QA approval authorizes replacing the exact three target keys above because switching the production connection to the new Supabase project is the requested release. Do not touch any other key. Sensitive old values may not be readable, so preserve the currently aliased deployment as the rollback target.
5. Re-read environment metadata and verify every pre-existing entry identity remains plus the required production Supabase keys.
6. Environment changes affect only new deployments, so build a new staged production deployment.

`Invoke-CreVercelStage.ps1` requires both `-RootQaApproved` and `-ApproveEnvironmentMutation`. It pins Vercel CLI `59.13.1`, updates only the key manifest from the declared per-key authority, deploys with `--prod --skip-domain`, waits for READY, and deliberately leaves `cre-db.vercel.app` unchanged.

### Smart-lookup runtime environment

The canonical server allowlist in `smart-lookup-http.ts` contains exactly four provider keys and permits only the four fixed HTTPS provider hosts. No provider base URL is configurable.

| Key | Functional requirement | Approved local authority at preparation time |
| --- | --- | --- |
| `VWORLD_KEY` | Required for address candidate search | Existing global external-API authority |
| `DATA_GO_KR_KEY` | Required for selected-address building-register detail | Existing global external-API authority |
| `DART_API_KEY` | Required for company candidate search, company overview, and disclosures | Existing global external-API authority |
| `KRX_API_KEY` | Optional to the DART company flow, but required for the KRX listed-security enrichment card | Existing global external-API authority |

Name-only inspection found none of these four keys in `C:\10137_WorkSpace\env\.env.personal.txt` and all four in `C:\10137_WorkSpace\env\.env`. The global file is already the canonical workstation fallback read by this feature, so it is the per-key authority for adding these existing provider credentials to Vercel. Values stay in memory and are never printed or copied into the repository. `SMART_LOOKUP_ENV_FILE` is a local-only optional override and must not be added to Vercel; Vercel supplies its own `VERCEL` system variable.

Vercel key/target presence is still unknown while authorization is absent. After login, list names/targets only and then add or replace exactly the eight entries in `vercel-env-mutations.tsv`; do not infer missing smart-lookup keys from the old Turso release. If `DASHBOARD_SUPABASE_RPC_SCHEMA` already exists for production, read it in memory and require exactly `public`; do not delete it or print its value. The old `SUPABASE_DB_SCHEMA` is ignored and should be preserved.

## Staged deployment QA gate

Run each check against the staged deployment URL before promotion and retain status, response headers, timing, and a small non-sensitive payload sample.

- Anonymous calls to every protected data API return `401` with `Cache-Control: no-store`.
- Allowed email `sjlee@igisam.com` logs in successfully and receives the secure HTTP-only session cookie.
- A unique, non-allowlisted IGIS email is rejected. Do not weaken the existing email-only allowlist model in this release.
- The three dashboard tabs load from the new Supabase-backed data paths: 최신기사, 시계열자료, and 스마트 조회.
- Article-detail lookup resolves an ID returned by 최신기사, and the article tab's deterministic index search returns source-grounded results.
- 스마트 조회 exercises both the address and company API paths. There is no generative response path or model call.
- Source/dataset version and cache-state headers match the final server contract. Record cold and warm responses independently.
- Data RPC timing and authorization RPC timing are captured independently (for example, separate `Server-Timing` entries); neither hides the other.
- Desktop and mobile visual QA cover login, all three tabs, article detail, indexed search, loading/empty/error states, and a mobile viewport around `390 × 844`.
- No production alias has changed at this point.

## Promotion and live verification gate

Promotion requires a second explicit approval after staged QA:

1. Confirm the staged deployment ID, URL, project ID, production target, and READY state.
2. Record the currently aliased production deployment for rollback.
3. Promote the staged production deployment with `vercel promote <deployment-url> --yes`; do not rebuild.
4. Confirm `cre-db.vercel.app` is assigned to the new deployment.
5. Repeat anonymous `401`, allowed and rejected login, three-tab APIs, article detail, indexed search, source/version/cache headers, cold/warm data RPC, auth RPC, and desktop/mobile visual checks on the production URL.
6. Review recent production error logs.
7. Record the local release commit, GitHub push status, Vercel deployment ID/URL/READY timestamp, production alias verification, final Supabase version/freshness/size evidence, and rollback deployment ID.

`Promote-CreVercelRelease.ps1` implements this second gate. It refuses to run without both staged-QA and production-promotion switches, verifies that the target is a READY staged production deployment, records the currently aliased deployment, promotes without rebuilding, and confirms the production alias by API readback.

If live verification fails, promote the previously recorded production deployment back immediately. Do not alter Supabase data during rollback.
