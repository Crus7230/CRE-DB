from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import html
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import DiscoveredDocument, ingest_partition


def load_key(env_path: Path) -> str:
    values = {}
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    value = values.get("DART_API_KEY")
    if not value:
        raise SystemExit("DART_API_KEY is not configured")
    return value


def decode_xml(data: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def clean_xml(text: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_document(task: dict, api_key: str) -> dict:
    error = None
    for attempt in range(1, 4):
        try:
            query = urllib.parse.urlencode({"crtfc_key": api_key, "rcept_no": task["receipt_no"]})
            req = urllib.request.Request(
                "https://opendart.fss.or.kr/api/document.xml?" + query,
                headers={"User-Agent": "Hermes CRE official filing research"},
            )
            payload = urllib.request.urlopen(req, timeout=45).read()
            if not payload.startswith(b"PK"):
                try:
                    root = ET.fromstring(payload)
                    status = root.findtext("status") or "UNKNOWN"
                    message = root.findtext("message") or "OpenDART document error"
                    raise RuntimeError(f"OpenDARTStatus{status}: {message}")
                except ET.ParseError:
                    raise RuntimeError("OpenDARTNonZipResponse")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = sorted(archive.namelist())
                sections = [clean_xml(decode_xml(archive.read(name))) for name in names]
            stored_text = "\n\n".join(section for section in sections if section)
            if not stored_text:
                raise ValueError("empty filing text")
            metadata = dict(task["metadata"])
            metadata.update({
                "document_api": "OpenDART document.xml",
                "document_file_count": len(names),
                "full_text_collected_at": datetime.now(timezone.utc).isoformat(),
            })
            doc = DiscoveredDocument(
                canonical_url=task["canonical_url"], external_key=task["receipt_no"],
                title=task["title"], publisher_name=metadata.get("filer_name"),
                published_at=task["published_at"], snippet_text=task["snippet_text"],
                document_type="OFFICIAL_FILING", rights_status="FULL_STORAGE_ALLOWED",
                stored_text=stored_text, metadata=metadata,
            )
            return {**task, "status": "OK", "document": doc, "text_bytes": len(stored_text.encode("utf-8"))}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
    return {**task, "status": "FAILED", "error": error}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/market.db")
    parser.add_argument("--env", default="C:/10137_WorkSpace/env/.env")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    db = (ROOT / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db)
    api_key = load_key(Path(args.env))
    con = sqlite3.connect(db)
    rows = con.execute(
        """SELECT d.external_document_key,d.canonical_url,v.title,v.published_at,
                  v.snippet_text,v.metadata_json
           FROM source_documents d
           JOIN collection_sources s ON s.source_id=d.source_id
           JOIN document_versions v ON v.document_id=d.document_id
           WHERE s.source_code='OPENDART'
             AND v.published_at>='2025-01-01' AND v.published_at<'2026-01-01'
             AND (v.title LIKE '%유형자산양도%' OR v.title LIKE '%유형자산양수%')
             AND v.version_no=(SELECT max(v2.version_no) FROM document_versions v2 WHERE v2.document_id=d.document_id)
             AND v.stored_text IS NULL
           ORDER BY v.published_at,d.external_document_key"""
    ).fetchall()
    con.close()
    if args.limit is not None:
        rows = rows[:args.limit]
    tasks = [{
        "receipt_no": row[0], "canonical_url": row[1], "title": row[2],
        "published_at": row[3], "snippet_text": row[4],
        "metadata": json.loads(row[5] or "{}"),
    } for row in rows]
    fetched: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(fetch_document, task, api_key) for task in tasks]
        for future in as_completed(futures):
            result = future.result()
            fetched.append(result)
            print(json.dumps({
                "receipt_no": result["receipt_no"], "status": result["status"],
                "text_bytes": result.get("text_bytes"), "error_class": (result.get("error") or "").split(":",1)[0] or None,
            }, ensure_ascii=False), flush=True)
    by_month: dict[str, list[DiscoveredDocument]] = {}
    for result in fetched:
        if result["status"] == "OK":
            month = result["published_at"][:7]
            by_month.setdefault(month, []).append(result["document"])
    ingested = []
    for month, docs in sorted(by_month.items()):
        year, mon = map(int, month.split("-"))
        next_year, next_month = (year + 1, 1) if mon == 12 else (year, mon + 1)
        start = f"{year:04d}-{mon:02d}-01T00:00:00Z"
        end = f"{next_year:04d}-{next_month:02d}-01T00:00:00Z"
        result = ingest_partition(
            db_path=db, source_code="OPENDART",
            job_code="BACKFILL_2025_OPENDART_SALE_DOCUMENT_TEXT_V2",
            category_code="SALE", window_start=start, window_end=end,
            query_rendered="OpenDART document.xml full text for 2025 유형자산양도/양수 filings",
            documents=docs, runner_version="backfill-2025-dart-document-text-v2",
        )
        ingested.append({"month": month, "documents": len(docs), "inserted": result.inserted_count, "updated": result.updated_count})
    summary = {
        "attempted": len(tasks), "downloaded": sum(r["status"] == "OK" for r in fetched),
        "failed": sum(r["status"] == "FAILED" for r in fetched),
        "textBytes": sum(r.get("text_bytes", 0) for r in fetched),
        "ingestedByMonth": ingested,
        "failures": [{"receipt_no":r["receipt_no"],"error_class":(r.get("error") or "").split(":",1)[0]} for r in fetched if r["status"] == "FAILED"],
    }
    output = ROOT / "artifacts" / "backfill-2025-opendart-sale-document-text-v2-summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
