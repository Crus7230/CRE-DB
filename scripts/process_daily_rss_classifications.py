#!/usr/bin/env python
"""Incrementally assess daily RSS documents and create review-only event mentions.

The command is a rollback rehearsal unless ``--apply`` is supplied.  It never
creates canonical events and it never writes APPROVED review states.  Governed
DOCUMENT/MARKET_CATEGORY projection is delegated to
``backfill_document_market_categories`` so the assignment identity remains
``DOCUMENT_EVENT_MENTION_V1`` in both backlog and daily processing.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.news_cre_scope import (  # noqa: E402
    CLASSIFIER_VERSION as NEWS_SCOPE_CLASSIFIER_VERSION,
    classify_news_cre_scope,
)

DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
PIPELINE_VERSION = "daily-rss-review-queue-v1"
PROJECTION_CLASSIFIER_VERSION = "DOCUMENT_EVENT_MENTION_V1"
HEADLINE_PROJECTION_CLASSIFIER_VERSION = "DOCUMENT_HEADLINE_MARKET_CATEGORY_V1"
SEOUL = ZoneInfo("Asia/Seoul")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ALLOWED_SCHEMA_VERSIONS = {"3.3.0", "3.4.0", "3.4.1", "3.5.0"}


@dataclass
class Candidate:
    document_id: str
    document_version_id: str
    title: str | None
    snippet: str | None
    published_at: str | None
    collected_at: str | None
    categories: dict[str, str] = field(default_factory=dict)
    run_ids: set[str] = field(default_factory=set)
    collection_slots: set[str] = field(default_factory=set)


Projector = Callable[..., dict[str, Any]]
ContextualProjector = Callable[..., dict[str, Any]]
HeadlineProjector = Callable[..., dict[str, Any]]


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def publication_day_kst(value: object) -> date | None:
    parsed = parse_timestamp(value)
    return parsed.astimezone(SEOUL).date() if parsed else None


def parse_collection_slot(value: str) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        raise argparse.ArgumentTypeError("collection slot must be an ISO datetime with offset")
    local = parsed.astimezone(SEOUL)
    if local.minute != 0 or local.second or local.microsecond or local.hour not in (6, 9, 12, 15, 18, 21):
        raise argparse.ArgumentTypeError("collection slot must be a KST scheduler fire at 06:00, 09:00, 12:00, 15:00, 18:00, or 21:00")
    return local.isoformat(timespec="minutes")


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if IDENTIFIER.fullmatch(key.strip()):
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _is_sqlite(conn: Any) -> bool:
    return isinstance(conn, sqlite3.Connection)


def _placeholder(conn: Any) -> str:
    return "?" if _is_sqlite(conn) else "%s"


def _table(schema: str | None, name: str) -> str:
    if not IDENTIFIER.fullmatch(name) or (schema and not IDENTIFIER.fullmatch(schema)):
        raise ValueError("invalid SQL identifier")
    return f'"{schema}"."{name}"' if schema else f'"{name}"'


def _fetch_dicts(conn: Any, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cur = conn.execute(sql, tuple(params))
    names = [column.name if hasattr(column, "name") else column[0] for column in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def _fetch_one(conn: Any, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = _fetch_dicts(conn, sql, params)
    return rows[0] if rows else None


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_equivalent(value: object, expected: object) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return False
    return value == expected


def _cursor_slot(value: object) -> str | None:
    if isinstance(value, dict):
        payload = value
    else:
        try:
            payload = json.loads(str(value or "{}"))
        except (json.JSONDecodeError, TypeError):
            return None
    slot = payload.get("collection_slot") if isinstance(payload, dict) else None
    return str(slot) if slot else None


def _utc_bounds(from_date: date, to_date: date) -> tuple[str, str]:
    start = datetime.combine(from_date, time.min, SEOUL).astimezone(timezone.utc)
    end = datetime.combine(to_date, time.min, SEOUL).astimezone(timezone.utc)
    return (
        start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        end.isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def load_daily_candidates(
    conn: Any,
    *,
    schema: str | None,
    from_date: date | None,
    to_date: date | None,
    collection_slot: str | None,
) -> list[Candidate]:
    """Load completed Google News RSS rows and group their category provenance."""
    ph = _placeholder(conn)
    scheduled_bounds: tuple[str, str] | None = None
    predicates = ["cs.source_code='GOOGLE_NEWS_RSS'", "cr.status_code='COMPLETED'", "cjc.is_primary=1"]
    params: list[Any] = []
    if from_date and to_date:
        scheduled_bounds = _utc_bounds(from_date, to_date)
        predicates.append(
            f"((dv.published_at>={ph} AND dv.published_at<{ph}) OR "
            f"(dv.published_at IS NULL AND cr.scheduled_for>={ph} AND cr.scheduled_for<{ph}))"
        )
        params.extend((*scheduled_bounds, *scheduled_bounds))

    sql = f"""
      SELECT sd.document_id,dv.document_version_id,dv.title,dv.snippet_text,
             dv.published_at,dv.collected_at,ec.event_category_id,ec.code AS category_code,
             cr.run_id,cr.cursor_in,cr.scheduled_for
      FROM {_table(schema,'source_documents')} sd
      JOIN {_table(schema,'collection_sources')} cs ON cs.source_id=sd.source_id
      JOIN {_table(schema,'document_versions')} dv ON dv.document_id=sd.document_id
      JOIN {_table(schema,'run_documents')} rd ON rd.document_version_id=dv.document_version_id
      JOIN {_table(schema,'collection_runs')} cr ON cr.run_id=rd.run_id
      JOIN {_table(schema,'collection_job_categories')} cjc ON cjc.job_id=cr.job_id
      JOIN {_table(schema,'event_categories')} ec ON ec.event_category_id=cjc.event_category_id
      WHERE {' AND '.join(predicates)}
      ORDER BY dv.document_version_id,ec.code,cr.run_id
    """
    rows = _fetch_dicts(conn, sql, params)
    grouped: dict[str, Candidate] = {}
    for row in rows:
        row_slot = _cursor_slot(row.get("cursor_in"))
        if collection_slot and row_slot != collection_slot:
            continue
        published_day = publication_day_kst(row.get("published_at"))
        scheduled_day = publication_day_kst(row.get("scheduled_for"))
        effective_day = published_day or scheduled_day
        if from_date and (effective_day is None or effective_day < from_date):
            continue
        if to_date and (effective_day is None or effective_day >= to_date):
            continue
        version_id = str(row["document_version_id"])
        item = grouped.setdefault(
            version_id,
            Candidate(
                document_id=str(row["document_id"]),
                document_version_id=version_id,
                title=row.get("title"),
                snippet=row.get("snippet_text"),
                published_at=row.get("published_at"),
                collected_at=row.get("collected_at"),
            ),
        )
        item.categories[str(row["category_code"])] = str(row["event_category_id"])
        item.run_ids.add(str(row["run_id"]))
        if row_slot:
            item.collection_slots.add(row_slot)
    return list(grouped.values())


def _require_schema(conn: Any, schema: str | None) -> str:
    ph = _placeholder(conn)
    row = _fetch_one(
        conn,
        f"SELECT schema_value FROM {_table(schema,'schema_meta')} WHERE schema_key={ph}",
        ("schema_version",),
    )
    version = str(row["schema_value"]) if row else "missing"
    if version not in ALLOWED_SCHEMA_VERSIONS:
        raise RuntimeError(f"daily RSS classification requires schema {sorted(ALLOWED_SCHEMA_VERSIONS)}, found {version}")
    return version


def _upsert_scope(conn: Any, schema: str | None, candidate: Candidate, result: Any, assessed_at: str) -> str:
    ph = _placeholder(conn)
    table = _table(schema, "document_scope_assessments")
    existing = _fetch_one(
        conn,
        f"SELECT * FROM {table} WHERE document_version_id={ph} AND scope_code='CRE' AND classifier_version={ph}",
        (candidate.document_version_id, NEWS_SCOPE_CLASSIFIER_VERSION),
    )
    evidence = {
        "categoryCodes": sorted(candidate.categories),
        "collectionRunIds": sorted(candidate.run_ids),
        "collectionSlots": sorted(candidate.collection_slots),
        "publishedAt": candidate.published_at,
        "publicationDayKst": publication_day_kst(candidate.published_at).isoformat()
        if publication_day_kst(candidate.published_at)
        else None,
    }
    reasons = list(result.reason_codes)
    if existing and (
        existing["status_code"] == result.status_code
        and _json_equivalent(existing["reason_codes_json"], reasons)
        and _json_equivalent(existing["evidence_json"], evidence)
    ):
        return "unchanged"
    values = (
        result.status_code,
        _stable_json(reasons),
        _stable_json(evidence),
        assessed_at,
        candidate.document_version_id,
        NEWS_SCOPE_CLASSIFIER_VERSION,
    )
    if existing:
        conn.execute(
            f"UPDATE {table} SET status_code={ph},reason_codes_json={ph},evidence_json={ph},assessed_at={ph} "
            f"WHERE document_version_id={ph} AND scope_code='CRE' AND classifier_version={ph}",
            values,
        )
        return "updated"
    conn.execute(
        f"INSERT INTO {table}(document_scope_assessment_id,document_version_id,scope_code,classifier_version,"
        f"status_code,reason_codes_json,evidence_json,assessed_at) VALUES({','.join([ph] * 8)})",
        (
            stable_id("scope", candidate.document_version_id, "CRE", NEWS_SCOPE_CLASSIFIER_VERSION),
            candidate.document_version_id,
            "CRE",
            NEWS_SCOPE_CLASSIFIER_VERSION,
            result.status_code,
            _stable_json(reasons),
            _stable_json(evidence),
            assessed_at,
        ),
    )
    return "inserted"


def _ensure_extraction(conn: Any, schema: str | None, candidate: Candidate, now: str) -> tuple[str, str]:
    ph = _placeholder(conn)
    table = _table(schema, "extraction_runs")
    existing = _fetch_one(
        conn,
        f"SELECT extraction_run_id,status_code FROM {table} WHERE document_version_id={ph} AND pipeline_version={ph}",
        (candidate.document_version_id, PIPELINE_VERSION),
    )
    if existing:
        if existing["status_code"] != "COMPLETED":
            conn.execute(
                f"UPDATE {table} SET completed_at={ph},status_code='COMPLETED',error_message=NULL "
                f"WHERE extraction_run_id={ph}",
                (now, existing["extraction_run_id"]),
            )
            return str(existing["extraction_run_id"]), "updated"
        return str(existing["extraction_run_id"]), "unchanged"
    extraction_id = stable_id("daily_rss_ext", candidate.document_version_id, PIPELINE_VERSION)
    conn.execute(
        f"INSERT INTO {table}(extraction_run_id,document_version_id,pipeline_version,model_name,model_version,"
        f"prompt_or_rule_hash,started_at,completed_at,status_code) VALUES({','.join([ph] * 9)})",
        (
            extraction_id,
            candidate.document_version_id,
            PIPELINE_VERSION,
            "deterministic-rule",
            "1",
            hashlib.sha256(
                f"{NEWS_SCOPE_CLASSIFIER_VERSION}:{PIPELINE_VERSION}".encode("utf-8")
            ).hexdigest(),
            now,
            now,
            "COMPLETED",
        ),
    )
    return extraction_id, "inserted"


def _upsert_review_mention(
    conn: Any,
    schema: str | None,
    candidate: Candidate,
    extraction_id: str,
    category_code: str,
    category_id: str,
) -> str:
    ph = _placeholder(conn)
    table = _table(schema, "event_mentions")
    extraction_key = f"market-category:{category_code}"
    existing = _fetch_one(
        conn,
        f"SELECT * FROM {table} WHERE extraction_run_id={ph} AND extraction_key={ph}",
        (extraction_id, extraction_key),
    )
    target = {
        "event_category_id": category_id,
        "title_raw": candidate.title,
        "summary_raw": candidate.snippet,
        # Publication day is evidence chronology, not necessarily the event day.
        # Keep semantic event dates unresolved until extraction/review confirms them.
        "event_date_start": None,
        "event_date_end": None,
        "date_precision": "UNKNOWN",
        "confidence": 0.75,
    }
    if existing:
        if existing["status_code"] != "REVIEW_READY":
            return "protected"
        if all(existing.get(key) == value for key, value in target.items()):
            return "unchanged"
        conn.execute(
            f"UPDATE {table} SET event_category_id={ph},title_raw={ph},summary_raw={ph},"
            f"event_date_start={ph},event_date_end={ph},date_precision={ph},confidence={ph} "
            f"WHERE event_mention_id={ph} AND status_code='REVIEW_READY'",
            (*target.values(), existing["event_mention_id"]),
        )
        return "updated"
    conn.execute(
        f"INSERT INTO {table}(event_mention_id,extraction_run_id,extraction_key,event_category_id,title_raw,"
        f"summary_raw,event_date_start,event_date_end,date_precision,confidence,status_code) "
        f"VALUES({','.join([ph] * 11)})",
        (
            stable_id("daily_rss_em", candidate.document_version_id, category_code, PIPELINE_VERSION),
            extraction_id,
            extraction_key,
            category_id,
            candidate.title,
            candidate.snippet,
            None,
            None,
            "UNKNOWN",
            0.75,
            "REVIEW_READY",
        ),
    )
    return "inserted"


def _default_projector() -> Projector:
    from scripts.backfill_document_market_categories import backfill_document_market_categories

    return backfill_document_market_categories


def _default_contextual_projector() -> ContextualProjector:
    from scripts.process_incremental_contextual_intelligence import (
        process_contextual_document_versions,
    )

    return process_contextual_document_versions


def _default_headline_projector() -> HeadlineProjector:
    from scripts.backfill_headline_market_categories import (
        backfill_headline_market_categories,
    )

    return backfill_headline_market_categories


def _contextual_schema_available(conn: Any, schema: str | None) -> bool:
    if _is_sqlite(conn):
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='contextual_processing_campaigns'"
        ).fetchone() is not None
    return conn.execute(
        "SELECT to_regclass(%s) IS NOT NULL",
        (f"{schema or 'public'}.contextual_processing_campaigns",),
    ).fetchone()[0]


def process_daily_rss_classifications(
    conn: Any,
    *,
    schema: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    collection_slot: str | None = None,
    apply: bool = False,
    commit: bool = True,
    projector: Projector | None = None,
    contextual_projector: ContextualProjector | None = None,
    headline_projector: HeadlineProjector | None = None,
) -> dict[str, Any]:
    if (from_date is None) != (to_date is None):
        raise ValueError("from_date and to_date must be supplied together")
    if from_date and to_date <= from_date:
        raise ValueError("to_date must be exclusive and later than from_date")
    if not collection_slot and not from_date:
        target = datetime.now(SEOUL).date()
        from_date, to_date = target - timedelta(days=1), target + timedelta(days=1)

    schema_version = _require_schema(conn, schema)
    candidates = load_daily_candidates(
        conn,
        schema=schema,
        from_date=from_date,
        to_date=to_date,
        collection_slot=collection_slot,
    )
    events_before = int(conn.execute(f"SELECT count(*) FROM {_table(schema,'events')}").fetchone()[0])
    approved_before = int(
        conn.execute(
            f"SELECT count(*) FROM {_table(schema,'event_mentions')} em "
            f"JOIN {_table(schema,'extraction_runs')} er ON er.extraction_run_id=em.extraction_run_id "
            f"WHERE er.pipeline_version={_placeholder(conn)} AND em.status_code='APPROVED'",
            (PIPELINE_VERSION,),
        ).fetchone()[0]
    )
    counters = {
        "scope_inserted": 0,
        "scope_updated": 0,
        "scope_unchanged": 0,
        "extraction_inserted": 0,
        "extraction_updated": 0,
        "extraction_unchanged": 0,
        "mentions_inserted": 0,
        "mentions_updated": 0,
        "mentions_unchanged": 0,
        "mentions_protected": 0,
        "confirmed_without_publication": 0,
    }
    status_counts: dict[str, int] = {}
    confirmed_versions: list[str] = []
    conn.execute("SAVEPOINT daily_rss_classifications")
    savepoint_active = True
    try:
        now = utc_now()
        for candidate in candidates:
            result = classify_news_cre_scope(
                title=candidate.title,
                snippet=candidate.snippet,
                category_codes=tuple(sorted(candidate.categories)),
            )
            status_counts[result.status_code] = status_counts.get(result.status_code, 0) + 1
            scope_action = _upsert_scope(conn, schema, candidate, result, now)
            counters[f"scope_{scope_action}"] += 1
            if result.status_code != "CRE_CONFIRMED":
                continue
            event_day = publication_day_kst(candidate.published_at)
            if event_day is None:
                counters["confirmed_without_publication"] += 1
                continue
            extraction_id, extraction_action = _ensure_extraction(conn, schema, candidate, now)
            counters[f"extraction_{extraction_action}"] += 1
            for code, category_id in sorted(candidate.categories.items()):
                mention_action = _upsert_review_mention(
                    conn, schema, candidate, extraction_id, code, category_id
                )
                counters[f"mentions_{mention_action}"] += 1
            confirmed_versions.append(candidate.document_version_id)

        projection: dict[str, Any] = {"skipped": True, "reason": "no confirmed version with publication date"}
        headline_projection: dict[str, Any] = {
            "skipped": True,
            "reason": "no confirmed version with publication date",
        }
        contextual_projection: dict[str, Any] = {
            "skipped": True,
            "reason": "no confirmed version with publication date",
        }
        projection_start = from_date
        projection_end = to_date
        published_days = [
            day
            for item in candidates
            if (day := publication_day_kst(item.published_at)) is not None
        ]
        if projection_start is None and published_days:
            projection_start = min(published_days)
        if projection_end is None and published_days:
            projection_end = max(published_days) + timedelta(days=1)

        if confirmed_versions:
            projection_runner = projector or _default_projector()
            if projection_start is None or projection_end is None:
                raise RuntimeError("confirmed daily RSS versions require a bounded publication window")
            projection = projection_runner(
                conn,
                start_date=projection_start.isoformat(),
                end_date=projection_end.isoformat(),
                document_version_ids=sorted(set(confirmed_versions)),
                apply=True,
                commit=False,
            )
            if contextual_projector is not None or _contextual_schema_available(conn, schema):
                contextual_runner = contextual_projector or _default_contextual_projector()
                contextual_projection = contextual_runner(
                    conn,
                    schema=schema,
                    document_version_ids=sorted(set(confirmed_versions)),
                    apply=True,
                )
            else:
                contextual_projection = {
                    "skipped": True,
                    "reason": "contextual feature schema unavailable",
                }

        # A supplied primary-projector spy keeps older focused tests isolated
        # unless they explicitly supply a headline projector. Production runs
        # this bounded catch-up even when the current collection slot produced
        # no newly confirmed versions: older articles inside the same lookback
        # can have become eligible after this rule was introduced.
        if headline_projector is not None or projector is None:
            if projection_start is not None and projection_end is not None:
                headline_runner = headline_projector or _default_headline_projector()
                headline_projection = headline_runner(
                    conn,
                    start_date=projection_start.isoformat(),
                    end_date=projection_end.isoformat(),
                    # Date, latest-version CRE_CONFIRMED scope, and absence of
                    # any active governed category are the catch-up guards.
                    document_version_ids=None,
                    apply=True,
                    commit=False,
                )
            else:
                headline_projection = {
                    "skipped": True,
                    "reason": "no bounded publication window",
                }
        else:
            headline_projection = {
                "skipped": True,
                "reason": "explicit primary projector isolation",
            }

        events_after = int(conn.execute(f"SELECT count(*) FROM {_table(schema,'events')}").fetchone()[0])
        if events_after != events_before:
            raise RuntimeError("daily RSS review processing must not mutate canonical events")
        approved_after = int(
            conn.execute(
                f"SELECT count(*) FROM {_table(schema,'event_mentions')} em "
                f"JOIN {_table(schema,'extraction_runs')} er ON er.extraction_run_id=em.extraction_run_id "
                f"WHERE er.pipeline_version={_placeholder(conn)} AND em.status_code='APPROVED'",
                (PIPELINE_VERSION,),
            ).fetchone()[0]
        )
        if approved_after != approved_before:
            raise RuntimeError("daily RSS review processing must not create APPROVED event mentions")

        report = {
            "status": "applied" if apply else "rollback_rehearsal",
            "schemaVersion": schema_version,
            "pipelineVersion": PIPELINE_VERSION,
            "scopeClassifierVersion": NEWS_SCOPE_CLASSIFIER_VERSION,
            "projectionClassifierVersion": PROJECTION_CLASSIFIER_VERSION,
            "headlineProjectionClassifierVersion": HEADLINE_PROJECTION_CLASSIFIER_VERSION,
            "fromDate": from_date.isoformat() if from_date else None,
            "toDateExclusive": to_date.isoformat() if to_date else None,
            "collectionSlot": collection_slot,
            "candidates": len(candidates),
            "scopeStatusCounts": dict(sorted(status_counts.items())),
            **counters,
            "confirmedDocumentVersions": len(set(confirmed_versions)),
            "projection": projection,
            "headlineProjection": headline_projection,
            "contextualProjection": contextual_projection,
            "canonicalEventsBefore": events_before,
            "canonicalEventsAfter": events_after,
            "approvedMentionsBefore": approved_before,
            "approvedMentionsAfter": approved_after,
        }
        if apply:
            conn.execute("RELEASE daily_rss_classifications")
            savepoint_active = False
            if commit:
                conn.commit()
        else:
            conn.execute("ROLLBACK TO daily_rss_classifications")
            conn.execute("RELEASE daily_rss_classifications")
            savepoint_active = False
        return report
    except Exception:
        if savepoint_active:
            conn.execute("ROLLBACK TO daily_rss_classifications")
            conn.execute("RELEASE daily_rss_classifications")
        elif apply and commit:
            conn.rollback()
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assess daily RSS and create review-only governed category candidates")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--schema")
    parser.add_argument("--from-date", type=date.fromisoformat)
    parser.add_argument("--to-date", type=date.fromisoformat, help="exclusive KST publication date")
    parser.add_argument("--collection-slot", type=parse_collection_slot)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if (args.from_date is None) != (args.to_date is None):
        raise SystemExit("--from-date and --to-date must be supplied together")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    env = load_env(args.env_file)
    dsn = os.environ.get("SUPABASE_DB_URL") or env.get("SUPABASE_DB_URL") or env.get("DATABASE_URL")
    schema = args.schema or os.environ.get("SUPABASE_DB_SCHEMA") or env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL or DATABASE_URL is missing")
    if not IDENTIFIER.fullmatch(schema):
        raise SystemExit("invalid schema")
    with psycopg.connect(dsn, connect_timeout=20) as conn:
        conn.execute("SET statement_timeout TO 300000")
        if args.apply:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"{PIPELINE_VERSION}:{args.collection_slot or args.from_date}",),
            )
        report = process_daily_rss_classifications(
            conn,
            schema=schema,
            from_date=args.from_date,
            to_date=args.to_date,
            collection_slot=args.collection_slot,
            apply=args.apply,
        )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
