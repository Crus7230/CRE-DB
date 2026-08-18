"""Persist title/snippet bid-process candidates as review-ready event mentions.

No canonical sale process, organization, bid or funding record is created automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from collector.post_collection_relationships import reconcile_relationships

from collector.bid_extraction import extract_bid_process_candidate, load_geography_policy


@dataclass(frozen=True)
class CandidateIngestResult:
    scanned_documents: int
    matched_documents: int
    inserted_extraction_runs: int
    inserted_event_mentions: int
    inserted_review_tasks: int


def _stable_id(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:32]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def extract_and_queue_bid_process_candidates(
    *,
    db_path: str | Path,
    geography_policy_path: str | Path,
    collection_runner_version: str = "2025-bid-process-v1",
    pipeline_version: str = "BID_PROCESS_TITLE_SNIPPET_V3",
) -> CandidateIngestResult:
    policy = load_geography_policy(geography_policy_path)
    rule_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    con = sqlite3.connect(str(db_path), timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    now = _utc_now()
    inserted_runs = inserted_mentions = inserted_tasks = matched = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        sale_category = con.execute(
            "SELECT event_category_id FROM event_categories WHERE code='SALE'"
        ).fetchone()
        if sale_category is None:
            raise RuntimeError("SALE event category is not seeded")
        sale_category_id = sale_category[0]

        # Preserve lineage but retire pending candidates produced by an older
        # version of this rule pipeline.
        prior_mentions = [row[0] for row in con.execute(
            """SELECT em.event_mention_id
               FROM event_mentions em
               JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
               WHERE er.pipeline_version LIKE 'BID_PROCESS_TITLE_SNIPPET_V%'
                 AND er.pipeline_version<>?
                 AND em.status_code IN ('EXTRACTED','RESOLUTION_REQUIRED','REVIEW_READY')""",
            (pipeline_version,),
        )]
        if prior_mentions:
            con.executemany(
                "UPDATE event_mentions SET status_code='REJECTED',rejection_code='SUPERSEDED_PIPELINE' WHERE event_mention_id=?",
                ((mid,) for mid in prior_mentions),
            )
            con.executemany(
                """UPDATE review_tasks SET status_code='REJECTED',completed_at=?,decision_note='superseded extraction pipeline'
                   WHERE target_kind='EVENT_MENTION' AND target_id=? AND status_code IN ('PENDING','IN_PROGRESS')""",
                ((now, mid) for mid in prior_mentions),
            )

        # Reject candidates from superseded immutable document versions.
        old_mentions = [row[0] for row in con.execute(
            """SELECT em.event_mention_id
               FROM event_mentions em
               JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
               JOIN document_versions v ON v.document_version_id=er.document_version_id
               WHERE er.pipeline_version=?
                 AND v.version_no < (SELECT max(v2.version_no) FROM document_versions v2 WHERE v2.document_id=v.document_id)
                 AND em.status_code IN ('EXTRACTED','RESOLUTION_REQUIRED','REVIEW_READY')""",
            (pipeline_version,),
        )]
        if old_mentions:
            con.executemany(
                "UPDATE event_mentions SET status_code='REJECTED',rejection_code='SUPERSEDED_DOCUMENT_VERSION' WHERE event_mention_id=?",
                ((mid,) for mid in old_mentions),
            )
            con.executemany(
                """UPDATE review_tasks SET status_code='REJECTED',completed_at=?,decision_note='superseded document version'
                   WHERE target_kind='EVENT_MENTION' AND target_id=? AND status_code IN ('PENDING','IN_PROGRESS')""",
                ((now, mid) for mid in old_mentions),
            )

        rows = con.execute(
            """SELECT DISTINCT v.document_version_id,d.document_id,d.canonical_url,
                       v.title,v.snippet_text,v.published_at,s.source_code
               FROM collection_runs cr
               JOIN run_documents rd ON rd.run_id=cr.run_id
               JOIN document_versions v ON v.document_version_id=rd.document_version_id
               JOIN source_documents d ON d.document_id=v.document_id
               JOIN collection_sources s ON s.source_id=d.source_id
               WHERE cr.runner_version=? AND cr.status_code='COMPLETED'
                 AND v.version_no=(SELECT max(v2.version_no) FROM document_versions v2 WHERE v2.document_id=v.document_id)
               ORDER BY v.published_at,v.document_version_id""",
            (collection_runner_version,),
        ).fetchall()
        for document_version_id, document_id, url, title, snippet, published_at, source_code in rows:
            candidate = extract_bid_process_candidate(title, snippet, policy)
            if candidate is None:
                continue
            matched += 1
            extraction_id = _stable_id("extraction", f"{document_version_id}:{pipeline_version}")
            cur = con.execute(
                """INSERT OR IGNORE INTO extraction_runs(
                       extraction_run_id,document_version_id,pipeline_version,offset_basis,
                       model_name,prompt_or_rule_hash,started_at,completed_at,status_code)
                   VALUES (?, ?, ?, 'UNICODE_CODEPOINT', 'BID_PROCESS_RULE', ?, ?, ?, 'COMPLETED')""",
                (extraction_id, document_version_id, pipeline_version, rule_hash, now, now),
            )
            inserted_runs += int(bool(cur.rowcount))
            stage_hint = candidate.stage_signals[0] if len(candidate.stage_signals) == 1 else None
            extraction_key = "bid-process:title-snippet:v1"
            event_mention_id = _stable_id("event-mention", f"{extraction_id}:{extraction_key}")
            signal_count = sum(len(v) for v in (
                candidate.stage_signals, candidate.participation_signals,
                candidate.advisor_signals, candidate.funding_signals,
            ))
            confidence = min(0.80, 0.40 + 0.05 * signal_count)
            cur = con.execute(
                """INSERT OR IGNORE INTO event_mentions(
                       event_mention_id,extraction_run_id,extraction_key,event_category_id,
                       stage_code_hint,title_raw,summary_raw,confidence,status_code)
                   VALUES (?,?,?,?,?,?,?,?,'REVIEW_READY')""",
                (event_mention_id, extraction_id, extraction_key, sale_category_id,
                 stage_hint, title, snippet, confidence),
            )
            inserted_mentions += int(bool(cur.rowcount))
            payload = {
                "candidateVersion": "1.0.0",
                "offsetBasis": "TITLE_NEWLINE_SNIPPET_UNICODE_CODEPOINT",
                "documentId": document_id,
                "documentVersionId": document_version_id,
                "canonicalUrl": url,
                "publishedAt": published_at,
                "sourceCode": source_code,
                "geographyPolicyVersion": policy.get("policyVersion"),
                "candidate": candidate.to_json(),
                "promotionPolicy": "REVIEW_THEN_CLAIM_THEN_CANONICAL_SALE_PROCESS",
            }
            review_task_id = _stable_id("review-task", f"SALE_PROCESS_EVIDENCE_REVIEW:{event_mention_id}")
            priority = 1 if any(s in candidate.stage_signals for s in (
                "PREFERRED_BIDDER_SELECTED", "SPA_SIGNED", "CLOSED", "SALE_FAILED"
            )) or candidate.money_mentions or candidate.reported_ranks else 2
            cur = con.execute(
                """INSERT OR IGNORE INTO review_tasks(
                       review_task_id,target_kind,target_id,review_type,status_code,priority,
                       reason_code,payload_json,created_at)
                   VALUES (?, 'EVENT_MENTION', ?, 'SALE_PROCESS_EVIDENCE_REVIEW','PENDING',?,
                           'TITLE_SNIPPET_CANDIDATE',?,?)""",
                (review_task_id, event_mention_id, priority,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True), now),
            )
            inserted_tasks += int(bool(cur.rowcount))
        con.commit()
        reconcile_relationships(db_path, allow_live=True)
        return CandidateIngestResult(len(rows), matched, inserted_runs, inserted_mentions, inserted_tasks)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
