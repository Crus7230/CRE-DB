#!/usr/bin/env python
"""Collect category-first Korean CRE articles into Supabase PostgreSQL main.

The collector stores RSS metadata/excerpts only, writes append-only document versions,
and is idempotent by source URL, content hash, and category/date run identity.
Credentials are read from environment variables or the external authority env file and
are never printed.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import (
    DiscoveredDocument,
    _content_hash,
    _stable_id,
    _utc_now,
    parse_google_news_rss,
    render_google_query,
)

DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
DEFAULT_CONFIG = ROOT / "campaigns" / "rolling-2026-current.json"
RUNNER_VERSION = "daily-google-news-rss-postgres-v2"
JOB_VERSION = 2
SEOUL = ZoneInfo("Asia/Seoul")
DOTENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = DOTENV_RE.match(text)
        if match:
            values[match.group(1)] = match.group(2).strip().strip("\"'")
    return values


def utc_window_for_seoul_day(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, SEOUL).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def collection_slot_key(moment: datetime) -> str:
    """Return the deterministic Seoul schedule slot for an execution.

    Retries within one slot keep the same identity, while the morning,
    afternoon, and evening runs can ingest newly published documents.
    """
    local = moment.astimezone(SEOUL)
    slots = [
        datetime.combine(local.date(), time(hour, 0), SEOUL)
        for hour in (6, 9, 12, 15, 18, 21)
    ]
    eligible = [slot for slot in slots if slot <= local]
    if eligible:
        return eligible[-1].isoformat(timespec="minutes")
    previous_evening = datetime.combine(
        local.date() - timedelta(days=1),
        time(21, 0),
        SEOUL,
    )
    return previous_evening.isoformat(timespec="minutes")


def parse_collection_slot(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("collection slot must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("collection slot must include a UTC offset")
    local = parsed.astimezone(SEOUL)
    if local.minute != 0 or local.second != 0 or local.microsecond != 0 or local.hour not in (6, 9, 12, 15, 18, 21):
        raise argparse.ArgumentTypeError("collection slot must be a KST scheduler fire at 06:00, 09:00, 12:00, 15:00, 18:00, or 21:00")
    return local.isoformat(timespec="minutes")


def lock_collection_run(conn, run_id: str) -> None:
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (run_id,),
    )


def configure_connection(conn: Any) -> None:
    conn.execute("SET statement_timeout TO 60000")
    conn.commit()


def partition_cursor_json(day: date, collection_slot: str) -> str:
    start_utc, end_utc = utc_window_for_seoul_day(day)
    return json.dumps(
        {
            "collection_slot": collection_slot,
            "window_end": end_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "window_start": start_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        sort_keys=True,
    )


def fetch_partition(base_query: str, day: date) -> tuple[str, list[DiscoveredDocument]]:
    start_utc, end_utc = utc_window_for_seoul_day(day)
    query = render_google_query(base_query, day.isoformat(), (day + timedelta(days=1)).isoformat())
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    )
    request = urllib.request.Request(url, headers={"User-Agent": "CRE-DB-Daily-Collector/1.0"})
    raw = urllib.request.urlopen(request, timeout=45).read()
    return query, parse_google_news_rss(raw, start=start_utc, end=end_utc)


def q(identifier: str) -> str:
    if not IDENT_RE.fullmatch(identifier):
        raise ValueError("invalid PostgreSQL identifier")
    return f'"{identifier}"'


def ingest_partition_postgres(
    conn,
    *,
    schema: str,
    source_code: str,
    category_code: str,
    day: date,
    collection_slot: str,
    query_rendered: str,
    documents: list[DiscoveredDocument],
) -> dict:
    namespace = q(schema)
    start_utc, end_utc = utc_window_for_seoul_day(day)
    window_start = start_utc.isoformat(timespec="seconds").replace("+00:00", "Z")
    window_end = end_utc.isoformat(timespec="seconds").replace("+00:00", "Z")
    cursor_json = partition_cursor_json(day, collection_slot)
    job_code = f"DAILY_GOOGLE_NEWS_RSS_{category_code}"
    now = _utc_now()

    with conn.transaction():
        source = conn.execute(
            f"SELECT source_id FROM {namespace}.collection_sources WHERE source_code=%s AND is_active=1",
            (source_code,),
        ).fetchone()
        category = conn.execute(
            f"SELECT event_category_id FROM {namespace}.event_categories WHERE code=%s AND is_active=1",
            (category_code,),
        ).fetchone()
        if source is None or category is None:
            raise RuntimeError(f"missing active source/category: {source_code}/{category_code}")

        job = conn.execute(
            f"SELECT job_id FROM {namespace}.collection_jobs WHERE job_code=%s AND job_version=%s",
            (job_code, JOB_VERSION),
        ).fetchone()
        if job is None:
            candidate_job_id = _stable_id("job", f"{job_code}:{JOB_VERSION}")
            conn.execute(
                f"""INSERT INTO {namespace}.collection_jobs(
                    job_id,job_code,job_version,job_kind,source_id,query_template,
                    cadence_code,config_json,valid_from,is_active
                ) VALUES(%s,%s,%s,'CATEGORY_SEARCH',%s,%s,'DAILY',%s,%s,1)
                ON CONFLICT DO NOTHING""",
                (candidate_job_id, job_code, JOB_VERSION, source[0], query_rendered,
                 json.dumps({"pipeline": RUNNER_VERSION, "timezone": "Asia/Seoul"}, sort_keys=True),
                 window_start),
            )
            job = conn.execute(
                f"SELECT job_id FROM {namespace}.collection_jobs WHERE job_code=%s AND job_version=%s",
                (job_code, JOB_VERSION),
            ).fetchone()
            if job is None:
                raise RuntimeError(f"failed to create collection job: {job_code} v{JOB_VERSION}")
        job_id = job[0]
        conn.execute(
            f"""INSERT INTO {namespace}.collection_job_categories(job_id,event_category_id,is_primary)
                VALUES(%s,%s,1)
                ON CONFLICT(job_id,event_category_id) DO UPDATE SET is_primary=EXCLUDED.is_primary""",
            (job_id, category[0]),
        )

        run_id = _stable_id(
            "run",
            f"{job_id}:{window_start}:{window_end}:{collection_slot}:{query_rendered}",
        )
        lock_collection_run(conn, run_id)

        existing = conn.execute(
            f"""SELECT run_id,discovered_count,inserted_count,updated_count
                FROM {namespace}.collection_runs
                WHERE job_id=%s AND scheduled_for=%s AND query_rendered=%s
                  AND cursor_in=%s AND status_code='COMPLETED'
                ORDER BY completed_at DESC LIMIT 1""",
            (job_id, window_start, query_rendered, cursor_json),
        ).fetchone()
        if existing:
            return {
                "category": category_code,
                "date": day.isoformat(),
                "run_id": existing[0],
                "discovered": existing[1] or 0,
                "inserted": existing[2] or 0,
                "updated": existing[3] or 0,
                "skipped": True,
            }

        conn.execute(
            f"""INSERT INTO {namespace}.collection_runs(
                run_id,job_id,scheduled_for,started_at,status_code,query_rendered,cursor_in,runner_version
            ) VALUES(%s,%s,%s,%s,'RUNNING',%s,%s,%s)
            ON CONFLICT(run_id) DO UPDATE SET started_at=EXCLUDED.started_at,status_code='RUNNING',
                completed_at=NULL,error_code=NULL,error_message=NULL,runner_version=EXCLUDED.runner_version""",
            (run_id, job_id, window_start, now, query_rendered, cursor_json, RUNNER_VERSION),
        )

        inserted = 0
        updated = 0
        for rank, document in enumerate(documents, 1):
            if not document.canonical_url:
                continue
            row = conn.execute(
                f"SELECT document_id FROM {namespace}.source_documents WHERE source_id=%s AND canonical_url=%s",
                (source[0], document.canonical_url),
            ).fetchone()
            existed = row is not None
            if existed:
                document_id = row[0]
                conn.execute(
                    f"UPDATE {namespace}.source_documents SET last_seen_at=%s WHERE document_id=%s",
                    (now, document_id),
                )
            else:
                document_id = _stable_id("document", f"{source_code}:{document.canonical_url}")
                conn.execute(
                    f"""INSERT INTO {namespace}.source_documents(
                        document_id,source_id,canonical_url,publisher_name,document_type,
                        external_document_key,first_seen_at,last_seen_at,access_status
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'ACCESSIBLE')
                    ON CONFLICT(source_id,canonical_url) DO NOTHING""",
                    (document_id, source[0], document.canonical_url, document.publisher_name,
                     document.document_type, document.external_key, now, now),
                )
                inserted += 1

            content_hash = _content_hash(document)
            version = conn.execute(
                f"SELECT document_version_id FROM {namespace}.document_versions WHERE document_id=%s AND content_sha256=%s",
                (document_id, content_hash),
            ).fetchone()
            if version is None:
                version_no = conn.execute(
                    f"SELECT coalesce(max(version_no),0)+1 FROM {namespace}.document_versions WHERE document_id=%s",
                    (document_id,),
                ).fetchone()[0]
                version_id = _stable_id("document-version", f"{document_id}:{content_hash}")
                conn.execute(
                    f"""INSERT INTO {namespace}.document_versions(
                        document_version_id,document_id,version_no,title,published_at,collected_at,
                        content_sha256,snippet_text,stored_text,rights_status,metadata_json
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (version_id, document_id, version_no, document.title, document.published_at,
                     now, content_hash, document.snippet_text, document.stored_text,
                     document.rights_status,
                     json.dumps(document.metadata or {}, ensure_ascii=False, sort_keys=True)),
                )
                if existed:
                    updated += 1
            else:
                version_id = version[0]

            conn.execute(
                f"""INSERT INTO {namespace}.run_documents(
                    run_id,document_version_id,result_rank,search_snippet,discovered_at
                ) VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(run_id,document_version_id) DO NOTHING""",
                (run_id, version_id, rank, document.snippet_text, now),
            )

        conn.execute(
            f"""UPDATE {namespace}.collection_runs SET completed_at=%s,status_code='COMPLETED',
                discovered_count=%s,inserted_count=%s,updated_count=%s,rejected_count=0,cursor_out=%s
                WHERE run_id=%s""",
            (now, len(documents), inserted, updated, cursor_json, run_id),
        )
    return {
        "category": category_code,
        "date": day.isoformat(),
        "run_id": run_id,
        "discovered": len(documents),
        "inserted": inserted,
        "updated": updated,
        "skipped": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect daily Korean CRE Google News RSS into Supabase main")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--lookback-days", type=int, default=2)
    parser.add_argument("--category")
    parser.add_argument("--collection-slot", type=parse_collection_slot)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.lookback_days < 1 or args.lookback_days > 7:
        raise SystemExit("--lookback-days must be between 1 and 7")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc

    file_env = load_env_file(args.env)
    dsn = os.environ.get("SUPABASE_DB_URL") or file_env.get("SUPABASE_DB_URL")
    schema = os.environ.get("SUPABASE_DB_SCHEMA") or file_env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is missing")
    q(schema)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    categories = config["categories"]
    if args.category:
        if args.category not in categories:
            raise SystemExit(f"unknown category: {args.category}")
        categories = {args.category: categories[args.category]}
    target = args.date or datetime.now(SEOUL).date()
    collection_slot = args.collection_slot or collection_slot_key(datetime.now(SEOUL))
    days = [target - timedelta(days=offset) for offset in reversed(range(args.lookback_days))]

    summaries: list[dict] = []
    with psycopg.connect(dsn, connect_timeout=20) as conn:
        configure_connection(conn)
        for day in days:
            for category_code, base_query in categories.items():
                query, documents = fetch_partition(base_query, day)
                result = ingest_partition_postgres(
                    conn,
                    schema=schema,
                    source_code="GOOGLE_NEWS_RSS",
                    category_code=category_code,
                    day=day,
                    collection_slot=collection_slot,
                    query_rendered=query,
                    documents=documents,
                )
                summaries.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)

    output = {
        "status": "completed",
        "runner": RUNNER_VERSION,
        "target_date": target.isoformat(),
        "lookback_days": args.lookback_days,
        "partitions": len(summaries),
        "skipped_partitions": sum(1 for row in summaries if row["skipped"]),
        "discovered": sum(row["discovered"] for row in summaries if not row["skipped"]),
        "inserted": sum(row["inserted"] for row in summaries if not row["skipped"]),
        "updated": sum(row["updated"] for row in summaries if not row["skipped"]),
    }
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
