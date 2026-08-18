from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import ingest_partition, month_windows, parse_dart_filings


parser = argparse.ArgumentParser(description="Run resumable 2025 OpenDART sale disclosure backfill")
parser.add_argument("--db", default="data/market.db")
parser.add_argument("--env", default="C:/10137_WorkSpace/env/.env")
parser.add_argument("--month", type=int)
parser.add_argument("--sleep", type=float, default=0.25)
args = parser.parse_args()

values = {}
for raw in Path(args.env).read_text(encoding="utf-8-sig").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = line.split("=", 1)
    values[name.strip()] = value.strip().strip('"').strip("'")
api_key = values.get("DART_API_KEY")
if not api_key:
    raise SystemExit("DART_API_KEY is not configured")

windows = month_windows(2025)
if args.month is not None:
    if args.month < 1 or args.month > 12:
        raise SystemExit("--month must be between 1 and 12")
    windows = [windows[args.month - 1]]

keywords = (
    "유형자산양도", "유형자산양수", "유형자산취득",
    "유형자산 양도", "유형자산 양수", "유형자산 취득",
    "영업양도", "영업양수",
)
summary = []
for start_date, end_date in windows:
    inclusive_end = date.fromisoformat(end_date) - timedelta(days=1)
    common = {
        "crtfc_key": api_key,
        "bgn_de": start_date.replace("-", ""),
        "end_de": inclusive_end.isoformat().replace("-", ""),
        "pblntf_ty": "B",
        "page_count": "100",
    }
    all_items = []
    total_pages = 1
    page = 1
    while page <= total_pages:
        params = dict(common, page_no=str(page))
        url = "https://opendart.fss.or.kr/api/list.json?" + urllib.parse.urlencode(params)
        payload = json.loads(urllib.request.urlopen(url, timeout=45).read().decode("utf-8"))
        if payload.get("status") != "000":
            raise RuntimeError(f"OpenDART status={payload.get('status')} message={payload.get('message')}")
        if page == 1:
            total_pages = max(1, math.ceil(int(payload.get("total_count", 0)) / 100))
        all_items.extend(payload.get("list", []))
        page += 1
        if args.sleep:
            time.sleep(args.sleep)

    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    documents = parse_dart_filings(
        {"status": "000", "list": all_items},
        start=start,
        end=end,
        report_keywords=keywords,
    )
    query_description = "OpenDART list pblntf_ty=B; report keywords: " + ",".join(keywords)
    result = ingest_partition(
        db_path=Path(args.db),
        source_code="OPENDART",
        job_code="BACKFILL_2025_OPENDART_SALE_V2",
        category_code="SALE",
        window_start=f"{start_date}T00:00:00Z",
        window_end=f"{end_date}T00:00:00Z",
        query_rendered=query_description,
        documents=documents,
        runner_version="backfill-2025-dart-sale-v2",
    )
    row = {
        "start": start_date,
        "end_exclusive": end_date,
        "api_records": len(all_items),
        "filtered_documents": len(documents),
        "inserted": result.inserted_count,
        "updated": result.updated_count,
        "skipped": result.skipped_existing_run,
        "run_id": result.run_id,
    }
    summary.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)

output = Path("artifacts/backfill-2025-opendart-sale-v2-summary.json")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"campaign": "BACKFILL_2025", "partitions": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"completed_partitions": len(summary), "summary": str(output)}, ensure_ascii=False), flush=True)
