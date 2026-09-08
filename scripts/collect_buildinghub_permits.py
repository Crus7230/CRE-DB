"""Resumable MOLIT BuildingHUB permit collector partitioned by Seoul legal dong."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
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
    complete_snapshot, create_snapshot, ensure_source, mark_partial, store_buildinghub_page,
)
from scripts.collect_seoul_building_permits import load_env, snapshot_state  # noqa: E402

ENDPOINT = "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo"
DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env")
DEFAULT_ROSTER = ROOT / "config/seoul-legal-dong-codes.json"
DEFAULT_REPORT = ROOT / "artifacts/building-permits/buildinghub-latest.json"


def fetch_page(
    key: str, sigungu: str, bjdong: str, start_date: str, end_date: str,
    page_no: int, page_size: int, *, attempts: int = 4,
) -> tuple[int, list[dict[str, Any]]]:
    params = {
        "serviceKey": key, "sigunguCd": sigungu, "bjdongCd": bjdong,
        "startDate": start_date.replace("-", ""), "endDate": end_date.replace("-", ""),
        "numOfRows": str(page_size), "pageNo": str(page_no), "_type": "json",
    }
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(ENDPOINT, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            service_error = payload.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {})
            if service_error:
                raise RuntimeError(
                    f"BuildingHUB error {service_error.get('returnReasonCode','UNKNOWN')}: "
                    f"{service_error.get('returnAuthMsg') or service_error.get('errMsg','')}"
                )
            envelope = payload.get("response") or {}
            header = envelope.get("header") or {}
            if str(header.get("resultCode", "00")) not in {"00", "000"}:
                raise RuntimeError(f"BuildingHUB error {header.get('resultCode')}: {header.get('resultMsg','')}")
            body = envelope.get("body") or {}
            total = int(body.get("totalCount") or 0)
            items = body.get("items") or {}
            rows = items.get("item", []) if isinstance(items, dict) else []
            if isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list):
                raise RuntimeError("BuildingHUB item payload is not a list")
            return total, rows
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 8))
    assert last_error is not None
    raise last_error


def load_roster(path: Path, district: str | None, legal_dong: str | None) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["rows"]
    if district:
        rows = [row for row in rows if row["sigunguCd"] == district]
    if legal_dong:
        rows = [row for row in rows if row["bjdongCd"] == legal_dong]
    if not rows:
        raise ValueError("no legal-dong partition matches the requested filter")
    return rows


def collect(
    db_path: Path, env_path: Path, roster_path: Path, *, apply: bool,
    start_date: str, end_date: str, page_size: int, max_requests: int | None,
    resume_snapshot: str | None, district: str | None, legal_dong: str | None,
    sleep_seconds: float,
) -> dict[str, Any]:
    partitions = load_roster(roster_path, district, legal_dong)
    if not apply:
        return {"status": "dry_run", "partitions": len(partitions), "startDate": start_date,
                "endDate": end_date, "maxRequests": max_requests, "message": "Pass --apply to collect."}
    key = load_env(env_path).get("DATA_GO_KR_KEY")
    if not key:
        raise SystemExit("DATA_GO_KR_KEY is missing")
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        feature = conn.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='building_permit_schema_version'"
        ).fetchone()
        if not feature or feature[0] != "1.0.5":
            raise RuntimeError("building permit feature migration 1.0.5 is not installed")
        source_id = ensure_source(conn, "BUILDING_HUB")
        if resume_snapshot:
            state = snapshot_state(conn, resume_snapshot)
            if state["source_id"] != source_id or state["status_code"] not in {"RUNNING", "PARTIAL", "FAILED"}:
                raise RuntimeError("snapshot is not resumable for BuildingHUB")
            metadata = json.loads(state["metadata_json"])
            if metadata.get("startDate") != start_date or metadata.get("endDate") != end_date:
                raise RuntimeError("resume date window differs from snapshot metadata")
            cursor = json.loads(state["cursor_json"] or "{}")
            partition_index = int(cursor.get("partitionIndex", 0))
            api_page = int(cursor.get("apiPage", 1))
            global_page = int(cursor.get("globalPage", state["last_completed_page"] + 1))
            global_row = int(cursor.get("globalRow", state["fetched_count"]))
            completed_source_total = int(cursor.get("completedSourceTotal", 0))
            snapshot_id = resume_snapshot
            conn.execute("UPDATE building_permit_snapshots SET status_code='RUNNING',error_json='{}' WHERE snapshot_id=?", (snapshot_id,))
            conn.commit()
        else:
            snapshot_id = create_snapshot(
                conn, source_id, "INCREMENTAL", page_size,
                metadata={"dataset": "15136267", "operation": "getApBasisOulnInfo",
                          "startDate": start_date, "endDate": end_date,
                          "partitionCount": len(partitions), "roster": roster_path.name,
                          "filterSemantics": "crtnDay"},
            )
            partition_index = 0; api_page = 1; global_page = 1; global_row = 0; completed_source_total = 0
        requests_this_run = 0
        try:
            while partition_index < len(partitions):
                part = partitions[partition_index]
                total, rows = fetch_page(
                    key, part["sigunguCd"], part["bjdongCd"], start_date, end_date,
                    api_page, page_size,
                )
                for raw in rows:
                    raw.setdefault("sigunguCdNm", part["districtName"])
                    raw.setdefault("bjdongCdNm", part["legalDongName"])
                page_result = store_buildinghub_page(
                    conn, snapshot_id, source_id, rows, global_page, global_row
                )
                requests_this_run += 1
                global_row += len(rows)
                total_api_pages = max(1, math.ceil(total / page_size))
                if api_page >= total_api_pages:
                    completed_source_total += total
                    partition_index += 1
                    api_page = 1
                else:
                    api_page += 1
                global_page += 1
                cursor = {
                    "partitionIndex": partition_index, "apiPage": api_page,
                    "globalPage": global_page, "globalRow": global_row,
                    "completedSourceTotal": completed_source_total,
                }
                conn.execute(
                    "UPDATE building_permit_snapshots SET cursor_json=?,source_total_count=? WHERE snapshot_id=?",
                    (canonical_json(cursor), completed_source_total, snapshot_id),
                )
                conn.commit()
                print(canonical_json({
                    "snapshotId": snapshot_id, "request": requests_this_run,
                    "partition": f"{part['sigunguCd']}/{part['bjdongCd']}",
                    "partitionIndex": partition_index, "apiPageNext": api_page,
                    "partitionTotal": total, "fetched": page_result.fetched,
                    "stored": page_result.stored, "excluded": page_result.excluded,
                }), flush=True)
                if max_requests is not None and requests_this_run >= max_requests:
                    break
                if sleep_seconds:
                    time.sleep(sleep_seconds)
            state = snapshot_state(conn, snapshot_id)
            if partition_index >= len(partitions):
                counts = json.loads(state["classification_counts_json"])
                complete_snapshot(
                    conn, snapshot_id, completed_source_total, int(state["fetched_count"]),
                    int(state["stored_count"]), int(state["excluded_count"]),
                    int(state["request_count"]), int(state["last_completed_page"]), counts,
                    source_as_of_date=end_date,
                )
                status = "completed"
            else:
                mark_partial(conn, snapshot_id, {"reason": "max_requests_reached", **cursor})
                status = "partial"
        except Exception as exc:
            mark_partial(conn, snapshot_id, {"type": type(exc).__name__, "message": str(exc)[:1000],
                                                "partitionIndex": partition_index, "apiPage": api_page})
            raise
        state = snapshot_state(conn, snapshot_id)
        return {
            "status": status, "snapshotId": snapshot_id, "source": "BUILDING_HUB",
            "startDate": start_date, "endDate": end_date, "partitions": len(partitions),
            "requestsThisRun": requests_this_run, "snapshot": state,
            "integrity": {
                "foreignKeyViolations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
                "duplicateSourceKeys": conn.execute(
                    """SELECT count(*) FROM (SELECT source_record_key,count(*) n
                       FROM v_latest_building_permit_records WHERE source_id=?
                       GROUP BY source_record_key HAVING count(*)>1)""", (source_id,)
                ).fetchone()[0],
            },
        }
    finally:
        conn.close()


def main() -> None:
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--start-date", default=yesterday.isoformat())
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--district")
    parser.add_argument("--legal-dong")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--resume-snapshot")
    parser.add_argument("--sleep", type=float, default=0.08)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = collect(
        args.db, args.env, args.roster, apply=args.apply, start_date=args.start_date,
        end_date=args.end_date, page_size=args.page_size, max_requests=args.max_requests,
        resume_snapshot=args.resume_snapshot, district=args.district, legal_dong=args.legal_dong,
        sleep_seconds=max(0, args.sleep),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(canonical_json({"status": result["status"], "snapshotId": result.get("snapshotId"), "report": str(args.report)}))


if __name__ == "__main__":
    main()
