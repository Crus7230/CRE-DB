from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import (
    ingest_partition,
    month_windows,
    parse_google_news_rss,
    render_google_query,
)


parser = argparse.ArgumentParser(description="Run resumable campaign-configured Google News RSS partitions")
parser.add_argument("--db", default="data/market.db")
parser.add_argument("--config", default="campaigns/backfill-2026-h1.json")
parser.add_argument("--category")
parser.add_argument("--month", type=int)
parser.add_argument("--sleep", type=float, default=0.5)
args = parser.parse_args()

config = json.loads(Path(args.config).read_text(encoding="utf-8"))
year = int(config["year"])
windows = month_windows(year)
configured_months = config.get("months")
if configured_months:
    windows = [windows[int(month) - 1] for month in configured_months]
if args.month is not None:
    if args.month < 1 or args.month > 12:
        raise SystemExit("--month must be between 1 and 12")
    windows = [windows[args.month - 1]]

categories = config["categories"]
if args.category:
    if args.category not in categories:
        raise SystemExit(f"unknown category: {args.category}")
    categories = {args.category: categories[args.category]}

summary = []
for category_code, base_query in categories.items():
    for start_date, end_date in windows:
        query = render_google_query(base_query, start_date, end_date)
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
        )
        raw = urllib.request.urlopen(url, timeout=45).read()
        start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
        documents = parse_google_news_rss(raw, start=start, end=end)
        result = ingest_partition(
            db_path=Path(args.db),
            source_code="GOOGLE_NEWS_RSS",
            job_code=f"{config['campaignCode']}_GOOGLE_NEWS_RSS_{category_code}",
            category_code=category_code,
            window_start=f"{start_date}T00:00:00Z",
            window_end=f"{end_date}T00:00:00Z",
            query_rendered=query,
            documents=documents,
            runner_version=config["campaignVersion"],
        )
        row = {
            "category": category_code,
            "start": start_date,
            "end_exclusive": end_date,
            "discovered": result.discovered_count,
            "inserted": result.inserted_count,
            "updated": result.updated_count,
            "skipped": result.skipped_existing_run,
            "saturated": result.discovered_count >= int(config["saturationResultCount"]),
            "run_id": result.run_id,
        }
        summary.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if args.sleep:
            time.sleep(args.sleep)

output = Path(config.get("outputArtifact", f"artifacts/{config['campaignCode'].lower().replace('_','-')}-google-news-rss-summary.json"))
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"campaign": config["campaignCode"], "partitions": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"completed_partitions": len(summary), "summary": str(output)}, ensure_ascii=False), flush=True)
