from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import ingest_partition, parse_google_news_rss


def main() -> None:
    cfg = json.loads((ROOT / "campaigns/backfill-2025-sale-process-case-depth.json").read_text(encoding="utf-8"))
    db = ROOT / "data/market.db"
    start = datetime(2025,1,1,tzinfo=timezone.utc)
    end = datetime(2026,1,1,tzinfo=timezone.utc)
    summary=[]
    for code,asset_query in cfg["assets"].items():
        query=f"{asset_query} {cfg['processTerms']} after:2024-12-31 before:2026-01-01"
        url="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":query,"hl":"ko","gl":"KR","ceid":"KR:ko"})
        raw = None
        error = None
        for attempt in range(1, 4):
            try:
                raw=urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 Hermes CRE case research"}),timeout=45).read()
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if attempt < 3:
                    time.sleep(10 * attempt)
        if raw is None:
            row={"assetCode":code,"status":"FAILED","errorClass":error.split(':',1)[0],"discovered":0,"inserted":0,"updated":0}
            summary.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
            continue
        docs=parse_google_news_rss(raw,start=start,end=end)
        result=ingest_partition(
            db_path=db,source_code=cfg["sourceCode"],job_code=f"BACKFILL_2025_BID_DETAIL_{code}",
            category_code=cfg["categoryCode"],window_start="2025-01-01T00:00:00Z",window_end="2026-01-01T00:00:00Z",
            query_rendered=query,documents=docs,runner_version=cfg["runnerVersion"],
        )
        row={"assetCode":code,"status":"COMPLETED","discovered":result.discovered_count,"inserted":result.inserted_count,"updated":result.updated_count,"runId":result.run_id}
        summary.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
    out={"campaign":cfg["campaignCode"],"completedAt":datetime.now(timezone.utc).isoformat(),"queries":len(summary),"discovered":sum(r['discovered'] for r in summary),"inserted":sum(r['inserted'] for r in summary),"updated":sum(r['updated'] for r in summary),"partitions":summary}
    (ROOT/"artifacts/backfill-2025-sale-process-case-depth-summary.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:out[k] for k in ('queries','discovered','inserted','updated')},ensure_ascii=False))

if __name__=="__main__": main()
