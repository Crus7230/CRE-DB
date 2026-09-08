"""Resumable Seoul Open Data building-permit snapshot collector."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.building_permits import canonical_json, utc_now  # noqa: E402
from collector.building_permit_store import (  # noqa: E402
    complete_snapshot,
    create_snapshot,
    ensure_source,
    mark_partial,
    store_seoul_page,
)

DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env")
DEFAULT_REPORT = ROOT / "artifacts/building-permits/seoul-latest.json"
SERVICE = "vBigKcrPmsrgst"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def fetch_page(key: str, start: int, end: int, *, timeout: int = 60, attempts: int = 4) -> tuple[int, list[dict[str, Any]]]:
    # Key is intentionally never logged or returned.
    url = f"http://openapi.seoul.go.kr:8088/{key}/json/{SERVICE}/{start}/{end}/"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            root = payload.get(SERVICE)
            if not isinstance(root, dict):
                result = payload.get("RESULT") or {}
                raise RuntimeError(f"Seoul API error {result.get('CODE','UNKNOWN')}: {result.get('MESSAGE','missing service root')}")
            result = root.get("RESULT") or {}
            if result.get("CODE") != "INFO-000":
                raise RuntimeError(f"Seoul API error {result.get('CODE','UNKNOWN')}: {result.get('MESSAGE','')}")
            total = int(root.get("list_total_count") or 0)
            rows = root.get("row") or []
            if not isinstance(rows, list):
                raise RuntimeError("Seoul API row payload is not a list")
            return total, rows
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 8))
    assert last_error is not None
    raise last_error


def snapshot_state(conn: sqlite3.Connection, snapshot_id: str) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM building_permit_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    if not row:
        raise ValueError(f"snapshot not found: {snapshot_id}")
    return dict(row)


def validation_summary(conn: sqlite3.Connection, snapshot_id: str) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    snapshot = snapshot_state(conn, snapshot_id)
    distributions = {
        "classification": [dict(row) for row in conn.execute(
            """SELECT c.scope_status,c.asset_type,count(*) AS permit_count,
                      round(sum(coalesce(r.total_floor_area_m2,0)),2) AS total_floor_area_m2
               FROM building_permit_snapshot_records sr
               JOIN building_permit_record_versions r ON r.record_version_id=sr.record_version_id
               JOIN building_permit_classifications c ON c.record_version_id=r.record_version_id AND c.is_current=1
               WHERE sr.snapshot_id=? GROUP BY c.scope_status,c.asset_type
               ORDER BY permit_count DESC""", (snapshot_id,)
        )],
        "mainUse": [dict(row) for row in conn.execute(
            """SELECT coalesce(r.main_use_name,'') AS main_use_name,count(*) AS permit_count
               FROM building_permit_snapshot_records sr
               JOIN building_permit_record_versions r ON r.record_version_id=sr.record_version_id
               WHERE sr.snapshot_id=? GROUP BY coalesce(r.main_use_name,'') ORDER BY permit_count DESC LIMIT 50""",
            (snapshot_id,),
        )],
        "eventCoverage": [dict(row) for row in conn.execute(
            """SELECT event_type,min(event_date) AS min_date,max(event_date) AS max_date,count(*) AS event_count
               FROM v_cre_building_permit_events GROUP BY event_type ORDER BY event_type"""
        )],
    }
    integrity = {
        "duplicateSourceKeysWithinSnapshot": conn.execute(
            """SELECT count(*) FROM (
                 SELECT r.source_record_key,count(*) n FROM building_permit_snapshot_records sr
                 JOIN building_permit_record_versions r ON r.record_version_id=sr.record_version_id
                 WHERE sr.snapshot_id=? GROUP BY r.source_record_key HAVING count(*)>1)""", (snapshot_id,)
        ).fetchone()[0],
        "orphanMemberships": conn.execute(
            """SELECT count(*) FROM building_permit_snapshot_records sr
               LEFT JOIN building_permit_record_versions r ON r.record_version_id=sr.record_version_id
               WHERE sr.snapshot_id=? AND r.record_version_id IS NULL""", (snapshot_id,)
        ).fetchone()[0],
        "foreignKeyViolations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
    }
    return {"snapshot": snapshot, "distributions": distributions, "integrity": integrity}


def collect(
    db_path: Path, env_path: Path, *, apply: bool, snapshot_kind: str, page_size: int,
    max_pages: int | None, resume_snapshot: str | None, sleep_seconds: float,
) -> dict[str, Any]:
    env = load_env(env_path)
    key = env.get("SEOUL_OPEN_DATA_GENERAL_KEY")
    if not key:
        raise SystemExit("SEOUL_OPEN_DATA_GENERAL_KEY is missing")
    if not apply:
        return {
            "status": "dry_run", "db": str(db_path), "snapshotKind": snapshot_kind,
            "pageSize": page_size, "maxPages": max_pages,
            "message": "No API request or database write performed; pass --apply.",
        }
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        feature = conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version'"
        ).fetchone()
        if not feature or feature[0] != "1.0.5":
            raise RuntimeError("building permit feature migration 1.0.5 is not installed")
        source_id = ensure_source(conn, "SEOUL_BUILDING_PERMIT")
        if resume_snapshot:
            state = snapshot_state(conn, resume_snapshot)
            if state["source_id"] != source_id or state["status_code"] not in {"RUNNING", "PARTIAL", "FAILED"}:
                raise RuntimeError("resume snapshot is not resumable for Seoul source")
            snapshot_id = resume_snapshot
            page_size = int(state["page_size"])
            conn.execute("UPDATE building_permit_snapshots SET status_code='RUNNING',error_json='{}' WHERE snapshot_id=?", (snapshot_id,))
            conn.commit()
            first_page = int(state["last_completed_page"]) + 1
        else:
            snapshot_id = create_snapshot(
                conn, source_id, snapshot_kind, page_size,
                metadata={"dataset": "OA-22404", "service": SERVICE, "collectorVersion": "1.0.0"},
            )
            first_page = 1
        page_no = first_page
        pages_this_run = 0
        source_total: int | None = None
        try:
            while True:
                start = (page_no - 1) * page_size + 1
                end = start + page_size - 1
                total, rows = fetch_page(key, start, end)
                source_total = total
                if not rows and start <= total:
                    raise RuntimeError(f"Seoul API returned no rows for expected range {start}-{end}")
                result = store_seoul_page(conn, snapshot_id, source_id, rows, page_no, start - 1)
                pages_this_run += 1
                print(canonical_json({
                    "snapshotId": snapshot_id, "page": page_no, "range": [start, end],
                    "sourceTotal": total, "fetched": result.fetched, "stored": result.stored,
                    "excluded": result.excluded, "replayed": result.replayed,
                }), flush=True)
                if end >= total:
                    break
                if max_pages is not None and pages_this_run >= max_pages:
                    break
                page_no += 1
                if sleep_seconds:
                    time.sleep(sleep_seconds)
        except Exception as exc:
            mark_partial(conn, snapshot_id, {"type": type(exc).__name__, "message": str(exc)[:1000], "failedPage": page_no})
            raise
        state = snapshot_state(conn, snapshot_id)
        total_pages = math.ceil((source_total or 0) / page_size) if source_total else 0
        is_complete = bool(source_total is not None and int(state["last_completed_page"]) >= total_pages)
        counts = json.loads(state["classification_counts_json"])
        if is_complete:
            complete_snapshot(
                conn, snapshot_id, int(source_total), int(state["fetched_count"]), int(state["stored_count"]),
                int(state["excluded_count"]), int(state["request_count"]), int(state["last_completed_page"]),
                counts, source_as_of_date=date.today().isoformat(),
            )
        else:
            mark_partial(conn, snapshot_id, {"reason": "max_pages_reached", "nextPage": int(state["last_completed_page"]) + 1})
        result = validation_summary(conn, snapshot_id)
        result.update({"status": "completed" if is_complete else "partial", "snapshotId": snapshot_id,
                       "totalPages": total_pages, "pagesThisRun": pages_this_run})
        return result
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--snapshot-kind", choices=("FULL", "PILOT"), default="FULL")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--resume-snapshot")
    parser.add_argument("--sleep", type=float, default=0.08)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 1000:
        raise SystemExit("--page-size must be between 1 and 1000")
    result = collect(
        args.db, args.env, apply=args.apply, snapshot_kind=args.snapshot_kind,
        page_size=args.page_size, max_pages=args.max_pages,
        resume_snapshot=args.resume_snapshot, sleep_seconds=max(0, args.sleep),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(canonical_json({"status": result["status"], "snapshotId": result.get("snapshotId"), "report": str(args.report)}))


if __name__ == "__main__":
    main()
