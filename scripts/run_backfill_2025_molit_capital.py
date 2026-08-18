from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import ingest_partition, month_windows, parse_molit_nrg_trade_xml


parser = argparse.ArgumentParser(description="Run resumable 2025 MOLIT Incheon/Gyeonggi non-residential trade backfill")
parser.add_argument("--db", default="data/market.db")
parser.add_argument("--env", default="C:/10137_WorkSpace/env/.env")
parser.add_argument("--manifest", default="config/molit-2025-capital-region-codes.json")
parser.add_argument("--region", choices=("incheon", "gyeonggi", "capital"), default="capital")
parser.add_argument("--district")
parser.add_argument("--month", type=int)
parser.add_argument("--sleep", type=float, default=0.15)
parser.add_argument("--retries", type=int, default=3)
parser.add_argument("--force-fetch", action="store_true")
args = parser.parse_args()


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def completed_partition(
    db_path: Path,
    *,
    job_code: str,
    start: str,
    query_rendered: str,
) -> dict | None:
    if not db_path.exists():
        return None
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            """SELECT cr.run_id, cr.discovered_count, cr.inserted_count, cr.updated_count
               FROM collection_runs cr
               JOIN collection_jobs j ON j.job_id = cr.job_id
               WHERE j.job_code = ? AND cr.scheduled_for = ?
                 AND cr.query_rendered = ? AND cr.status_code = 'COMPLETED'
               ORDER BY cr.completed_at DESC LIMIT 1""",
            (job_code, start, query_rendered),
        ).fetchone()
        if row is None:
            return None
        return {"run_id": row[0], "discovered": row[1], "inserted": row[2], "updated": row[3]}
    finally:
        con.close()


def fetch_page(url: str, *, retries: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return urllib.request.urlopen(url, timeout=45).read()
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 4))
    assert last_error is not None
    raise last_error


manifest_path = Path(args.manifest)
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
region_keys = ("incheon", "gyeonggi") if args.region == "capital" else (args.region,)
districts: dict[str, dict[str, str]] = {}
for region_key in region_keys:
    region = manifest["regions"][region_key]
    for code, name in region["districts"].items():
        districts[code] = {"region": region_key, "region_name": region["name"], "district_name": name}
if args.district:
    if args.district not in districts:
        raise SystemExit(f"--district {args.district} is not in selected region manifest")
    districts = {args.district: districts[args.district]}

if args.month is not None and not 1 <= args.month <= 12:
    raise SystemExit("--month must be between 1 and 12")
windows = month_windows(2025)
if args.month is not None:
    windows = [windows[args.month - 1]]

api_key = read_env(Path(args.env)).get("DATA_GO_KR_KEY")
if not api_key:
    raise SystemExit("DATA_GO_KR_KEY is not configured")
if args.retries < 1:
    raise SystemExit("--retries must be at least 1")

endpoint = "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
manifest_version = manifest["manifestVersion"]
manifest_sha = manifest["source"]["zipSha256"]
summary: list[dict] = []
for lawd_cd, district in districts.items():
    for start_date, end_date in windows:
        deal_ym = start_date[:7].replace("-", "")
        job_code = f"BACKFILL_2025_MOLIT_RTMS_NRG_TRADE_{lawd_cd}"
        query_description = (
            f"MOLIT RTMS NRG trade; LAWD_CD={lawd_cd}; DEAL_YMD={deal_ym}; "
            f"identity=record-hash-occurrence-v2; region-manifest={manifest_version}; source-sha256={manifest_sha}"
        )
        checkpoint = None if args.force_fetch else completed_partition(
            Path(args.db), job_code=job_code, start=f"{start_date}T00:00:00Z", query_rendered=query_description
        )
        if checkpoint:
            row = {
                "region": district["region"], "region_name": district["region_name"],
                "district_code": lawd_cd, "district_name": district["district_name"],
                "start": start_date, "end_exclusive": end_date,
                "api_total_count": checkpoint["discovered"], "parsed_documents": checkpoint["discovered"],
                "inserted": checkpoint["inserted"], "updated": checkpoint["updated"],
                "skipped": True, "run_id": checkpoint["run_id"], "pages": 0,
            }
            summary.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            continue

        all_documents = []
        total_count = 0
        total_pages = 1
        page = 1
        while page <= total_pages:
            params = {
                "serviceKey": api_key, "LAWD_CD": lawd_cd, "DEAL_YMD": deal_ym,
                "pageNo": str(page), "numOfRows": "1000",
            }
            raw = fetch_page(endpoint + "?" + urllib.parse.urlencode(params), retries=args.retries)
            root = ET.fromstring(raw)
            if page == 1:
                total_count = int((root.findtext(".//totalCount") or "0").strip() or "0")
                total_pages = max(1, math.ceil(total_count / 1000))
            all_documents.extend(parse_molit_nrg_trade_xml(raw, lawd_cd=lawd_cd, deal_ym=deal_ym))
            page += 1
            if args.sleep:
                time.sleep(args.sleep)
        if len(all_documents) != total_count:
            raise RuntimeError(
                f"pagination mismatch LAWD_CD={lawd_cd} DEAL_YMD={deal_ym}: "
                f"totalCount={total_count} parsed={len(all_documents)}"
            )

        result = ingest_partition(
            db_path=Path(args.db), source_code="MOLIT_REAL_TRANSACTION",
            job_code=job_code, category_code="SALE",
            window_start=f"{start_date}T00:00:00Z", window_end=f"{end_date}T00:00:00Z",
            query_rendered=query_description, documents=all_documents,
            runner_version="backfill-2025.2",
        )
        row = {
            "region": district["region"], "region_name": district["region_name"],
            "district_code": lawd_cd, "district_name": district["district_name"],
            "start": start_date, "end_exclusive": end_date,
            "api_total_count": total_count, "parsed_documents": len(all_documents),
            "inserted": result.inserted_count, "updated": result.updated_count,
            "skipped": result.skipped_existing_run, "run_id": result.run_id, "pages": total_pages,
        }
        summary.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

output = Path(f"artifacts/backfill-2025-molit-{args.region}-summary.json")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps(
        {
            "campaign": "BACKFILL_2025", "source": "MOLIT_REAL_TRANSACTION",
            "manifest": str(manifest_path), "manifestVersion": manifest_version,
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "partitions": summary,
        },
        ensure_ascii=False, indent=2,
    ),
    encoding="utf-8",
)
print(json.dumps({"completed_partitions": len(summary), "summary": str(output)}, ensure_ascii=False), flush=True)
