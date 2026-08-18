from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.bid_extraction import load_geography_policy
from collector.dart_sale_extraction import extract_dart_type_asset_sale

PIPELINE = "DART_TYPE_ASSET_SALE_RULE_V3"


def sid(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:32]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract historical OpenDART type-asset sale candidates")
    parser.add_argument("--db", default="data/market.db")
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    args = parser.parse_args()
    if args.start_year > args.end_year:
        raise SystemExit("start-year must be <= end-year")
    db = (ROOT / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db)
    start_date = f"{args.start_year}-01-01"
    end_date = f"{args.end_year + 1}-01-01"
    policy = load_geography_policy(ROOT / "config" / "asset-use-geography-policies.json")
    con = sqlite3.connect(db, timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    rows = con.execute(
        """SELECT v.document_version_id,d.document_id,d.external_document_key,d.canonical_url,
                  v.title,v.published_at,v.stored_text,v.metadata_json
           FROM source_documents d
           JOIN collection_sources s ON s.source_id=d.source_id
           JOIN document_versions v ON v.document_id=d.document_id
           WHERE s.source_code='OPENDART' AND v.stored_text IS NOT NULL
             AND v.published_at>=? AND v.published_at<?
             AND v.version_no=(SELECT max(v2.version_no) FROM document_versions v2 WHERE v2.document_id=d.document_id)
             AND (v.title LIKE '%유형자산양도%' OR v.title LIKE '%유형자산양수%')
           ORDER BY v.published_at,d.external_document_key""",
        (start_date, end_date),
    ).fetchall()
    category_id = con.execute("SELECT event_category_id FROM event_categories WHERE code='SALE'").fetchone()[0]
    candidates = []
    inserted = {"runs":0,"mentions":0,"eventMentions":0,"reviewTasks":0,"mentionValues":0}
    try:
        con.execute("BEGIN IMMEDIATE")
        prior = [r[0] for r in con.execute(
            """SELECT em.event_mention_id FROM event_mentions em
               JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
               WHERE er.pipeline_version LIKE 'DART_TYPE_ASSET_SALE_RULE_V%'
                 AND er.pipeline_version<>? AND em.status_code='REVIEW_READY'""",
            (PIPELINE,),
        )]
        if prior:
            con.executemany(
                "UPDATE event_mentions SET status_code='REJECTED',rejection_code='SUPERSEDED_PIPELINE' WHERE event_mention_id=?",
                ((mid,) for mid in prior),
            )
            con.executemany(
                """UPDATE review_tasks SET status_code='REJECTED',completed_at=?,decision_note='superseded extraction pipeline'
                   WHERE target_kind='EVENT_MENTION' AND target_id=? AND status_code IN ('PENDING','IN_PROGRESS')""",
                ((now,mid) for mid in prior),
            )
        for version_id, document_id, receipt_no, url, title, published_at, stored_text, metadata_json in rows:
            candidate = extract_dart_type_asset_sale(stored_text, policy)
            if candidate is None:
                continue
            metadata = json.loads(metadata_json or "{}")
            extraction_id = sid("extraction", f"{version_id}:{PIPELINE}")
            cur = con.execute(
                """INSERT OR IGNORE INTO extraction_runs(
                       extraction_run_id,document_version_id,pipeline_version,offset_basis,
                       model_name,prompt_or_rule_hash,started_at,completed_at,status_code)
                   VALUES (?, ?, ?, 'UNICODE_CODEPOINT','DART_SALE_RULE',?,?,?,'COMPLETED')""",
                (extraction_id, version_id, PIPELINE,
                 hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), now, now),
            )
            inserted["runs"] += int(bool(cur.rowcount))
            field_specs = [
                ("assetName","ASSET"),("amount","MONEY"),("counterparty","ORGANIZATION"),
                ("contractDate","DATE"),("baseDate","DATE"),("registrationDate","DATE"),
                ("paymentTerms","OTHER_METRIC"),
            ]
            normalized_values = {
                "assetName": candidate.get("assetName"),
                "amount": candidate.get("amountRaw"),
                "counterparty": candidate.get("counterparty"),
                "contractDate": candidate.get("contractDateRaw"),
                "baseDate": candidate.get("baseDateRaw"),
                "registrationDate": candidate.get("registrationDateRaw"),
                "paymentTerms": candidate.get("paymentTerms"),
            }
            mention_ids = {}
            for field, mention_type in field_specs:
                span = candidate["evidenceSpans"].get(field)
                if not span or span["end"] <= span["start"]:
                    continue
                mention_id = sid("mention", f"{extraction_id}:{field}:{span['start']}:{span['end']}")
                mention_ids[field] = mention_id
                surface = stored_text[span["start"]:span["end"]]
                cur = con.execute(
                    """INSERT OR IGNORE INTO mentions(
                           mention_id,extraction_run_id,mention_type,char_start,char_end,surface_text,
                           surface_sha256,normalized_text,parser_payload_json,confidence,review_status)
                       VALUES (?,?,?,?,?,?,?,?,?,0.85,'UNREVIEWED')""",
                    (mention_id, extraction_id, mention_type, span["start"], span["end"], surface,
                     hashlib.sha256(surface.encode()).hexdigest(),
                     normalized_values.get(field),
                     json.dumps({"field":field,"candidateVersion":"1.0.0"},ensure_ascii=False)),
                )
                inserted["mentions"] += int(bool(cur.rowcount))
            if "amount" in mention_ids and candidate.get("amountKrwDecimal"):
                cur = con.execute(
                    """INSERT OR IGNORE INTO mention_values(
                           mention_id,value_kind,raw_value,value_decimal_text,comparator_code,
                           currency_code,unit_code,normalized_unit_code,normalization_version)
                       VALUES (?,'MONEY',?,?,'EXACT','KRW','KRW','KRW','DART_KRW_V1')""",
                    (mention_ids["amount"],candidate.get("amountRaw"),candidate["amountKrwDecimal"]),
                )
                inserted["mentionValues"] += int(bool(cur.rowcount))
            event_mention_id = sid("event-mention", f"{extraction_id}:official-sale")
            stages = candidate["statusSignals"]
            stage_hint = stages[0] if len(stages) == 1 else None
            summary = " | ".join(str(x) for x in (
                metadata.get("filer_name"), candidate.get("assetName"),
                candidate.get("counterparty"), candidate.get("amountRaw"),
            ) if x)
            cur = con.execute(
                """INSERT OR IGNORE INTO event_mentions(
                       event_mention_id,extraction_run_id,extraction_key,event_category_id,
                       stage_code_hint,title_raw,summary_raw,confidence,status_code)
                   VALUES (?,?, 'dart-type-asset-sale:v3',?,?,?,?,0.85,'REVIEW_READY')""",
                (event_mention_id,extraction_id,category_id,stage_hint,title,summary),
            )
            inserted["eventMentions"] += int(bool(cur.rowcount))
            payload = {
                "sourceType":"OFFICIAL_FILING","documentId":document_id,
                "documentVersionId":version_id,"receiptNo":receipt_no,"canonicalUrl":url,
                "publishedAt":published_at,"filerName":metadata.get("filer_name"),
                "candidate":candidate,
                "promotionPolicy":"REVIEW_THEN_CLAIM_THEN_CANONICAL_SALE_PROCESS",
            }
            task_id = sid("review-task", f"OFFICIAL_SALE_DISCLOSURE_REVIEW:{event_mention_id}")
            priority = 1 if stages or candidate.get("amountKrwDecimal") else 2
            cur = con.execute(
                """INSERT OR IGNORE INTO review_tasks(
                       review_task_id,target_kind,target_id,review_type,status_code,priority,
                       reason_code,payload_json,created_at)
                   VALUES (?,'EVENT_MENTION',?,'OFFICIAL_SALE_DISCLOSURE_REVIEW','PENDING',?,
                           'DART_TYPE_ASSET_SALE_CANDIDATE',?,?)""",
                (task_id,event_mention_id,priority,json.dumps(payload,ensure_ascii=False,sort_keys=True),now),
            )
            inserted["reviewTasks"] += int(bool(cur.rowcount))
            candidates.append(payload)
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        con.close()
    output = {"startYear":args.start_year,"endYear":args.end_year,"pipeline":PIPELINE,"scannedFullTextFilings":len(rows),"candidateCount":len(candidates),"inserted":inserted,"candidates":candidates}
    path = ROOT / "artifacts" / f"opendart-{args.start_year}-{args.end_year}-type-asset-sale-candidates-v3.json"
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:output[k] for k in ("scannedFullTextFilings","candidateCount","inserted")},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
