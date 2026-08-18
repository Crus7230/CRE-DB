from __future__ import annotations

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

from collector.backfill_2025 import ingest_partition, parse_google_news_rss, render_google_query


def collect(job_code: str, category: str, base_query: str, start_date: str, end_date: str):
    query = render_google_query(base_query, start_date, end_date)
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    )
    raw = urllib.request.urlopen(url, timeout=45).read()
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    documents = parse_google_news_rss(raw, start=start, end=end)
    result = ingest_partition(
        db_path=ROOT / "data" / "market.db",
        source_code="GOOGLE_NEWS_RSS",
        job_code=job_code,
        category_code=category,
        window_start=f"{start_date}T00:00:00Z",
        window_end=f"{end_date}T00:00:00Z",
        query_rendered=query,
        documents=documents,
        runner_version="backfill-2025.1-recovery",
    )
    return {
        "job_code": job_code,
        "category": category,
        "start": start_date,
        "end_exclusive": end_date,
        "discovered": result.discovered_count,
        "inserted": result.inserted_count,
        "updated": result.updated_count,
        "skipped": result.skipped_existing_run,
        "run_id": result.run_id,
    }


sale_query = "(오피스 OR 빌딩 OR 물류센터 OR 데이터센터 OR 호텔 OR 리조트 OR 상가 OR 쇼핑몰 OR 지식산업센터 OR 개발부지) (매각 OR 매각주관사 OR 예비입찰 OR 본입찰 OR 우선협상대상자 OR 매매계약 OR 거래종결)"
sale_windows = [
    ("2025-02-01", "2025-02-08"),
    ("2025-02-08", "2025-02-15"),
    ("2025-02-15", "2025-02-22"),
    ("2025-02-22", "2025-03-01"),
]
investment_queries = [
    ("BACKFILL_2025_GOOGLE_NEWS_RSS_INVESTMENT_BUNDLE_A", "(리츠 OR 부동산펀드 OR 자산운용사) (취득 OR 자산편입 OR 출자 OR 투자 OR 클로징)"),
    ("BACKFILL_2025_GOOGLE_NEWS_RSS_INVESTMENT_BUNDLE_B", "(연기금 OR 공제회 OR 기관투자자) (부동산 OR 리츠 OR 부동산펀드) (출자 OR 투자 OR 약정 OR 공동투자)"),
]
rows = []
for start_date, end_date in sale_windows:
    rows.append(collect("BACKFILL_2025_GOOGLE_NEWS_RSS_SALE_WEEKLY", "SALE", sale_query, start_date, end_date))
    time.sleep(0.5)
for job_code, query in investment_queries:
    rows.append(collect(job_code, "INVESTMENT", query, "2025-04-01", "2025-05-01"))
    time.sleep(0.5)

output = ROOT / "artifacts" / "backfill-2025-recovery-summary.json"
output.write_text(json.dumps({"partitions": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"partitions": rows, "summary": str(output)}, ensure_ascii=False))
