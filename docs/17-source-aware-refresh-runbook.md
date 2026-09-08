# Source-aware refresh operations

## 1. Authority and safety boundary

`data/market.db` is the full local authority. Each source refresh starts from a
consistent SQLite backup, writes only to an owned candidate, refreshes governed
serving projections, checks `integrity_check`, `foreign_key_check`, and raw-row
non-regression, and only then atomically activates the candidate. A failed
candidate never replaces the last known good archive.

The orchestrator also holds `artifacts/source-aware-refresh.lock`. This prevents
two instances of the new job from overlapping. Older or ad-hoc writers do not
share that lock, so an optimistic archive/data-version/WAL guard rejects an
activation as `SOURCE_CHANGED_DURING_COLLECTION` if the archive changed after
the candidate baseline. Uncoordinated writers must still be kept off
`data/market.db` during the final activation window.

Only direct-child files named `source-aware-*.db` under
`backups/source-aware-refresh/` are retention-managed. The newest three are kept. No
legacy or user-created backup is deleted.

## 2. Source cadences (Asia/Seoul)

| Domain | Trigger | Refresh contract |
|---|---|---|
| News | Daily 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 | Two publication-date lookback days; exact slot is part of run lineage |
| Macro | Monday-Friday 08:00 | ECOS/NY Fed rolling 24-month correction overlap; Treasury current calendar year; history remains append-only |
| MOLIT transactions | Wednesday 07:30 | Seoul only; current plus prior two calendar months; a new weekly campaign identity forces correction re-fetch |
| Seoul permits | Saturday 07:30 | Full snapshot; an incomplete quota/error snapshot remains resumable while the completed serving projection stays unchanged |

One Windows task owns all nine triggers and calls the same `--due` action.
Per-domain successful slots are stored independently, so one failure does not
roll back or rerun another successful domain.

## 3. Runtime and credentials

Stable runtime:

`C:\10137_WorkSpace\00. 2025 RA 기획추진\RA dashboard\.codex_tmp\cre-dashboard-venv\Scripts\python.exe`

The runtime currently includes Python 3.11.15, `requests`, `libsql-client`,
`tzdata`, `pytest`, `psycopg[binary]`, and `beautifulsoup4`. The scheduled task
uses the sibling `pythonw.exe`, so no console window is opened. The ordinary
`python` on `PATH` is not a supported runtime for this job.

Credential files stay external to the repository and their values must never
be printed:

- `C:\10137_WorkSpace\env\.env.personal.txt`: `TURSO_DATABASE_URL`,
  `TURSO_AUTH_TOKEN` only.
- `C:\10137_WorkSpace\env\.env`: `DATA_GO_KR_KEY` and
  `SEOUL_OPEN_DATA_GENERAL_KEY` are available.
- The public-source file currently has no BOK/ECOS key. The collector therefore
  reports `ecosAuth=sample-pagination`; this is an explicit provider status,
  not a configured-key claim.

Child Python output is decoded as UTF-8 with replacement for malformed source
bytes. Raw child stderr and provider exception messages are not copied into the
durable reports because request URLs can contain API keys.

## 4. Rehearsal and one-domain execution

From `09. CRE DB Board`:

```powershell
& '..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe' `
  scripts/run_source_aware_refresh.py --due `
  --config config/source-aware-refresh.json
```

This is a plan-only `REHEARSED` run. It makes no source request and does not
activate the live archive.

An explicitly approved one-domain local run is:

```powershell
& '..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe' `
  scripts/run_source_aware_refresh.py `
  --domain news --slot '2026-09-08T12:00+09:00' `
  --apply --allow-live-db --publish-if-enabled `
  --config config/source-aware-refresh.json
```

`--apply` without `--allow-live-db` is rejected. A known quota defer is not a
local failure. An unknown publication error is recorded as `PUBLISH_FAILED`,
does not undo local success, but makes the job return nonzero.

## 5. Windows task installation

Dry-run and validate the stable runtime:

```powershell
& '..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe' `
  scripts/install_source_aware_refresh_tasks.py `
  --python '..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe'
```

Register only after review:

```powershell
& '..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe' `
  scripts/install_source_aware_refresh_tasks.py --apply `
  --python '..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe'
```

The installer registers `\CRE DB Board\SourceAwareLocalRefresh`, then reads
back its XML and verifies all nine boundaries, `IgnoreNew`, the hidden runtime,
and the complete action arguments. It uses `InteractiveToken`, so the Windows
user must be logged in. No password is stored.

The superseded task `\CRE DB\Daily Analytics Refresh` should be disabled, not
deleted, only after the new task has completed a verified local run:

```powershell
schtasks.exe /Change /TN "\CRE DB\Daily Analytics Refresh" /Disable
```

Inventory and confirm any older Hermes news task by exact name before disabling
it. Never wildcard-delete scheduled tasks. To recover, disable the new task,
re-enable the exact prior task, and restore an exact validated backup only with
explicit operator approval.

## 6. Durable health evidence

