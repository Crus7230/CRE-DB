from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts" / "bid-process-2025-candidates.json"
OUTPUT = ROOT / "artifacts" / "google-news-bid-candidate-source-url-map.json"

ONE = """import json,sys
from googlenewsdecoder import gnewsdecoder
try:
 r=gnewsdecoder(sys.argv[1])
 print(json.dumps(r,ensure_ascii=False))
except Exception as e:
 print(json.dumps({'status':False,'message':type(e).__name__+': '+str(e)},ensure_ascii=False))
"""


def decode_one(doc: dict) -> dict:
    discovery_url = doc["canonicalUrl"]
    decoded = None
    error = None
    if "news.google.com/" not in discovery_url:
        decoded = discovery_url
    else:
        try:
            result = subprocess.run(
                [sys.executable, "-c", ONE, discovery_url],
                capture_output=True, text=True, encoding="utf-8", timeout=25,
            )
            line = next((line for line in reversed(result.stdout.splitlines()) if line.strip().startswith("{")), "{}")
            payload = json.loads(line)
            if payload.get("status") and payload.get("decoded_url"):
                decoded = payload["decoded_url"]
            else:
                error = str(payload.get("message") or payload)
        except subprocess.TimeoutExpired:
            error = "TimeoutExpired: 25s"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    return {
        "reviewTaskId": doc["reviewTaskId"], "title": doc["title"],
        "publishedAt": doc["publishedAt"], "discoveryUrl": discovery_url,
        "sourceUrl": decoded, "decodeStatus": "OK" if decoded else "FAILED",
        "errorClass": error.split(":", 1)[0] if error else None,
    }


def main() -> None:
    docs = json.loads(SOURCE.read_text(encoding="utf-8"))["documents"]
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(decode_one, doc): i for i,doc in enumerate(docs,1)}
        for future in as_completed(futures):
            row = future.result(); row["inputIndex"] = futures[future]
            rows.append(row)
            print(json.dumps({"index":row["inputIndex"],"status":row["decodeStatus"],"sourceUrl":row["sourceUrl"]},ensure_ascii=False),flush=True)
    rows.sort(key=lambda x:x["inputIndex"])
    result = {
        "inputDocumentCount": len(rows),
        "decodedCount": sum(r["decodeStatus"] == "OK" for r in rows),
        "failedCount": sum(r["decodeStatus"] == "FAILED" for r in rows),
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("inputDocumentCount","decodedCount","failedCount")},ensure_ascii=False))


if __name__ == "__main__":
    main()
