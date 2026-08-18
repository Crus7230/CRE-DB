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

from collector.dart_business_transfer_extraction import extract_business_transfer_cre_candidate

PIPELINE = "DART_BUSINESS_TRANSFER_CRE_REVIEW_V1"


def sid(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:32]


def main() -> None:
    p = argparse.ArgumentParser(description="Extract review-only CRE leads from OpenDART business transfers")
    p.add_argument("--db", type=Path, default=ROOT / "data" / "market.db")
    p.add_argument("--start-year", type=int, default=2020)
    p.add_argument("--end-year", type=int, default=2024)
    p.add_argument("--output", type=Path, default=ROOT / "artifacts" / "opendart-2020-2024-business-transfer-cre-candidates.json")
    a = p.parse_args()
    con = sqlite3.connect(a.db, timeout=5)
    con.execute("PRAGMA foreign_keys=ON"); con.execute("PRAGMA busy_timeout=5000")
    docs = con.execute("""SELECT v.document_version_id,d.document_id,d.canonical_url,v.title,v.published_at,v.stored_text
      FROM source_documents d JOIN collection_sources s ON s.source_id=d.source_id
      JOIN document_versions v ON v.document_id=d.document_id
      WHERE s.source_code='OPENDART' AND v.published_at>=? AND v.published_at<?
        AND (v.title LIKE '%영업양도%' OR v.title LIKE '%영업양수%') AND v.stored_text IS NOT NULL
        AND v.version_no=(SELECT max(v2.version_no) FROM document_versions v2 WHERE v2.document_id=d.document_id)
      ORDER BY v.published_at,v.document_version_id""",(f'{a.start_year}-01-01',f'{a.end_year+1}-01-01')).fetchall()
    sale_category=con.execute("SELECT event_category_id FROM event_categories WHERE code='SALE'").fetchone()[0]
    now=datetime.now(timezone.utc).isoformat(); out=[]; inserted_runs=inserted_mentions=inserted_tasks=0
    con.execute("BEGIN IMMEDIATE")
    try:
        for version_id,document_id,url,title,published,text in docs:
            candidate=extract_business_transfer_cre_candidate(text)
            if not candidate: continue
            run_id=sid('run',version_id+PIPELINE); em_id=sid('event',run_id); task_id=sid('task',em_id)
            cur=con.execute("""INSERT OR IGNORE INTO extraction_runs(extraction_run_id,document_version_id,pipeline_version,model_name,status_code,started_at,completed_at)
                VALUES (?,?,?,'DART_BUSINESS_TRANSFER_RULE','COMPLETED',?,?)""",(run_id,version_id,PIPELINE,now,now)); inserted_runs+=int(bool(cur.rowcount))
            cur=con.execute("""INSERT OR IGNORE INTO event_mentions(event_mention_id,extraction_run_id,extraction_key,event_category_id,title_raw,confidence,status_code)
                VALUES (?,?, 'dart-business-transfer-cre:v1',?,?,0.45,'REVIEW_READY')""",(em_id,run_id,sale_category,title)); inserted_mentions+=int(bool(cur.rowcount))
            payload={'documentId':document_id,'documentVersionId':version_id,'canonicalUrl':url,'publishedAt':published,'candidate':candidate,'promotionPolicy':'REVIEW_ONLY_NO_AUTO_CANONICAL'}
            cur=con.execute("""INSERT OR IGNORE INTO review_tasks(review_task_id,target_kind,target_id,review_type,status_code,priority,reason_code,payload_json,created_at)
                VALUES (?,'EVENT_MENTION',?,'DART_BUSINESS_TRANSFER_CRE_REVIEW','PENDING',2,'CRE_KEYWORD_IN_BUSINESS_TRANSFER',?,?)""",(task_id,em_id,json.dumps(payload,ensure_ascii=False,sort_keys=True),now)); inserted_tasks+=int(bool(cur.rowcount))
            out.append({'eventMentionId':em_id,'title':title,'publishedAt':published,'url':url,**candidate})
        con.commit()
    except Exception:
        con.rollback(); raise
    finally: con.close()
    result={'pipelineVersion':PIPELINE,'scannedFullText':len(docs),'candidateCount':len(out),'insertedRuns':inserted_runs,'insertedEventMentions':inserted_mentions,'insertedReviewTasks':inserted_tasks,'canonicalAutoCreated':0,'candidates':out}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('pipelineVersion','scannedFullText','candidateCount','insertedRuns','insertedEventMentions','insertedReviewTasks','canonicalAutoCreated')},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
