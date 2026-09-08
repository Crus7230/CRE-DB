#!/usr/bin/env python
"""Promote cutoff-day, scope-confirmed RSS documents into a typed review queue.

This script deliberately creates REVIEW_READY event mentions only. It does not
create canonical events, assets, organizations, mandates, or sale processes.
Those require stronger source-level verification and entity resolution.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
PIPELINE_VERSION = "cutoff-rss-review-queue-v1"
CLASSIFIER_VERSION = "NEWS_CRE_SCOPE_RULE_V1"
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        text = raw.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def quote_ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValueError("invalid PostgreSQL identifier")
    return f'"{value}"'


def select_candidates(conn: Any, *, schema: str, cutoff_day: date) -> list[dict[str, Any]]:
    ns = quote_ident(schema)
    cur = conn.execute(
        f"""
        WITH latest_assessment AS (
          SELECT DISTINCT ON (document_version_id)
                 document_version_id,status_code,classifier_version
          FROM {ns}.document_scope_assessments
          WHERE scope_code='CRE' AND classifier_version=%s
          ORDER BY document_version_id,assessed_at DESC
        ), eligible AS (
          SELECT DISTINCT dv.document_version_id,dv.title,dv.snippet_text,
                 ec.event_category_id,ec.code AS category_code
          FROM {ns}.collection_runs cr
          JOIN {ns}.collection_jobs cj ON cj.job_id=cr.job_id
          JOIN {ns}.collection_job_categories cjc ON cjc.job_id=cj.job_id AND cjc.is_primary=1
          JOIN {ns}.event_categories ec ON ec.event_category_id=cjc.event_category_id
          JOIN {ns}.run_documents rd ON rd.run_id=cr.run_id
          JOIN {ns}.document_versions dv ON dv.document_version_id=rd.document_version_id
          JOIN latest_assessment da ON da.document_version_id=dv.document_version_id
          WHERE cr.status_code='COMPLETED'
            AND da.status_code='CRE_CONFIRMED'
            AND (dv.published_at::timestamptz AT TIME ZONE 'Asia/Seoul')::date=%s
        )
        SELECT * FROM eligible ORDER BY category_code,title,document_version_id
        """,
        (CLASSIFIER_VERSION, cutoff_day),
    )
    columns = [item.name for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def promote(conn: Any, *, schema: str, cutoff_day: date, apply: bool) -> dict[str, Any]:
    ns = quote_ident(schema)
    candidates = select_candidates(conn, schema=schema, cutoff_day=cutoff_day)
    before = Counter(row["category_code"] for row in candidates)
    inserted_runs = inserted_mentions = 0
    now = datetime.now(timezone.utc).isoformat()
    if apply:
        with conn.transaction():
            for row in candidates:
                extraction_id = stable_id("cutoff_ext", row["document_version_id"], PIPELINE_VERSION)
                cur = conn.execute(
                    f"""INSERT INTO {ns}.extraction_runs(
                          extraction_run_id,document_version_id,pipeline_version,model_name,
                          model_version,prompt_or_rule_hash,started_at,completed_at,status_code
                        ) VALUES(%s,%s,%s,'deterministic-rule','1',%s,%s,%s,'COMPLETED')
                        ON CONFLICT(document_version_id,pipeline_version) DO NOTHING""",
                    (extraction_id,row["document_version_id"],PIPELINE_VERSION,
                     hashlib.sha256(CLASSIFIER_VERSION.encode()).hexdigest(),now,now),
                )
                inserted_runs += cur.rowcount
                mention_id = stable_id(
                    "cutoff_em", row["document_version_id"], row["category_code"], PIPELINE_VERSION
                )
                cur = conn.execute(
                    f"""INSERT INTO {ns}.event_mentions(
                          event_mention_id,extraction_run_id,extraction_key,event_category_id,
                          title_raw,summary_raw,event_date_start,event_date_end,date_precision,
                          confidence,status_code
                        ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'DAY',0.75,'REVIEW_READY')
                        ON CONFLICT(extraction_run_id,extraction_key) DO NOTHING""",
                    (mention_id,extraction_id,f"{cutoff_day}:{row['category_code']}",
                     row["event_category_id"],row["title"],row["snippet_text"],
                     cutoff_day.isoformat(),cutoff_day.isoformat()),
                )
                inserted_mentions += cur.rowcount
    return {
        "status": "applied" if apply else "dry_run",
        "cutoff_day": cutoff_day.isoformat(),
        "pipeline_version": PIPELINE_VERSION,
        "eligible_mentions": len(candidates),
        "eligible_by_category": dict(sorted(before.items())),
        "inserted_extraction_runs": inserted_runs,
        "inserted_event_mentions": inserted_mentions,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    values = load_env(args.env)
    dsn = os.environ.get("SUPABASE_DB_URL") or values.get("SUPABASE_DB_URL")
    schema = os.environ.get("SUPABASE_DB_SCHEMA") or values.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is missing")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    with psycopg.connect(dsn, connect_timeout=20) as conn:
        result = promote(conn, schema=schema, cutoff_day=args.date, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
