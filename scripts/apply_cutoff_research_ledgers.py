#!/usr/bin/env python
"""Import cutoff research ledgers as source documents and REVIEW_READY mentions.

No canonical events, sale processes, or terminal statuses are created here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from scripts.apply_approved_lp_manifest_postgres import insert_row, load_env, quote_ident

DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
SOURCE_ID = "src_cutoff_research_20260819"
PIPELINE = "cutoff-research-ledger-20260819-v1"
LINK_RE = re.compile(r"\[[^]]+\]\((https?://[^)]+)\)")
SECTION_MAP = {
    1: ("cat_lease", "LEASE_SIGNED"),
    2: ("cat_supply", "COMPLETED"),
    3: ("cat_supply", "PLANNED"),
    4: ("cat_permit", "PERMIT_APPROVED"),
    5: ("cat_pf", "PF_DRAWDOWN"),
    6: ("cat_invest", "INVESTMENT_REVIEWED"),
}
SALE_STAGE = {
    "CLOSED": "CLOSED",
    "CLOSED_MEDIA_FOLLOWUP": "CONDITIONS_PENDING",
    "PREFERRED_BIDDER": "PREFERRED_BIDDER_SELECTED",
    "PREFERRED_BIDDER_MEDIA_ONLY": "PREFERRED_BIDDER_SELECTED",
    "PREFERRED_NEGOTIATION_FINANCING_DELAY": "DUE_DILIGENCE",
    "PREFERRED_SPA_NOT_PROVED": "DUE_DILIGENCE",
}


def stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:24]}"


def parse_non_sale(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    section = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"## ([1-6])\.", line)
        if match:
            section = int(match.group(1))
            continue
        if not section or not line.startswith("|") or line.startswith("|---") or "event date" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 8:
            continue
        event_date, status, asset, parties, amount, area, sources, evidence = cells
        urls = LINK_RE.findall(sources)
        if not urls:
            continue
        category, default_stage = SECTION_MAP[section]
        text = (status + " " + evidence).lower()
        stage = default_stage
        if section == 2 and ("opened" in text or "개관" in text or "운영" in text):
            stage = "OPENED"
        elif section == 3 and ("started" in text or "착공" in text):
            stage = "UNDER_CONSTRUCTION"
        elif section == 4 and "conditional" in text:
            stage = "CONDITIONALLY_APPROVED"
        elif section == 5 and ("refinanced" in text or "리파이낸싱" in text or "본pf 전환" in text):
            stage = "PF_REFINANCED"
        elif section == 5 and ("proposed" in text or "추진" in text):
            stage = "MAIN_PF_ARRANGING"
        elif section == 6 and "selected" in text:
            stage = "MANAGER_SELECTED"
        elif section == 6 and ("위탁운용사 선정 공고" in text or "선정 계획" in text):
            stage = "MANAGER_RFP_OPEN"
        elif section == 6 and ("유상증자" in text or "회사채" in text):
            stage = "INVESTMENT_COMMITTED"
        records.append({
            "kind": "NON_SALE",
            "key": stable_id("nonsale", str(section), asset, event_date),
            "category": category,
            "stage": stage,
            "title": re.sub(r"\*+", "", asset),
            "summary": json.dumps({"event_date": event_date, "status": status, "parties": parties, "amount": amount, "area": area, "evidence": evidence}, ensure_ascii=False),
            "urls": urls,
            "confidence": 0.92 if "**A**" in evidence else 0.80 if "**B" in evidence else 0.62,
        })
    return records


def parse_sales(path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for process in manifest["processes"]:
        refs = process.get("source_refs", [])
        records.append({
            "kind": "SALE",
            "key": process["process_code"],
            "category": "cat_sale",
            "stage": SALE_STAGE[process["current_status"]],
            "title": process["asset"],
            "summary": json.dumps(process, ensure_ascii=False, sort_keys=True),
            "urls": [ref["url"] for ref in refs],
            "confidence": 0.55 if process["evidence_grade"].startswith("C") else 0.78,
        })
    return records


def document_type(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "kind.krx" in host:
        return "DISCLOSURE"
    if any(token in host for token in ("seoul.go.kr", "khug.or.kr", "nps.or.kr")):
        return "NOTICE"
    return "ARTICLE"


def import_records(conn: Any, *, schema: str, records: list[dict[str, Any]], apply: bool) -> dict[str, Any]:
    ns = quote_ident(schema)
    inserted = 0
    per_category: dict[str, int] = {}
    unique_urls: set[str] = set()
    with conn.transaction(force_rollback=not apply):
        inserted += insert_row(conn, schema=schema, table="collection_sources", values={
            "source_id": SOURCE_ID,
            "source_code": "CUTOFF_RESEARCH_20260819",
            "source_name": "CRE cutoff research ledgers through 2026-08-19",
            "source_kind": "MANUAL",
            "authority_tier": 3,
            "collection_policy": "MANUAL_ONLY",
        })
        for record in records:
            per_category[record["category"]] = per_category.get(record["category"], 0) + 1
            for url in record["urls"]:
                unique_urls.add(url)
                existing = conn.execute(
                    f"""SELECT d.document_id,v.document_version_id
                        FROM {ns}.source_documents d
                        JOIN {ns}.document_versions v ON v.document_id=d.document_id
                        WHERE d.canonical_url=%s ORDER BY v.version_no DESC LIMIT 1""",
                    (url,),
                ).fetchone()
                if existing:
                    document_id, version_id = existing
                else:
                    document_id = stable_id("doc", url)
                    version_id = document_id + "_v1"
                    inserted += insert_row(conn, schema=schema, table="source_documents", values={
                        "document_id": document_id,
                        "source_id": SOURCE_ID,
                        "canonical_url": url,
                        "publisher_name": urlparse(url).netloc,
                        "document_type": document_type(url),
                        "first_seen_at": "2026-08-20",
                        "last_seen_at": "2026-08-20",
                        "access_status": "ACCESSIBLE",
                    })
                    inserted += insert_row(conn, schema=schema, table="document_versions", values={
                        "document_version_id": version_id,
                        "document_id": document_id,
                        "version_no": 1,
                        "title": record["title"],
                        "published_at": None,
                        "collected_at": "2026-08-20",
                        "content_sha256": hashlib.sha256(record["summary"].encode("utf-8")).hexdigest(),
                        "snippet_text": record["summary"],
                        "rights_status": "EXCERPT_ALLOWED",
                        "metadata_json": json.dumps({"cutoff_date":"2026-08-19","research_record":record["key"]}, ensure_ascii=False),
                    })
                extraction_id = stable_id("ext", PIPELINE, version_id)
                inserted += insert_row(conn, schema=schema, table="extraction_runs", values={
                    "extraction_run_id": extraction_id,
                    "document_version_id": version_id,
                    "pipeline_version": PIPELINE,
                    "model_name": "manual-research-ledger",
                    "started_at": "2026-08-20",
                    "completed_at": "2026-08-20",
                    "status_code": "COMPLETED",
                })
                mention_id = stable_id("em", record["key"], version_id)
                inserted += insert_row(conn, schema=schema, table="event_mentions", values={
                    "event_mention_id": mention_id,
                    "extraction_run_id": extraction_id,
                    "extraction_key": record["key"],
                    "event_category_id": record["category"],
                    "stage_code_hint": record["stage"],
                    "title_raw": record["title"],
                    "summary_raw": record["summary"],
                    "confidence": record["confidence"],
                    "status_code": "REVIEW_READY",
                })
    return {"records": len(records), "unique_urls": len(unique_urls), "per_category": per_category, "inserted_rows": inserted, "dry_run": not apply}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sale", type=Path, required=True)
    parser.add_argument("--non-sale", type=Path, required=True)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = parse_sales(args.sale) + parse_non_sale(args.non_sale)
    env = load_env(args.env)
    dsn = os.environ.get("SUPABASE_DB_URL") or env.get("SUPABASE_DB_URL")
    schema = os.environ.get("SUPABASE_DB_SCHEMA") or env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is missing")
    import psycopg
    with psycopg.connect(dsn, connect_timeout=20) as conn:
        result = import_records(conn, schema=schema, records=records, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
