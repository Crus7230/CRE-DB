"""Refresh the full archive before analytics, then verify the serving sync.

Default mode builds and validates a disposable candidate without replacing the
archive or committing PostgreSQL changes. No raw/canonical PostgreSQL writes.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_analytics_v350_supabase import run as sync_analytics
from scripts.merge_supabase_active_into_full_archive import merge_archive
from scripts.refresh_sqlite_sub_from_supabase import activate
from scripts.run_daily_analytics_refresh import (
    AlreadyRunning, analytics_file_lock, run_daily_refresh,
)

DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
SYNC_MARKER = ROOT / "data/.supabase-analytics-sync-enabled"
PIPELINE_VERSION = "SOURCE_MERGE_ANALYZE_SYNC_V1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parsed_time(value: str | None) -> datetime:
    if not value:
        raise RuntimeError("source freshness timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def validate_freshness(merge: dict, *, now: datetime, max_age_hours: float) -> dict:
    source = merge["source_freshness"]
    candidate = merge["candidate_freshness"]
    remote_latest = parsed_time(source["rss_latest_collected_at"])
    local_latest = parsed_time(candidate["rss_latest_collected_at"])
    age = (now - remote_latest).total_seconds() / 3600
    if age > max_age_hours or age < -1:
        raise RuntimeError("RSS source is stale or future-dated; analytics refresh stopped")
    if local_latest < remote_latest:
        raise RuntimeError("archive candidate is behind the Supabase snapshot")
    if candidate["document_versions"] < source["document_versions"]:
        raise RuntimeError("archive candidate lost source document versions")
    return {"checkedAt": now.isoformat(), "sourceAgeHours": round(age, 3),
            "maximumAgeHours": max_age_hours, "source": source, "archive": candidate}


def validate_candidate(path: Path, analytics: dict) -> dict:
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        run = conn.execute(
            "SELECT status_code,completed_at FROM analytics_refresh_runs WHERE analytics_refresh_run_id=?",
            (analytics["runId"],),
        ).fetchone()
    if integrity != "ok" or fk_count or not run or run[0] != "COMPLETED":
        raise RuntimeError("post-analysis candidate validation failed")
    return {"integrity": integrity, "foreignKeyViolations": fk_count,
            "analyticsCompletedAt": run[1]}


def append_log(path: Path, event: str, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    item = {"timestamp": utc_now(), "event": event, "pipelineVersion": PIPELINE_VERSION,
            "pipelineRunId": report["pipelineRunId"], "status": report["status"],
            "stage": report.get("stage"), "exceptionType": report.get("exceptionType")}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def enter_stage(report: dict, stage: str, log_path: Path) -> None:
    report["stage"] = stage
    append_log(log_path, "STAGE_STARTED", report)


def run_pipeline(*, db: Path, env_file: Path, apply: bool, sync: bool,
                 max_attempts: int = 3, max_source_age_hours: float = 36,
                 report_path: Path, log_path: Path,
                 now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    run_id = "market-refresh-" + now.strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    candidate = db.with_name(f"{db.stem}.{run_id}.candidate.db")
    report = {"pipelineVersion": PIPELINE_VERSION, "pipelineRunId": run_id,
              "startedAt": utc_now(), "status": "RUNNING", "apply": apply,
              "syncRequested": sync, "candidate": str(candidate), "stage": "lock"}
    try:
        # The legacy analytics CLI uses this exact lock too. Hold it through
        # snapshot creation, analysis, activation, and serving payload readback.
        with analytics_file_lock(db.with_suffix(db.suffix + ".analytics.lock")):
            report["stage"] = "merge"
            append_log(log_path, "STARTED", report)
            report["merge"] = merge_archive(db, candidate, env_file)
            enter_stage(report, "source_freshness", log_path)
            report["freshness"] = validate_freshness(
                report["merge"], now=now, max_age_hours=max_source_age_hours,
            )
            enter_stage(report, "analytics", log_path)
            # Mutate the candidate only, even in rehearsal mode.
            with closing(sqlite3.connect(candidate, timeout=5)) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                report["analytics"] = run_daily_refresh(
                    conn, apply=True, max_attempts=max_attempts,
                    reference_date=now.astimezone(ZoneInfo("Asia/Seoul")).date(),
                )
                checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint and checkpoint[0]:
                    raise RuntimeError("post-analysis candidate WAL checkpoint was blocked")
            enter_stage(report, "candidate_validation", log_path)
            report["validation"] = validate_candidate(candidate, report["analytics"])
            if sync:
                enter_stage(report, "sync_rehearsal", log_path)
                report["syncRehearsal"] = sync_analytics(
                    env_file, candidate, apply=False, sync_only=True, window_days=90,
                )
            if apply:
                enter_stage(report, "activate", log_path)
                report["activation"] = activate(candidate, db)
                if sync:
                    enter_stage(report, "sync_apply", log_path)
                    report["sync"] = sync_analytics(
                        env_file, db, apply=True, sync_only=True, window_days=90,
                    )
                    report["status"] = "COMPLETED"
                else:
                    report["status"] = "LOCAL_ONLY_SYNC_DISABLED"
            else:
                report["status"] = "REHEARSED"
            report["stage"] = "finished"
            report["completedAt"] = utc_now()
            append_log(log_path, report["status"], report)
    except AlreadyRunning:
        report.update(status="ALREADY_RUNNING", completedAt=utc_now())
        append_log(log_path, "ALREADY_RUNNING", report)
    except (Exception, SystemExit) as error:
        # Never log connection strings or raw database exception text.
        report.update(status="FAILED", exceptionType=type(error).__name__, completedAt=utc_now())
        append_log(log_path, "FAILED", report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-live-db", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sync", action="store_true", help="explicit analytics-only serving sync")
    mode.add_argument("--sync-if-enabled", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-source-age-hours", type=float, default=36)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/market-refresh-latest.json")
    parser.add_argument("--log", type=Path, default=ROOT / "logs/market-refresh-pipeline.jsonl")
    args = parser.parse_args()
    db = args.db.resolve()
    if args.apply and db == DEFAULT_DB.resolve() and not args.allow_live_db:
        parser.error("live archive activation requires --allow-live-db")
    if not 0 < args.max_source_age_hours <= 168:
        parser.error("max source age must be between 0 and 168 hours")
    report = run_pipeline(
        db=db, env_file=args.env_file.resolve(), apply=args.apply,
        sync=args.sync or (args.sync_if_enabled and SYNC_MARKER.is_file()),
        max_attempts=args.max_attempts, max_source_age_hours=args.max_source_age_hours,
        report_path=args.report, log_path=args.log,
    )
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] == "ALREADY_RUNNING":
        raise SystemExit(75)
    if report["status"] == "FAILED":
        raise SystemExit(1)
    if args.sync_if_enabled and report["status"] == "LOCAL_ONLY_SYNC_DISABLED":
        raise SystemExit(78)


if __name__ == "__main__":
    main()
