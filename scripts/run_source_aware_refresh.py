#!/usr/bin/env python
"""Source-aware local refresh orchestrator with independent remote publication.

The command only prints a plan unless both ``--apply`` and
``--allow-live-db`` are supplied.  Every domain is collected into its own
SQLite candidate and activated only after validation, so a later domain or
remote failure cannot roll back an already-valid local refresh.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, closing
from datetime import date, datetime, time, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time as wall_time
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "source-aware-refresh.json"
SEOUL = ZoneInfo("Asia/Seoul")
DOMAIN_ORDER = ("news", "macro", "molit", "permits")
SOURCE_CODES = {
    "news": "GOVERNED_CRE_DOCUMENTS",
    "macro": "FINANCIAL_MARKETS",
    "molit": "MOLIT_REAL_TRANSACTION",
    "permits": "src_seoul_building_permit",
}
RAW_TABLES = {
    "news": ("source_documents", "document_versions", "record_classifications"),
    "macro": ("macro_releases", "macro_observations"),
    "molit": ("source_documents", "document_versions", "collection_runs"),
    "permits": ("building_permit_snapshots", "building_permit_record_versions", "building_permit_snapshot_records"),
}


class LockBusy(RuntimeError):
    pass


class SourceChanged(RuntimeError):
    pass


class ActivationError(RuntimeError):
    """Sanitized activation failure safe for durable operational reports."""

    def __init__(self, stage: str, error: OSError, candidate: Path):
        super().__init__(stage)
        self.stage = stage
        self.error_code = type(error).__name__
        self.errno = error.errno
        self.winerror = getattr(error, "winerror", None)
        self.candidate = candidate

    def report_fields(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "errorCode": self.error_code,
            "failureStage": self.stage,
            "candidate": str(self.candidate),
        }
        if self.errno is not None:
            result["errno"] = int(self.errno)
        if self.winerror is not None:
            result["winerror"] = int(self.winerror)
        return result


ACTIVATION_RETRY_DELAYS = (0.10, 0.20, 0.40, 0.80, 1.00, 1.00, 1.00)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".source-aware.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_event(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise LockBusy("another source-aware refresh is running") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise LockBusy("another source-aware refresh is running") from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def slot_id(moment: datetime) -> str:
    return moment.astimezone(SEOUL).isoformat(timespec="minutes")


def eligible_slot(now: datetime, domain: dict[str, Any]) -> datetime | None:
    local = now.astimezone(SEOUL)
    weekdays = set(int(value) for value in domain.get("weekdays", range(1, 8)))
    candidates: list[datetime] = []
    for days_back in range(0, 9):
        day = local.date() - timedelta(days=days_back)
        if day.isoweekday() not in weekdays:
            continue
        for raw in domain["slots"]:
            hour, minute = (int(part) for part in raw.split(":"))
            candidate = datetime.combine(day, time(hour, minute), SEOUL)
            if candidate <= local:
                candidates.append(candidate)
    return max(candidates) if candidates else None


def due_domains(config: dict[str, Any], state: dict[str, Any], now: datetime) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    state_domains = state.get("domains", {})
    for name in DOMAIN_ORDER:
        latest = eligible_slot(now, config["domains"][name])
        if latest is None:
            continue
        slot = slot_id(latest)
        if str(state_domains.get(name, {}).get("lastSuccessfulSlot", "")) < slot:
            result.append((name, slot))
    return result


def sqlite_backup(source: Path, target: Path, source_connection: sqlite3.Connection | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.chmod(0o666)
        target.unlink()
    if source_connection is not None:
        with closing(sqlite3.connect(target)) as dst:
            source_connection.backup(dst)
        return
    with closing(sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)


def archive_token(path: Path) -> dict[str, Any]:
    stat = path.stat()
    with path.open("rb") as handle:
        head = handle.read(4096)
        handle.seek(max(0, stat.st_size - 4096))
        tail = handle.read(4096)
    token: dict[str, Any] = {
        "size": stat.st_size,
        "mtimeNs": stat.st_mtime_ns,
        "fileId": (stat.st_dev, stat.st_ino),
        "edgeSha256": hashlib.sha256(head + tail).hexdigest(),
    }
    # SHM lifecycle is connection-local and a zero-byte WAL may disappear when
    # our guard connection closes. Only a non-empty WAL represents data not
    # already covered by the main-file token.
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        item = wal.stat()
        token["wal"] = (item.st_size, item.st_mtime_ns, item.st_dev, item.st_ino)
    else:
        token["wal"] = None
    return token


def guarded_backup(archive: Path, candidate: Path, guard: sqlite3.Connection) -> tuple[int, dict[str, Any]]:
    baseline_version = int(guard.execute("PRAGMA data_version").fetchone()[0])
    baseline_token = archive_token(archive)
    sqlite_backup(archive, candidate, guard)
    if int(guard.execute("PRAGMA data_version").fetchone()[0]) != baseline_version or archive_token(archive) != baseline_token:
        raise SourceChanged("archive changed while candidate backup was running")
    return baseline_version, baseline_token


def prepare_archive(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    _safe_remove_sidecars(path)


def table_counts(path: Path, tables: Iterable[str]) -> dict[str, int]:
    with closing(sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)) as conn:
        present = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {table: int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]) for table in tables if table in present}


def validate_candidate(path: Path, before: dict[str, int], domain: str) -> dict[str, Any]:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    after = table_counts(path, RAW_TABLES[domain])
    regressions = {name: {"before": count, "after": after.get(name, -1)} for name, count in before.items() if after.get(name, -1) < count}
    if integrity != "ok" or foreign_keys or regressions:
        raise RuntimeError("candidate validation failed")
    return {"integrity": integrity, "foreignKeyViolations": foreign_keys, "rawRowsBefore": before, "rawRowsAfter": after}


def _safe_remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size == 0:
            try:
                sidecar.unlink()
            except OSError:
                # A concurrent read-only connection can hold the zero-byte WAL.
                # Its stat is still part of archive_token and any write is caught.
                pass


def activate_candidate(
    candidate: Path,
    archive: Path,
    backup_dir: Path,
    domain: str,
    run_id: str,
    expected_archive_token: dict[str, Any],
    *,
    retry_delays: tuple[float, ...] = ACTIVATION_RETRY_DELAYS,
) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"source-aware-{run_id}-{domain}.db"
    archive_mode = archive.stat().st_mode & 0o777
    _safe_remove_sidecars(candidate)
    if archive_token(archive) != expected_archive_token:
        raise SourceChanged("archive changed after candidate backup")
    if backup.exists():
        raise ActivationError(
            "CREATE_BACKUP", FileExistsError(17, "backup already exists"), candidate,
        )
    try:
        try:
            os.link(archive, backup)
        except OSError:
            try:
                shutil.copy2(archive, backup)
            except OSError as exc:
                raise ActivationError("CREATE_BACKUP", exc, candidate) from exc
        try:
            archive.chmod(0o666)
            candidate.chmod(0o666)
        except OSError as exc:
            raise ActivationError("PREPARE_REPLACE", exc, candidate) from exc
        for attempt in range(len(retry_delays) + 1):
            if archive_token(archive) != expected_archive_token:
                raise SourceChanged("archive changed during activation retries")
            try:
                os.replace(candidate, archive)
                break
            except OSError as exc:
                transient = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32}
                if not transient or attempt >= len(retry_delays):
                    raise ActivationError("ACTIVATE_REPLACE", exc, candidate) from exc
                wall_time.sleep(retry_delays[attempt])
        try:
            backup.chmod(0o444)
        except OSError as exc:
            raise ActivationError("PROTECT_BACKUP", exc, candidate) from exc
    finally:
        if archive.exists():
            archive.chmod(archive_mode)
    return backup


def prune_owned(directory: Path, pattern: str, keep: int) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    base = directory.resolve()
    matches = []
    for path in directory.glob(pattern):
        resolved = path.resolve()
        if resolved.parent == base and path.is_file():
            matches.append(path)
    matches.sort(key=lambda item: (item.stat().st_mtime_ns, item.name), reverse=True)
    removed: list[str] = []
    for path in matches[max(0, keep):]:
        path.chmod(0o666)
        path.unlink()
        removed.append(path.name)
    return removed


def month_groups(slot: datetime, count: int) -> list[tuple[int, int, int]]:
    anchor = slot.astimezone(SEOUL).date().replace(day=1)
    months: list[tuple[int, int]] = []
    for offset in range(count - 1, -1, -1):
        index = anchor.year * 12 + anchor.month - 1 - offset
        months.append((index // 12, index % 12 + 1))
    groups: list[tuple[int, int, int]] = []
    for year in sorted({year for year, _ in months}):
        selected = [month for item_year, month in months if item_year == year]
        groups.append((year, min(selected), max(selected)))
    return groups


def month_start_before(slot: datetime, months: int) -> date:
    local = slot.astimezone(SEOUL)
    index = local.year * 12 + local.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def latest_resumable_permit(path: Path) -> str | None:
    with closing(sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)) as conn:
        row = conn.execute(
            """SELECT snapshot_id FROM building_permit_snapshots
               WHERE source_id='src_seoul_building_permit' AND snapshot_kind='FULL'
                 AND status_code IN ('RUNNING','PARTIAL','FAILED') AND last_completed_page>0
               ORDER BY started_at DESC,snapshot_id DESC LIMIT 1"""
        ).fetchone()
    return str(row[0]) if row else None


def collector_commands(domain: str, candidate: Path, slot: str, config: dict[str, Any], report: Path) -> list[list[str]]:
    python = sys.executable
    public_env = str(resolve(ROOT, config["credentials"]["publicSources"]))
    local = datetime.fromisoformat(slot).astimezone(SEOUL)
    if domain == "news":
        return [[python, str(ROOT / "scripts/collect_daily_rss_sqlite.py"), "--db", str(candidate), "--date", local.date().isoformat(), "--lookback-days", str(config["domains"][domain]["lookbackDays"]), "--collection-slot", slot, "--apply", "--report", str(report)]]
    if domain == "macro":
        rolling_start = month_start_before(local, 24)
        return [[python, str(ROOT / "scripts/collect_financial_macro.py"), "--db", str(candidate), "--env", public_env, "--start-date", rolling_start.isoformat(), "--end-date", local.date().isoformat(), "--treasury-start-year", str(local.year), "--apply", "--report", str(report), "--artifacts", str(ROOT / "artifacts/financial-macro/raw")]]
    if domain == "molit":
        campaign = "ROLLING_CORRECTION_" + local.strftime("%Y%m%dT%H%M")
        result = []
        for index, (year, first, last) in enumerate(month_groups(local, int(config["domains"][domain]["correctionMonths"]))):
            result.append([python, str(ROOT / "scripts/run_backfill_year_molit_seoul.py"), "--db", str(candidate), "--env", public_env, "--year", str(year), "--start-month", str(first), "--end-month", str(last), "--campaign-code", campaign])
        return result
    if domain == "permits":
        command = [python, str(ROOT / "scripts/collect_seoul_building_permits.py"), "--db", str(candidate), "--env", public_env, "--snapshot-kind", "FULL", "--apply", "--report", str(report)]
        resume = latest_resumable_permit(candidate)
        if resume:
            command.extend(("--resume-snapshot", resume))
        return [command]
    raise ValueError(domain)


def run_commands(commands: list[list[str]], *, timeout_seconds: int) -> tuple[bool, str | None]:
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    for command in commands:
        try:
            completed = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=child_env,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, "COLLECTOR_TIMEOUT"
        if completed.returncode:
            return False, f"COLLECTOR_EXIT_{completed.returncode}"
    return True, None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def require_compact_permit_projection(
    normalized: dict[str, Any], compact: dict[str, Any]
) -> None:
    """Refuse to label a non-empty Seoul source as built when its mart is empty."""
    source_rows = int(normalized.get("seoulCurrentRows") or 0)
    compact_rows = int(compact.get("permitMonthlyRows") or 0)
    if source_rows > 0 and compact_rows == 0:
        raise RuntimeError(
            "compact permit projection was not built for a non-empty Seoul source"
        )


def refresh_projection(candidate: Path, domain: str) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT))
    from scripts.refresh_dashboard_serving import (
        DAILY_DATASET, PERMIT_DATASET, SEOUL_PERMIT_SOURCE, _canonical_json, _dataset_digest,
        _refresh_row_fingerprints, _tables, _upsert_freshness,
        apply_dashboard_serving_schema, refresh_building_permit_serving,
        refresh_compact_permit_metadata, refresh_daily_article_serving,
    )
    from scripts.build_compact_serving_v2 import _materialize_permit_marts
    generated = utc_now()
    with closing(sqlite3.connect(candidate)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        apply_dashboard_serving_schema(conn)
        if domain == "molit":
            from scripts.refresh_molit_current_serving import apply_migration
            apply_migration(conn)
        conn.execute("BEGIN IMMEDIATE")
        if domain == "news":
            result = refresh_daily_article_serving(conn, generated)
            if result.get("status") != "READY":
                raise RuntimeError("daily projection was not ready")
        elif domain == "permits":
            result = refresh_building_permit_serving(conn, generated)
            if result.get("status") != "READY":
                raise RuntimeError("permit projection was not ready")
            compact = _materialize_permit_marts(conn, _tables(conn))
            require_compact_permit_projection(result, compact)
            metadata = refresh_compact_permit_metadata(conn, generated)
            if metadata.get("status") != "READY":
                raise RuntimeError("compact permit projection was not ready")
            result = {**result, "compact": compact, "freshness": metadata}
        elif domain == "macro":
            conn.execute("DELETE FROM financial_macro_monthly_serving")
            conn.execute(
                """INSERT INTO financial_macro_monthly_serving(
                     series_code,source_id,region_id,observation_month,numeric_value,
                     observation_count,aggregation_code,unit_code,source_vintage_at,published_at)
                   SELECT series_code,source_id,region_id,observation_month,numeric_value,
                          observation_count,aggregation_code,unit_code,source_vintage_at,source_vintage_at
                   FROM v_financial_macro_monthly"""
            )
            series_cols = tuple(row[1] for row in conn.execute("PRAGMA table_info(macro_series)"))
            monthly_cols = tuple(row[1] for row in conn.execute("PRAGMA table_info(financial_macro_monthly_serving)"))
            fp = _refresh_row_fingerprints(conn, dataset_code="FINANCIAL_MACRO", table="macro_series", key_columns=("macro_series_id",), content_columns=series_cols, generated_at=generated)
            fp += _refresh_row_fingerprints(conn, dataset_code="FINANCIAL_MACRO", table="financial_macro_monthly_serving", key_columns=("series_code", "observation_month"), content_columns=tuple(c for c in monthly_cols if c != "published_at"), generated_at=generated)
            row_count = int(conn.execute("SELECT count(*) FROM financial_macro_monthly_serving").fetchone()[0])
            vintage = conn.execute("SELECT max(source_vintage_at) FROM financial_macro_monthly_serving").fetchone()[0]
            digest_rows = [tuple(row) for row in conn.execute(
                """SELECT table_name,row_key_json,content_sha256
                   FROM serving_row_fingerprints
                   WHERE dataset_code='FINANCIAL_MACRO' AND state_code='ACTIVE'
                   ORDER BY table_name,row_key_json"""
            )]
            digest = _dataset_digest({"rows": __import__("hashlib").sha256(_canonical_json(digest_rows).encode()).hexdigest()})
            _upsert_freshness(conn, dataset_code="FINANCIAL_MACRO", source_code="FINANCIAL_MARKETS", source_as_of_date=str(vintage or generated)[:10], generated_at=generated, source_row_count=row_count, serving_row_count=row_count, content_sha256=digest, metadata={"monthlyRows": row_count, "activeFingerprints": fp})
            result = {"status": "READY", "monthlyRows": row_count, "sourceVintageAt": vintage, "activeFingerprints": fp}
        else:
            from scripts.refresh_molit_current_serving import refresh_molit_current_serving
            result = refresh_molit_current_serving(conn, generated_at=generated)
            if result.get("status") not in {"READY", "PARTIAL_COVERAGE"}:
                raise RuntimeError("MOLIT projection did not reach a governed status")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError("projection introduced foreign-key violations")
        conn.commit()
        return result


def safe_partial_permit(candidate: Path, before: dict[str, int]) -> bool:
    try:
        validate_candidate(candidate, before, "permits")
        with closing(sqlite3.connect(f"file:{candidate.resolve().as_posix()}?mode=ro", uri=True)) as conn:
            row = conn.execute(
                """SELECT status_code,last_completed_page FROM building_permit_snapshots
                   WHERE source_id='src_seoul_building_permit' AND snapshot_kind='FULL'
                   ORDER BY started_at DESC,snapshot_id DESC LIMIT 1"""
            ).fetchone()
            # run_commands has already observed that the child exited or was
            # terminated. A remaining RUNNING row is therefore stale process
            # state, not evidence that a writer is still active. Preserve its
            # page commits so the next trigger can resume them.
            return bool(row and row[0] in {"RUNNING", "PARTIAL", "FAILED"} and int(row[1]) > 0)
    except Exception:
        return False


def collect_one(domain: str, slot: str, config: dict[str, Any], run_id: str) -> dict[str, Any]:
    archive = resolve(ROOT, config["archive"])
    candidate_dir = resolve(ROOT, config["candidates"])
    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate = candidate_dir / f"source-aware-{run_id}-{domain}.candidate.db"
    report_path = candidate_dir / f"source-aware-{run_id}-{domain}.collector.json"
    prepare_archive(archive)
    with closing(sqlite3.connect(f"file:{archive.resolve().as_posix()}?mode=ro", uri=True)) as archive_guard:
        try:
            baseline_version, baseline_token = guarded_backup(archive, candidate, archive_guard)
        except SourceChanged:
            return {"status": "FAILED_LOCAL", "slot": slot, "errorCode": "SOURCE_CHANGED_DURING_COLLECTION", "candidate": str(candidate.relative_to(ROOT))}
        before = table_counts(candidate, RAW_TABLES[domain])
        ok, error_code = run_commands(
            collector_commands(domain, candidate, slot, config, report_path),
            timeout_seconds=int(config["domains"][domain]["timeoutSeconds"]),
        )
        collector_report = read_json(report_path)
        is_partial = domain == "permits" and (collector_report.get("status") == "partial" or (not ok and safe_partial_permit(candidate, before)))
        if not ok and not is_partial:
            return {"status": "FAILED_LOCAL", "slot": slot, "errorCode": error_code, "candidate": str(candidate.relative_to(ROOT))}
        if not is_partial:
            projection = refresh_projection(candidate, domain)
        else:
            projection = {"status": "PRESERVED_LAST_KNOWN_GOOD", "reason": "INCOMPLETE_FULL_SNAPSHOT"}
        validation = validate_candidate(candidate, before, domain)
        if int(archive_guard.execute("PRAGMA data_version").fetchone()[0]) != baseline_version or archive_token(archive) != baseline_token:
            return {"status": "FAILED_LOCAL", "slot": slot, "errorCode": "SOURCE_CHANGED_DURING_COLLECTION", "candidate": str(candidate.relative_to(ROOT)), "validation": validation}
    try:
        backup = activate_candidate(candidate, archive, resolve(ROOT, config["backups"]), domain, run_id, baseline_token)
    except SourceChanged:
        return {"status": "FAILED_LOCAL", "slot": slot, "errorCode": "SOURCE_CHANGED_DURING_COLLECTION", "failureStage": "ACTIVATION_GUARD", "candidate": str(candidate.relative_to(ROOT)), "validation": validation}
    except ActivationError as exc:
        return {
            "status": "FAILED_LOCAL", "slot": slot, **exc.report_fields(),
            "candidate": str(candidate.relative_to(ROOT)), "validation": validation,
        }
    removed = prune_owned(resolve(ROOT, config["backups"]), "source-aware-*.db", int(config["retention"]["backups"]))
    return {
        "status": "COLLECTED_PARTIAL_LOCAL" if is_partial else "COLLECTED_LOCAL",
        "slot": slot,
        "collector": {key: collector_report.get(key) for key in ("status", "target_date", "lookback_days", "discovered", "inserted", "updated", "monthlyRows", "snapshotId", "pagesThisRun", "ecosAuth") if key in collector_report},
        "projection": projection,
        "validation": validation,
        "backup": str(backup.relative_to(ROOT)),
        "prunedBackups": removed,
    }


def archive_mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone(
        SEOUL
    ).isoformat(timespec="seconds")


def _owned_recovery_candidate(
    value: Path, config: dict[str, Any], domain: str
) -> Path:
    candidate = value if value.is_absolute() else ROOT / value
    candidate = candidate.resolve()
    owned_dir = resolve(ROOT, config["candidates"]).resolve()
    if candidate.parent != owned_dir:
        raise ValueError("recovery candidate is outside the owned candidate directory")
    if not (
        candidate.name.startswith("source-aware-")
        and candidate.name.endswith(f"-{domain}.candidate.db")
        and candidate.is_file()
    ):
        raise ValueError("recovery candidate name or type is invalid")
    return candidate


def recover_existing_candidate(
    config: dict[str, Any],
    candidate_value: Path,
    domain: str,
    *,
    expected_archive_size: int,
    expected_archive_mtime: str,
    apply: bool,
    allow_live_db: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and activate one already-collected, pipeline-owned candidate."""
    now = now or datetime.now(timezone.utc)
    run_id = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + f"-{os.getpid()}-recovery"
    candidate_display = str(candidate_value)
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "runId": run_id,
        "startedAt": utc_now(),
        "mode": "APPLY" if apply else "DRY_RUN",
        "operation": "ACTIVATE_EXISTING_CANDIDATE",
        "domain": domain,
        "candidate": candidate_display,
        "expectedArchiveSize": expected_archive_size,
        "expectedArchiveMtime": expected_archive_mtime,
        "publication": {
            "status": "PUBLISH_PENDING",
            "reason": "RECOVERY_ACTIVATION_ONLY",
            "remoteAttempted": False,
            "remotePending": True,
        },
    }
    try:
        candidate = _owned_recovery_candidate(candidate_value, config, domain)
        report["candidate"] = display_path(candidate)
        archive = resolve(ROOT, config["archive"]).resolve()
        actual_size = archive.stat().st_size
        actual_mtime = archive_mtime_iso(archive)
        report["actualArchiveSize"] = actual_size
        report["actualArchiveMtime"] = actual_mtime
        if actual_size != expected_archive_size or actual_mtime != expected_archive_mtime:
            raise SourceChanged("archive size or mtime differs from reviewed baseline")
        baseline_token = archive_token(archive)
        if baseline_token.get("wal") is not None:
            raise SourceChanged("archive has uncheckpointed WAL content")
        if not apply:
            report["status"] = "RECOVERY_REHEARSED"
            return report
        if not allow_live_db:
            report.update(
                status="FAILED_LOCAL", errorCode="LIVE_DB_NOT_ALLOWED",
                failureStage="RECOVERY_PREFLIGHT",
            )
            return report
        before = table_counts(archive, RAW_TABLES[domain])
        validation = validate_candidate(candidate, before, domain)
        report["validation"] = validation
        if archive_token(archive) != baseline_token:
            raise SourceChanged("archive changed while recovery candidate was validated")
        backup = activate_candidate(
            candidate, archive, resolve(ROOT, config["backups"]), domain,
            run_id, baseline_token,
        )
        report.update(
            status="RECOVERED_LOCAL",
            backup=display_path(backup),
            prunedBackups=prune_owned(
                resolve(ROOT, config["backups"]), "source-aware-*.db",
                int(config["retention"]["backups"]),
            ),
        )
    except SourceChanged:
        report.update(
            status="FAILED_LOCAL", errorCode="SOURCE_CHANGED_DURING_RECOVERY",
            failureStage="RECOVERY_ARCHIVE_GUARD",
        )
    except ActivationError as exc:
        report.update(status="FAILED_LOCAL", **exc.report_fields())
        report["candidate"] = display_path(exc.candidate)
    except OSError as exc:
        report.update(
            status="FAILED_LOCAL", errorCode=type(exc).__name__,
            failureStage="RECOVERY_PREFLIGHT",
        )
        if exc.errno is not None:
            report["errno"] = int(exc.errno)
        if getattr(exc, "winerror", None) is not None:
            report["winerror"] = int(exc.winerror)
    except (KeyError, TypeError, ValueError):
        report.update(
            status="FAILED_LOCAL", errorCode="INVALID_RECOVERY_REQUEST",
            failureStage="RECOVERY_PREFLIGHT",
        )
    finally:
        report["completedAt"] = utc_now()
    return report


