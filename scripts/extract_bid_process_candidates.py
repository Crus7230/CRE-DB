from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.sale_process_candidates import extract_and_queue_bid_process_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue review-only bid-process candidates for one or more collection runner versions")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "market.db")
    parser.add_argument("--runner-version", action="append", dest="runner_versions")
    parser.add_argument("--pipeline-version", default="BID_PROCESS_TITLE_SNIPPET_V4")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "bid-process-2020-2025-candidates.json")
    args = parser.parse_args()
    runner_versions = args.runner_versions or ["2020-2024-bid-process-v1", "2025-bid-process-v1"]

    summaries: list[dict[str, object]] = []
    for runner_version in runner_versions:
        result = extract_and_queue_bid_process_candidates(
            db_path=args.db,
            geography_policy_path=ROOT / "config" / "asset-use-geography-policies.json",
            collection_runner_version=runner_version,
            pipeline_version=args.pipeline_version,
        )
        summaries.append({
            "runnerVersion": runner_version,
            "scannedDocuments": result.scanned_documents,
            "matchedDocuments": result.matched_documents,
            "insertedExtractionRuns": result.inserted_extraction_runs,
            "insertedEventMentions": result.inserted_event_mentions,
            "insertedReviewTasks": result.inserted_review_tasks,
        })

    con = sqlite3.connect(args.db)
    rows = con.execute(
        """SELECT em.event_mention_id,em.title_raw,em.stage_code_hint,em.confidence,
                  dv.published_at,sd.canonical_url,sd.publisher_name,
                  er.pipeline_version,em.status_code
             FROM event_mentions em
             JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
             JOIN document_versions dv ON dv.document_version_id=er.document_version_id
             JOIN source_documents sd ON sd.document_id=dv.document_id
            WHERE er.pipeline_version=? AND em.status_code IN ('REVIEW_READY','APPROVED')
            ORDER BY dv.published_at,em.event_mention_id""",
        (args.pipeline_version,),
    ).fetchall()
    con.close()
    payload = {
        "pipelineVersion": args.pipeline_version,
        "runnerVersions": runner_versions,
        "summaries": summaries,
        "candidateCount": len(rows),
        "canonicalAutoCreated": 0,
        "candidates": [
            dict(zip(("eventMentionId","title","stageHint","confidence","publishedAt","url","publisher","pipelineVersion","status"), row))
            for row in rows
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("pipelineVersion","runnerVersions","summaries","candidateCount","canonicalAutoCreated")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
