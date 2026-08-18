from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import ingest_partition, parse_google_news_rss, render_google_query


def weekly_windows(start_text: str, end_text: str):
    start = date.fromisoformat(start_text)
    end = date.fromisoformat(end_text)
    cursor = start
    while cursor < end:
        next_cursor = min(cursor + timedelta(days=7), end)
        yield cursor.isoformat(), next_cursor.isoformat()
        cursor = next_cursor


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover near-cap Google News RSS month partitions with weekly windows")
    parser.add_argument("--db", default="data/market.db")
    parser.add_argument("--config", default="campaigns/backfill-2026-h1.json")
    parser.add_argument("--summary", default="artifacts/backfill-2026-h1-google-news-rss-summary.json")
    parser.add_argument("--threshold", type=int, default=95)
    parser.add_argument("--sleep", type=float, default=0.3)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    base = json.loads(Path(args.summary).read_text(encoding="utf-8"))["partitions"]
    rows = []
    for partition in base:
        if int(partition["discovered"]) < args.threshold:
            continue
        category = partition["category"]
        base_query = config["categories"][category]
        for start_date, end_date in weekly_windows(partition["start"], partition["end_exclusive"]):
            query = render_google_query(base_query, start_date, end_date)
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
            )
            raw = urllib.request.urlopen(url, timeout=45).read()
            start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
            documents = parse_google_news_rss(raw, start=start, end=end)
            result = ingest_partition(
                db_path=Path(args.db), source_code="GOOGLE_NEWS_RSS",
                job_code=f"{config['campaignCode']}_GOOGLE_NEWS_RSS_{category}_WEEKLY_RECOVERY",
                category_code=category,
                window_start=f"{start_date}T00:00:00Z", window_end=f"{end_date}T00:00:00Z",
                query_rendered=query, documents=documents,
                runner_version=f"{config['campaignVersion']}-weekly-recovery",
            )
            row = {
                "category": category, "start": start_date, "end_exclusive": end_date,
                "discovered": result.discovered_count, "inserted": result.inserted_count,
                "updated": result.updated_count, "skipped": result.skipped_existing_run,
                "saturated": result.discovered_count >= int(config["saturationResultCount"]),
                "run_id": result.run_id,
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if args.sleep:
                time.sleep(args.sleep)
    campaign_slug = config["campaignCode"].lower().replace("_", "-")
    output = ROOT / "artifacts" / f"{campaign_slug}-google-news-rss-recovery-summary.json"
    output.write_text(json.dumps({"campaign": config["campaignCode"], "threshold": args.threshold, "partitions": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"completed_partitions": len(rows), "summary": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
