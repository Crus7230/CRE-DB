#!/usr/bin/env python
"""Collect daily CRE Google News RSS into a validated SQLite candidate.

The live archive is never mutated in place. A consistent SQLite backup is
collected, classified separately by downstream jobs, validated, and atomically
activated only with --apply --allow-live-db.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import DiscoveredDocument, ingest_partition
from scripts.collect_daily_rss_supabase import (
    collection_slot_key,
    fetch_partition,
    parse_collection_slot,
    utc_window_for_seoul_day,
)
from scripts.process_daily_rss_classifications import process_daily_rss_classifications

DEFAULT_DB = ROOT / "data" / "market.db"
DEFAULT_CONFIG = ROOT / "campaigns" / "rolling-2026-current.json"
RUNNER_VERSION = "daily-google-news-rss-sqlite-v1"
SEOUL = ZoneInfo("Asia/Seoul")
Fetcher = Callable[[str, date], tuple[str, list[DiscoveredDocument]]]


def query_identity(query: str, collection_slot: str) -> str:
    return f"{query}\ncollection_slot={collection_slot}"


def collect_partitions(
    *,
    db_path: Path,
    categories: dict[str, str],
    target: date,
    lookback_days: int,
    collection_slot: str,
    fetcher: Fetcher = fetch_partition,
) -> dict[str, int]:
    if not 1 <= lookback_days <= 7:
        raise ValueError("lookback_days must be between 1 and 7")
    summaries = []
    days = [target - timedelta(days=offset) for offset in reversed(range(lookback_days))]
    for day in days:
        start, end = utc_window_for_seoul_day(day)
        window_start = start.isoformat(timespec="seconds").replace("+00:00", "Z")
        window_end = end.isoformat(timespec="seconds").replace("+00:00", "Z")
        for category_code, base_query in categories.items():
            query, documents = fetcher(base_query, day)
            result = ingest_partition(
                db_path=db_path,
                source_code="GOOGLE_NEWS_RSS",
                job_code=f"DAILY_GOOGLE_NEWS_RSS_{category_code}",
                category_code=category_code,
                window_start=window_start,
                window_end=window_end,
                query_rendered=query_identity(query, collection_slot),
                documents=documents,
                runner_version=RUNNER_VERSION,
                cursor_metadata={"collection_slot": collection_slot},
                job_version=2,
                cadence_code="DAILY",
            )
            summaries.append(result)
    return {
        "partitions": len(summaries),
        "skipped_partitions": sum(item.skipped_existing_run for item in summaries),
        "discovered": sum(item.discovered_count for item in summaries if not item.skipped_existing_run),
        "inserted": sum(item.inserted_count for item in summaries if not item.skipped_existing_run),
        "updated": sum(item.updated_count for item in summaries if not item.skipped_existing_run),
    }


def retire_shadowed_v1_daily_jobs(db_path: Path) -> int:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute("""
            UPDATE collection_jobs AS legacy
               SET is_active=0,
                   valid_to=COALESCE(
                       valid_to,
                       CASE WHEN date('now') > valid_from
                            THEN date('now')
                            ELSE date(valid_from,'+1 day') END
                   )
             WHERE legacy.job_version=1
               AND legacy.is_active=1
               AND legacy.job_code LIKE 'DAILY_GOOGLE_NEWS_RSS_%'
               AND EXISTS (
                   SELECT 1 FROM collection_jobs AS current
                    WHERE current.job_code=legacy.job_code
                      AND current.job_version=2
                      AND current.is_active=1
               )
        """)
        conn.commit()
        return cursor.rowcount


def classify_candidate(
    db_path: Path,
    *,
    from_date: date,
    to_date: date,
    collection_slot: str,
) -> dict[str, object]:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        return process_daily_rss_classifications(
            conn,
            schema=None,
            from_date=from_date,
            to_date=to_date,
            collection_slot=collection_slot,
            apply=True,
        )


def copy_sqlite(source: Path, candidate: Path) -> None:
    if candidate.exists():
        candidate.chmod(0o666)
        candidate.unlink()
    with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(candidate)) as dst:
            src.backup(dst)


def activate_candidate(candidate: Path, archive: Path, backup: Path | None = None) -> None:
    archive.chmod(0o666)
    try:
        if backup is not None:
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                backup.chmod(0o666)
                backup.unlink()
            try:
                os.link(archive, backup)
            except OSError:
                shutil.copy2(archive, backup)
        candidate.chmod(0o444)
        os.replace(candidate, archive)
        if backup is not None:
            backup.chmod(0o444)
    finally:
        if archive.exists():
            archive.chmod(0o444)


def validate_sqlite(path: Path) -> dict[str, object]:
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok" or foreign_keys:
        raise RuntimeError("candidate SQLite validation failed")
    return {"integrity": integrity, "foreignKeyViolations": foreign_keys}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--lookback-days", type=int, default=2)
    parser.add_argument("--category")
    parser.add_argument("--collection-slot", type=parse_collection_slot)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-live-db", action="store_true")
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts" / "daily-rss-sqlite-latest.json")
    args = parser.parse_args()

    db = args.db.resolve()
    if args.apply and db == DEFAULT_DB.resolve() and not args.allow_live_db:
        parser.error("live archive activation requires --allow-live-db")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    categories = config["categories"]
    if args.category:
        if args.category not in categories:
            parser.error(f"unknown category: {args.category}")
        categories = {args.category: categories[args.category]}
    target = args.date or datetime.now(SEOUL).date()
    slot = args.collection_slot or collection_slot_key(datetime.now(SEOUL))
    candidate = db.with_name(f"{db.stem}.daily-rss-{slot[:10].replace('-', '')}-{slot[11:16].replace(':', '')}.candidate.db")

    report: dict[str, object] = {
        "status": "RUNNING",
        "runner": RUNNER_VERSION,
        "target_date": target.isoformat(),
        "lookback_days": args.lookback_days,
        "collection_slot": slot,
        "candidate": str(candidate),
    }
    original_mode = db.stat().st_mode
    try:
        copy_sqlite(db, candidate)
        report.update(collect_partitions(
            db_path=candidate,
            categories=categories,
            target=target,
            lookback_days=args.lookback_days,
            collection_slot=slot,
        ))
        report["retired_shadowed_v1_jobs"] = retire_shadowed_v1_daily_jobs(candidate)
        report["classification"] = classify_candidate(
            candidate,
            from_date=target - timedelta(days=args.lookback_days - 1),
            to_date=target + timedelta(days=1),
            collection_slot=slot,
        )
        report["validation"] = validate_sqlite(candidate)
        if args.apply:
            # An outer orchestrator candidate already has its own bounded backup.
            # Only direct live-archive activation creates this legacy backup.
            backup = (
                ROOT / "backups" / f"market-pre-daily-rss-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
                if db == DEFAULT_DB.resolve() else None
            )
            activate_candidate(candidate, db, backup)
            report["backup"] = str(backup)
            report["status"] = "APPLIED"
        else:
            report["status"] = "REHEARSED"
    finally:
        if db.exists():
            db.chmod(original_mode & 0o777)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
