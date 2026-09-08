"""Refresh deterministic keyword analytics from latest document titles/snippets.

Dry-run is the default. Use --apply to persist derived rows. Raw documents are never changed.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import sqlite3
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ALGORITHM_VERSION = "KO_TITLE_PHRASE_DF_V1"
TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9]{2,}")
STOPWORDS = {"관련", "대한", "위한", "통해", "따른", "이번", "시장", "부동산", "기준", "현황", "발표", "기자", "뉴스"}
MAX_TERMS_PER_DOCUMENT = 30
MAX_PAIR_TERMS_PER_DOCUMENT = 8
MIN_GLOBAL_DOCUMENT_FREQUENCY = 2


def normalize_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().lower()


def extract_terms(title: str | None, snippet: str | None) -> list[str]:
    tokens = [normalize_term(item) for item in TOKEN_RE.findall(f"{title or ''} {snippet or ''}")]
    tokens = [item for item in tokens if item not in STOPWORDS and len(item) >= 2]
    ordered: list[str] = []
    seen: set[str] = set()
    for term in tokens:
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    for left, right in zip(tokens, tokens[1:]):
        phrase = f"{left} {right}"
        if left != right and phrase not in seen:
            seen.add(phrase)
            ordered.append(phrase)
    return ordered[:MAX_TERMS_PER_DOCUMENT]


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def publication_day(value: object) -> str:
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def latest_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute("""
      WITH latest_versions AS (
        SELECT sd.document_id,dv.document_version_id,dv.title,dv.published_at,dv.collected_at,
               dv.snippet_text,sd.source_id,
               row_number() OVER(PARTITION BY sd.document_id ORDER BY dv.version_no DESC,dv.document_version_id DESC) rn
        FROM source_documents sd JOIN document_versions dv ON dv.document_id=sd.document_id
      ), latest_scope AS (
        SELECT document_version_id,status_code,
               row_number() OVER(
                 PARTITION BY document_version_id
                 ORDER BY assessed_at DESC,classifier_version DESC,document_scope_assessment_id DESC
               ) rn
        FROM document_scope_assessments
        WHERE scope_code='CRE'
      )
      SELECT v.document_id,v.document_version_id,v.title,v.published_at,v.collected_at,
             v.snippet_text,v.source_id,s.status_code AS scope_status
      FROM latest_versions v
      LEFT JOIN latest_scope s ON s.document_version_id=v.document_version_id AND s.rn=1
      WHERE v.rn=1
    """).fetchall()


def collection_bias_terms_from_jobs(conn: sqlite3.Connection) -> set[str]:
    try:
        rows = conn.execute("SELECT query_template FROM collection_jobs WHERE is_active=1 AND query_template IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        return set()
    terms: set[str] = set()
    for row in rows:
        for item in TOKEN_RE.findall(str(row[0] or "")):
            normalized = normalize_term(item)
            if normalized and normalized not in STOPWORDS:
                terms.add(normalized)
    return terms


def refresh_keywords(
    conn: sqlite3.Connection,
    *,
    apply: bool = False,
    collection_bias_terms: Iterable[str] = (),
    window_start: str | None = None,
    window_end: str | None = None,
    commit: bool = True,
) -> dict[str, int | str | bool]:
    bias = collection_bias_terms_from_jobs(conn)
    bias.update(normalize_term(item) for item in collection_bias_terms if normalize_term(item))
    rows = latest_documents(conn)
    excluded_scope = sum(
        1 for row in rows if str(row["scope_status"] or "").startswith("OUT_OF_SCOPE")
    )
    rows = [
        row for row in rows
        if not str(row["scope_status"] or "").startswith("OUT_OF_SCOPE")
    ]
    excluded_missing = sum(1 for row in rows if not row["published_at"])
    scoped = []
    target_scoped = []
    analysis_start = _days_before(window_start, 28) if window_start else None
    for row in rows:
        published = row["published_at"]
        if not published:
            continue
        day = publication_day(published)
        if analysis_start and day < analysis_start:
            continue
        if window_end and day >= window_end:
            continue
        scoped.append((row, day))
        if not window_start or day >= window_start:
            target_scoped.append((row, day))
    if target_scoped:
        effective_start = window_start or min(day for _, day in target_scoped)
        effective_end = window_end or _days_after(max(day for _, day in target_scoped),1)
    else:
        effective_start = window_start or datetime.now(timezone.utc).date().isoformat()
        effective_end = window_end or effective_start

    observations: dict[tuple[str, str], dict[str, object]] = {}
    cooccurrences: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    display_by_term: dict[str, str] = {}
    kind_by_term: dict[str, str] = {}
    for row, day in scoped:
        terms = extract_terms(row["title"], row["snippet_text"])
        raw_tokens = [normalize_term(item) for item in TOKEN_RE.findall(f"{row['title'] or ''} {row['snippet_text'] or ''}")]
        raw_counts = Counter(raw_tokens)
        for term in terms:
            display_by_term.setdefault(term, term)
            kind_by_term.setdefault(term, "PHRASE" if " " in term else "TOKEN")
            entry = observations.setdefault((day, term), {"documents": set(), "mentions": 0})
            entry["documents"].add(row["document_id"])
            entry["mentions"] = int(entry["mentions"]) + (1 if " " in term else max(raw_counts.get(term, 1), 1))
        pair_terms = sorted(set(terms[:MAX_PAIR_TERMS_PER_DOCUMENT]))
        for left, right in itertools.combinations(pair_terms, 2):
            cooccurrences[(day, left, right)].add(row["document_id"])

    documents_by_term: dict[str, set[str]] = defaultdict(set)
    for (_, term), entry in observations.items():
        documents_by_term[term].update(entry["documents"])
    eligible_terms = {term for term, documents in documents_by_term.items() if len(documents) >= MIN_GLOBAL_DOCUMENT_FREQUENCY}
    observations = {key: value for key, value in observations.items() if key[1] in eligible_terms}
    cooccurrences = defaultdict(set, {
        key: documents for key, documents in cooccurrences.items()
        if key[1] in eligible_terms and key[2] in eligible_terms
    })
    display_by_term = {term: value for term, value in display_by_term.items() if term in eligible_terms}
    kind_by_term = {term: value for term, value in kind_by_term.items() if term in eligible_terms}

    dates_by_term: dict[str, dict[str, int]] = defaultdict(dict)
    for (day, term), entry in observations.items():
        dates_by_term[term][day] = len(entry["documents"])

    target_observations = {key: value for key, value in observations.items() if effective_start <= key[0] < effective_end}
    target_cooccurrences = {key: value for key, value in cooccurrences.items() if effective_start <= key[0] < effective_end}

    computed_at = utc_now()
    run_id = f"analytics-run-{uuid.uuid4().hex}"
    conn.execute("SAVEPOINT keyword_refresh")
    try:
        for term in sorted(display_by_term):
            keyword_id = stable_id("kw", ALGORITHM_VERSION, term)
            conn.execute("""INSERT INTO keyword_dictionary(
              keyword_id,normalized_term,display_term,term_kind,status_code,is_collection_bias,
              algorithm_version,metadata_json,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(normalized_term,algorithm_version) DO UPDATE SET
                display_term=excluded.display_term,term_kind=excluded.term_kind,
                is_collection_bias=excluded.is_collection_bias,updated_at=excluded.updated_at""",
              (keyword_id, term, display_by_term[term], kind_by_term[term], "ACTIVE", int(term in bias),
               ALGORITHM_VERSION, "{}", computed_at, computed_at))
        conn.execute("DELETE FROM keyword_observations_daily WHERE algorithm_version=? AND source_scope_code='ALL' AND bucket_date>=? AND bucket_date<?", (ALGORITHM_VERSION, effective_start, effective_end))
        conn.execute("DELETE FROM keyword_cooccurrences_daily WHERE algorithm_version=? AND source_scope_code='ALL' AND bucket_date>=? AND bucket_date<?", (ALGORITHM_VERSION, effective_start, effective_end))

        for (day, term), entry in sorted(target_observations.items()):
            prior = [count for date, count in dates_by_term[term].items() if date < day and date >= _days_before(day, 28)]
            baseline = sum(prior) / 28.0
            df = len(entry["documents"])
            burst = (df - baseline) / math.sqrt(baseline + 1.0)
            keyword_id = stable_id("kw", ALGORITHM_VERSION, term)
            observation_id = stable_id("kwobs", day, keyword_id, "ALL", ALGORITHM_VERSION)
            conn.execute("""INSERT INTO keyword_observations_daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (observation_id, day, keyword_id, "ALL", df, max(int(entry["mentions"]), df), baseline, burst,
               computed_at, effective_start, effective_end, ALGORITHM_VERSION, "{}", json.dumps({"frequency_semantics":"DISTINCT_DOCUMENT"}, ensure_ascii=False)))
        for (day, left, right), documents in sorted(target_cooccurrences.items()):
            left_id = stable_id("kw", ALGORITHM_VERSION, left)
            right_id = stable_id("kw", ALGORITHM_VERSION, right)
            if left_id > right_id:
                left_id, right_id = right_id, left_id
            pair_id = stable_id("kwco", day, left_id, right_id, "ALL", ALGORITHM_VERSION)
            conn.execute("INSERT INTO keyword_cooccurrences_daily VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (pair_id, day, left_id, right_id, "ALL", len(documents), computed_at, effective_start, effective_end, ALGORITHM_VERSION, "{}"))
        conn.execute("""INSERT INTO analytics_refresh_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (run_id, "KEYWORD_DAILY", "COMPLETED", ALGORITHM_VERSION, effective_start, effective_end, "ALL",
           len(target_scoped), len(target_observations), computed_at, computed_at, None,
           json.dumps({"documents_excluded_missing_publication": excluded_missing}, ensure_ascii=False)))
        if apply:
            conn.execute("RELEASE keyword_refresh")
            if commit:
                conn.commit()
        else:
            conn.execute("ROLLBACK TO keyword_refresh")
            conn.execute("RELEASE keyword_refresh")
    except Exception:
        conn.execute("ROLLBACK TO keyword_refresh")
        conn.execute("RELEASE keyword_refresh")
        raise

    return {
        "applied": apply,
        "algorithm_version": ALGORITHM_VERSION,
        "documents_in_scope": len(target_scoped),
        "documents_excluded_scope": excluded_scope,
        "documents_excluded_missing_publication": excluded_missing,
        "keywords_planned": len(display_by_term),
        "observations_written": len(target_observations),
        "cooccurrences_written": len(target_cooccurrences),
    }


def _days_before(day: str, days: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(day) - timedelta(days=days)).isoformat()

def _days_after(day:str,days:int)->str:
    from datetime import date,timedelta
    return (date.fromisoformat(day)+timedelta(days=days)).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path(__file__).parents[1] / "data" / "market.db")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--window-start")
    parser.add_argument("--window-end")
    parser.add_argument("--bias-term", action="append", default=[])
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        version = conn.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()
        if not version or version[0] not in {"3.4.0", "3.4.1", "3.5.0"}:
            raise SystemExit(f"Expected schema 3.4.0, 3.4.1 or 3.5.0, found {version[0] if version else 'missing'}")
        report = refresh_keywords(conn, apply=args.apply, collection_bias_terms=args.bias_term, window_start=args.window_start, window_end=args.window_end)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