def persist_recovery_report(config: dict[str, Any], report: dict[str, Any]) -> None:
    run_path = resolve(ROOT, config["runReports"]) / f"{report['runId']}.json"
    atomic_json(run_path, report)
    atomic_json(resolve(ROOT, config["latestReport"]), report)
    append_event(resolve(ROOT, config["eventLog"]), {
        "runId": report["runId"], "at": report["completedAt"],
        "domain": report.get("domain"), "operation": report["operation"],
        "localStatus": report["status"],
        "failureStage": report.get("failureStage"),
    })
    if report["mode"] == "DRY_RUN":
        return
    state_path = resolve(ROOT, config["state"])
    state = read_json(state_path) or {"schemaVersion": 1, "domains": {}}
    domain_state = state.setdefault("domains", {}).setdefault(report["domain"], {})
    domain_state["lastLocalAt"] = report["completedAt"]
    domain_state["lastLocalStatus"] = report["status"]
    domain_state["lastRecoveryCandidate"] = report["candidate"]
    if report["status"] == "RECOVERED_LOCAL":
        domain_state.pop("lastErrorCode", None)
        domain_state.pop("lastFailureStage", None)
    elif report["status"] == "FAILED_LOCAL":
        domain_state["lastErrorCode"] = report.get("errorCode")
        domain_state["lastFailureStage"] = report.get("failureStage")
    atomic_json(state_path, state)


