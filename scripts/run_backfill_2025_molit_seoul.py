from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import ingest_partition, month_windows, parse_molit_nrg_trade_xml


SEOUL_DISTRICTS = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}

parser = argparse.ArgumentParser(description="Run resumable 2025 MOLIT Seoul non-residential trade backfill")
parser.add_argument("--db", default="data/market.db")
parser.add_argument("--env", default="C:/10137_WorkSpace/env/.env")
parser.add_argument("--district", choices=sorted(SEOUL_DISTRICTS))
parser.add_argument("--month", type=int)
parser.add_argument("--sleep", type=float, default=0.15)
args = parser.parse_args()

values = {}
for raw in Path(args.env).read_text(encoding="utf-8-sig").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = line.split("=", 1)
    values[name.strip()] = value.strip().strip('"').strip("'")
api_key = values.get("DATA_GO_KR_KEY")
if not api_key:
    raise SystemExit("DATA_GO_KR_KEY is not configured")

windows = month_windows(2025)
if args.month is not None:
    if args.month < 1 or args.month > 12:
        raise SystemExit("--month must be between 1 and 12")
    windows = [windows[args.month - 1]]
districts = SEOUL_DISTRICTS
if args.district:
    districts = {args.district: SEOUL_DISTRICTS[args.district]}

endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
summary = []
for lawd_cd, district_name in districts.items():
    for start_date, end_date in windows:
        deal_ym = start_date[:7].replace("-", "")
        all_documents = []
        total_count = 0
        total_pages = 1
        page = 1
        while page <= total_pages:
            params = {
                "serviceKey": api_key,
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": deal_ym,
                "pageNo": str(page),
                "numOfRows": "1000",
            }
            url = endpoint + "?" + urllib.parse.urlencode(params)
            raw = urllib.request.urlopen(url, timeout=45).read()
            root = ET.fromstring(raw)
            if page == 1:
                total_count = int((root.findtext(".//totalCount") or "0").strip() or "0")
                total_pages = max(1, math.ceil(total_count / 1000))
            all_documents.extend(parse_molit_nrg_trade_xml(raw, lawd_cd=lawd_cd, deal_ym=deal_ym))
            page += 1
            if args.sleep:
                time.sleep(args.sleep)

        query_description = f"MOLIT RTMS NRG trade; LAWD_CD={lawd_cd}; DEAL_YMD={deal_ym}; identity=record-hash-occurrence-v2"
        result = ingest_partition(
            db_path=Path(args.db),
            source_code="MOLIT_REAL_TRANSACTION",
            job_code=f"BACKFILL_2025_MOLIT_RTMS_NRG_TRADE_{lawd_cd}",
            category_code="SALE",
            window_start=f"{start_date}T00:00:00Z",
            window_end=f"{end_date}T00:00:00Z",
            query_rendered=query_description,
            documents=all_documents,
            runner_version="backfill-2025.1",
        )
        row = {
            "district_code": lawd_cd,
            "district_name": district_name,
            "start": start_date,
            "end_exclusive": end_date,
            "api_total_count": total_count,
            "parsed_documents": len(all_documents),
            "inserted": result.inserted_count,
            "updated": result.updated_count,
            "skipped": result.skipped_existing_run,
            "run_id": result.run_id,
        }
        summary.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

output = Path("artifacts/backfill-2025-molit-seoul-summary.json")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"campaign": "BACKFILL_2025", "partitions": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"completed_partitions": len(summary), "summary": str(output)}, ensure_ascii=False), flush=True)