- Latest report: `artifacts/source-aware-refresh-latest.json`
- Scheduler state: `artifacts/source-aware-refresh-state.json`
- Append-only domain events: `logs/source-aware-refresh.jsonl`
- Per-run evidence: `artifacts/source-aware-refresh-runs/<runId>.json`
- Owned candidates: `artifacts/source-aware-refresh-candidates/`
- Owned backups: `backups/source-aware-refresh/`

Interpret local and remote states separately:

- `COLLECTED_LOCAL`: local collection, projection, validation, and activation succeeded.
- `COLLECTED_PARTIAL_LOCAL`: resumable permit progress was preserved; serving remained last-known-good and exit is nonzero.
- `FAILED_LOCAL`: candidate was not activated.
- `PUBLISH_DEFERRED`: expected policy/quota pause; `remotePending=true`.
- `PUBLISH_FAILED`: unexpected remote failure; local success remains valid, but exit is nonzero.
- `PUBLISHED` / `UNCHANGED`: transactionally verified remote result.

## 7. Turso quota pause and first publication

Configuration persists `blockedUntil=2026-10-01` and
`blockedReason=QUOTA_READS`. Before that date publication returns
`PUBLISH_DEFERRED` before reading credentials, importing the client, or opening
a network connection. Local collection and projection continue normally.

On the first eligible publication after the pause, the publisher is configured
to apply only the reviewed additive serving migrations `002` and `003`, commit
that bootstrap separately, and then publish one dataset in a second
transaction. A successful bootstrap timestamp is persisted so later slots do
not replay it. This is readiness logic, not a promise that the October attempt
will succeed; quota, authentication, schema, and affected-row readback still
fail closed.

The publisher first reads the one-row dataset freshness hash. Only a changed
dataset reads its compact fingerprint rows. It upserts changed/new rows and
reads back affected fingerprint keys. Retirement deletes are exact-key and are
allowed only in owned derived serving tables. Raw history, provenance, FTS
shadows, and all security tables are never deleted or scanned by this path.

## 8. Recovery checklist

1. Read the latest report and per-domain state; do not infer remote success from local success.
2. For `SOURCE_CHANGED_DURING_COLLECTION`, identify the other writer and retry at the next eligible slot; do not force activation.
3. For a permit partial, keep the candidate-derived partial snapshot and let the next permit trigger resume it.
4. For `PUBLISH_FAILED`, preserve the local archive and retry publication only after the provider cause is resolved.
5. Before any restore, validate the exact backup with SQLite integrity/FK checks and confirm it is newer than the intended recovery point.
6. Never restore, delete, or replace broad directories as part of recovery.

## 9. One-time MOLIT baseline recovery

`config/molit-baseline-recovery-20260908.json` is a reviewed one-time plan for
the missing January 2025 through June 2026 history. Run it only with an explicit
`--domain molit`; its 21-month correction window deliberately re-fetches all
January 2025 through September 2026 partitions so source corrections are not
silently skipped. The recurring configuration remains at three months.

The recovery shares the live archive and source-aware lock, but uses separate
state, latest-report, run-report, and event-log paths. Turso publication remains
deferred through October 1. A collector failure preserves the current archive
and retains the failed candidate; MOLIT does not resume that candidate, so a
retry repeats the full request window. Expect at least 525 district-month
requests plus any pagination. Provider quota is not encoded or known, and the
collector has no per-request retry/backoff, so the operator must review the
failure code before retrying.

Plan-only rehearsal:

```powershell
& '..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe' `
  scripts/run_source_aware_refresh.py --domain molit `
  --slot '2026-09-08T07:30+09:00' `
  --config config/molit-baseline-recovery-20260908.json
```

Add `--apply --allow-live-db --publish-if-enabled` only for the separately
approved one-time execution. Do not install this recovery configuration in the
recurring Windows task.

If collection and validation completed but Windows temporarily blocked the
final file replacement, do not repeat the source requests. The activation-only
path accepts only a direct child of the configured candidate directory, checks
the reviewed archive size and whole-second modification time, rejects a
non-empty archive WAL, repeats full integrity/FK/raw-row non-regression checks,
creates a fresh uniquely named backup, and then performs a guarded replacement.
It never publishes remotely. For the reviewed September 8 recovery candidate:

```powershell
& '..\.codex_tmp\cre-dashboard-venv\Scripts\python.exe' `
  scripts/run_source_aware_refresh.py `
  --activate-candidate 'artifacts/source-aware-refresh-candidates/source-aware-20260908T070100Z-49176-molit.candidate.db' `
  --candidate-domain molit `
  --expected-archive-size 1601179648 `
  --expected-archive-mtime '2026-09-08T16:00:08+09:00' `
  --config config/molit-baseline-recovery-20260908.json
```

The command above is a rehearsal. Add `--apply --allow-live-db` only after the
candidate and archive facts are rechecked under the shared lock. Do not add
`--publish-if-enabled`; recovery activation always remains `remotePending`.