def publish_domain(domain: str, config: dict[str, Any], *, enabled_by_cli: bool, bootstrap: bool) -> dict[str, Any]:
    publication = config["publication"]
    blocked = date.fromisoformat(publication["blockedUntil"]) if publication.get("blockedUntil") else None
    if blocked and date.today() < blocked:
        return {"status": "PUBLISH_DEFERRED", "reason": publication.get("blockedReason", "PAUSED"), "blockedUntil": blocked.isoformat(), "remoteAttempted": False, "remotePending": True}
    if not enabled_by_cli or not publication.get("enabled"):
        return {"status": "PUBLISH_PENDING", "reason": "PUBLICATION_NOT_ENABLED_FOR_RUN", "remoteAttempted": False, "remotePending": True}
    from scripts.incremental_serving_publish import publish_turso
    dataset = config["domains"][domain]["datasetCode"]
    return publish_turso(resolve(ROOT, config["archive"]), dataset, resolve(ROOT, config["credentials"]["tursoPersonal"]), apply=True, blocked_until=blocked, source_code=SOURCE_CODES[domain], batch_rows=int(publication["batchRows"]), bootstrap=bootstrap)


def orchestrate(config_path: Path, *, apply: bool, allow_live_db: bool, publish_if_enabled: bool, selected: list[str] | None, forced_slot: str | None, now: datetime | None = None) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    state_path = resolve(ROOT, config["state"])
    state = read_json(state_path) or {"schemaVersion": 1, "domains": {}}
    now = now or datetime.now(SEOUL)
    if selected:
        work = []
        for domain in selected:
            slot = forced_slot or slot_id(eligible_slot(now, config["domains"][domain]) or now)
            work.append((domain, slot))
    else:
        work = due_domains(config, state, now)
    run_id = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    report: dict[str, Any] = {"schemaVersion": 1, "runId": run_id, "startedAt": utc_now(), "mode": "APPLY" if apply else "DRY_RUN", "due": [{"domain": d, "slot": s} for d, s in work], "domains": {}}
    if not work:
        report["status"] = "NO_DOMAINS_DUE"
    elif not apply:
        report["status"] = "REHEARSED"
    elif not allow_live_db:
        raise RuntimeError("live archive activation requires --allow-live-db")
    else:
        any_local = False
        any_failed = False
        any_partial = False
        any_publication_failed = False
        for domain, slot in work:
            try:
                result = collect_one(domain, slot, config, run_id)
            except Exception as exc:
                result = {"status": "FAILED_LOCAL", "slot": slot, "errorCode": type(exc).__name__}
            local_ok = result["status"] in {"COLLECTED_LOCAL", "COLLECTED_PARTIAL_LOCAL"}
            if local_ok:
                any_local = True
                any_partial = any_partial or result["status"] == "COLLECTED_PARTIAL_LOCAL"
                domain_state = state.setdefault("domains", {}).setdefault(domain, {})
                domain_state["lastLocalStatus"] = result["status"]
                domain_state["lastLocalAt"] = utc_now()
                if result["status"] == "COLLECTED_LOCAL":
                    domain_state["lastSuccessfulSlot"] = slot
                    domain_state.pop("lastErrorCode", None)
                else:
                    domain_state["lastPartialSlot"] = slot
                atomic_json(state_path, state)
                if result["status"] == "COLLECTED_LOCAL":
                    try:
                        bootstrap_required = bool(config["publication"].get("bootstrapOnFirstPublish")) and not state.get("publication", {}).get("schemaBootstrapCompletedAt")
                        result["publication"] = publish_domain(domain, config, enabled_by_cli=publish_if_enabled, bootstrap=bootstrap_required)
                        if result["publication"].get("bootstrapStatements"):
                            state.setdefault("publication", {})["schemaBootstrapCompletedAt"] = utc_now()
                    except Exception as exc:
                        result["publication"] = {"status": "PUBLISH_FAILED", "errorCode": type(exc).__name__, "remoteAttempted": True, "remotePending": True}
                else:
                    result["publication"] = {"status": "PUBLISH_PENDING", "reason": "LOCAL_SNAPSHOT_INCOMPLETE", "remoteAttempted": False, "remotePending": True}
                domain_state["lastPublicationStatus"] = result["publication"]["status"]
                domain_state["lastPublicationAt"] = utc_now()
                atomic_json(state_path, state)
                any_publication_failed = any_publication_failed or result["publication"]["status"] == "PUBLISH_FAILED"
            else:
                any_failed = True
                state.setdefault("domains", {}).setdefault(domain, {}).update(lastLocalStatus="FAILED_LOCAL", lastLocalAt=utc_now(), lastErrorCode=result.get("errorCode"))
                atomic_json(state_path, state)
            report["domains"][domain] = result
            append_event(resolve(ROOT, config["eventLog"]), {"runId": run_id, "at": utc_now(), "domain": domain, "slot": slot, "localStatus": result["status"], "publicationStatus": result.get("publication", {}).get("status")})
        report["status"] = "COLLECTED_LOCAL" if any_local else "FAILED_LOCAL"
        if any_failed:
            report["hasDomainFailures"] = True
            if any_local:
                report["status"] = "COLLECTED_LOCAL_WITH_FAILURES"
        if any_partial:
            report["hasPartialDomains"] = True
            if not any_failed:
                report["status"] = "COLLECTED_PARTIAL_LOCAL"
        if any_publication_failed:
            report["hasPublicationFailures"] = True
            if not any_failed and not any_partial:
                report["status"] = "COLLECTED_LOCAL_WITH_PUBLICATION_FAILURES"
    report["completedAt"] = utc_now()
    run_path = resolve(ROOT, config["runReports"]) / f"{run_id}.json"
    atomic_json(run_path, report)
    atomic_json(resolve(ROOT, config["latestReport"]), report)
    prune_owned(resolve(ROOT, config["candidates"]), "source-aware-*.candidate.db", int(config["retention"]["failedCandidates"]))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--due", action="store_true", help="Run every currently due domain")
    parser.add_argument("--domain", action="append", choices=DOMAIN_ORDER, help="Run a named domain regardless of state")
    parser.add_argument("--slot", help="Explicit ISO KST slot for a manual domain run")
    parser.add_argument("--activate-candidate", type=Path, help="Activate one already-collected owned candidate without recollection")
    parser.add_argument("--candidate-domain", choices=DOMAIN_ORDER)
    parser.add_argument("--expected-archive-size", type=int)
    parser.add_argument("--expected-archive-mtime", help="Reviewed ISO timestamp with timezone, compared to whole seconds")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-live-db", action="store_true")
    parser.add_argument("--publish-if-enabled", action="store_true")
    args = parser.parse_args()
    if not args.due and not args.domain and not args.activate_candidate:
        parser.error("choose --due, at least one --domain, or --activate-candidate")
    if args.activate_candidate and (args.due or args.domain or args.slot or args.publish_if_enabled):
        parser.error("--activate-candidate cannot be combined with collection modes, --slot, or --publish-if-enabled")
    if args.activate_candidate and (
        not args.candidate_domain
        or args.expected_archive_size is None
        or not args.expected_archive_mtime
    ):
        parser.error("candidate recovery requires domain, expected archive size, and expected archive mtime")
    if not args.activate_candidate and (
        args.candidate_domain or args.expected_archive_size is not None
        or args.expected_archive_mtime
    ):
        parser.error("candidate recovery guard arguments require --activate-candidate")
    if args.slot and not args.domain:
        parser.error("--slot requires --domain")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        with exclusive_lock(resolve(ROOT, config["lock"])):
            if args.activate_candidate:
                report = recover_existing_candidate(
                    config, args.activate_candidate, args.candidate_domain,
                    expected_archive_size=args.expected_archive_size,
                    expected_archive_mtime=args.expected_archive_mtime,
                    apply=args.apply, allow_live_db=args.allow_live_db,
                )
                persist_recovery_report(config, report)
            else:
                report = orchestrate(args.config, apply=args.apply, allow_live_db=args.allow_live_db, publish_if_enabled=args.publish_if_enabled, selected=args.domain, forced_slot=args.slot)
    except LockBusy:
        report = {"status": "LOCKED", "at": utc_now()}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] in {"FAILED_LOCAL", "LOCKED"} or report.get("hasDomainFailures") or report.get("hasPartialDomains") or report.get("hasPublicationFailures"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
