#!/usr/bin/env python
"""Project reviewed event mentions onto document market-category assignments.

The backfill is deliberately additive: it never mutates event mentions or
canonical events, and dry-run is the default.  Both the backlog command and
the daily ingestion runner can reuse the pure inference/planning helpers so
they converge on the same assignment identity.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
DEFAULT_START_DATE = "2026-01-01"
DEFAULT_END_DATE = "2027-01-01"
CLASSIFIER_VERSION = "DOCUMENT_EVENT_MENTION_V1"
SCHEME_CODE = "MARKET_CATEGORY"


LEGACY_TERM_MAP: dict[str, tuple[str, ...]] = {
    # Already-managed codes are a forward-compatible direct input contract.
    "ACQUISITION": ("ACQUISITION",),
    "AUCTION": ("AUCTION",),
    "RELOCATION": ("RELOCATION",),
    "VACANCY": ("VACANCY",),
    "SUPPLY": ("SUPPLY",),
    "COMPLETION": ("COMPLETION",),
    "EQUITY_INVESTMENT": ("EQUITY_INVESTMENT",),
    "FUNDRAISING": ("FUNDRAISING",),
}


KEYWORD_RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "SALE": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"매각", r"매도", r"유형자산\s*양도", r"매물", r"매각\s*(?:자문|주관사)",
            r"티저\s*레터", r"예비\s*입찰", r"본\s*입찰", r"우선협상대상자", r"우협",
            r"매매\s*계약", r"거래\s*종결", r"실거래", r"\bsale\b", r"\bdisposition\b",
        )
    ),
    "ACQUISITION": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"매입", r"인수(?!\s*금융)", r"취득", r"매수", r"유형자산\s*양수", r"실거래",
            r"\bacquisition\b", r"\bacquir(?:e|ed|ing)\b",
        )
    ),
    "AUCTION": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (r"경\s*[·ㆍ/]?\s*공매", r"경매", r"공매", r"\bauction\b")
    ),
    "RELOCATION": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"(?:본사|사옥|오피스|사업장|사무실)\s*이전",
            r"이전\s*(?:계획|예정|결정|확정|완료|추진)",
            r"\brelocat(?:e|ed|es|ing|ion)\b",
        )
    ),
    "VACANCY": tuple(
        re.compile(pattern, re.IGNORECASE) for pattern in (r"공실", r"\bvacan(?:cy|t)\b")
    ),
    "LEASE": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"임대\s*(?:개시|공고|모집)", r"임차인\s*모집", r"입점업체\s*모집",
            r"임대차\s*계약\s*(?:체결|확정|갱신)", r"신규\s*임차", r"입주\s*(?:확정|계약|개시)",
            r"재계약", r"마스터\s*리스", r"프리\s*리스", r"\blease\s+(?:signed|executed)\b",
        )
    ),
    "SUPPLY": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"개발\s*(?:계획|확정|추진)", r"신축", r"착공", r"공사\s*개시", r"상량식",
            r"준공", r"완공", r"사용\s*승인", r"개장", r"개관", r"입주\s*개시",
        )
    ),
    "COMPLETION": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"(?:준공|완공)\s*(?:했다|됐다|완료|확정|행사|기념식|준공식)",
            r"(?:준공|완공)(?=…|\.\.\.|[·:])",
            r"사용\s*승인\s*(?:획득|완료|받|처리)",
            r"(?:개장|개관)\s*(?:했다|됐다|완료|행사|기념식)",
            r"\bcompleted\b", r"\bcompletion\s+(?:announced|confirmed)\b",
        )
    ),
    "PERMIT": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"건축\s*(?:허가|신고)", r"착공\s*신고", r"용도\s*변경", r"개발행위\s*허가",
            r"사업시행\s*인가", r"실시계획\s*인가", r"건축위원회", r"환경영향평가",
            r"조건부\s*승인", r"변경\s*고시",
        )
    ),
    "PF": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"부동산\s*PF", r"프로젝트\s*파이낸싱", r"브릿지\s*론", r"본\s*PF",
            r"PF\s*(?:대출|약정|전환|차환|리파이낸싱|재구조화|만기)", r"대주단\s*구성",
            r"책임\s*준공", r"기한이익상실", r"(?<![A-Za-z])EOD(?![A-Za-z])",
        )
    ),
    "LOAN": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"담보\s*대출", r"(?:선|중|후)순위\s*대출", r"인수\s*금융", r"대출\s*(?:약정|실행)",
            r"리파이낸싱", r"차환", r"만기\s*연장", r"셀\s*다운", r"채권\s*매각", r"담보권\s*실행",
        )
    ),
    "EQUITY_INVESTMENT": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"자산\s*편입", r"현물\s*출자", r"지분\s*투자", r"공동\s*투자", r"투자\s*집행",
            r"수익증권\s*(?:취득|양수)", r"(?:출자|약정)\s*(?:결정|확정|체결|완료)",
            r"투자\s*클로징", r"\bequity\s+investment\b",
        )
    ),
    "FUNDRAISING": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"자금\s*모집",
            r"출자자\s*모집",
            r"펀드\s*(?:조성|결성)",
            r"모집\s*완료",
            r"\bfund\s*rais(?:e|ed|ing)\b",
            r"\bfundraising\b",
            r"\bcapital\s+raise\b",
            r"\bfund\s+formation\b",
        )
    ),
}


CONTENT_TERM_RULES: dict[str, tuple[str, ...]] = {
    "SALE": ("SALE", "ACQUISITION", "AUCTION"),
    "LEASE": ("LEASE", "RELOCATION", "VACANCY"),
    "NEW_SUPPLY": ("SUPPLY", "COMPLETION"),
    "PERMIT": ("PERMIT",),
    "PF": ("PF",),
    "LOAN": ("LOAN",),
    "INVESTMENT": ("EQUITY_INVESTMENT", "FUNDRAISING"),
    "CORPORATE_RELOCATION": ("RELOCATION",),
}


def stable_assignment_id(
    document_id: str,
    classification_scheme_id: str,
    classification_term_id: str,
    classifier_version: str = CLASSIFIER_VERSION,
) -> str:
    """Return the shared backlog/daily assignment identity."""
    raw = "\x1f".join(
        (document_id, classification_scheme_id, classification_term_id, classifier_version)
    )
    return f"class-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _normalized_text(*values: str | None) -> str:
    text = " ".join(value for value in values if value)
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def infer_market_terms(
    legacy_category: str | None,
    title: str | None,
    snippet: str | None,
) -> dict[str, str]:
    """Map one legacy category and explicit wording to governed terms.

    Values are deterministic rule labels.  Returning a mapping (rather than a
    set) lets lineage explain exactly why every projected term was selected.
    """
    category = (legacy_category or "").strip().upper()
    inferred: dict[str, str] = {
        term: f"legacy_category:{category}"
        for term in LEGACY_TERM_MAP.get(category, ())
    }
    searchable = _normalized_text(title, snippet)
    for term in CONTENT_TERM_RULES.get(category, ()):
        if any(pattern.search(searchable) for pattern in KEYWORD_RULES[term]):
            inferred[term] = f"explicit_keyword:{term}"
    return dict(sorted(inferred.items()))


def _postgres(conn: Any) -> bool:
    return conn.__class__.__module__.startswith("psycopg")


def _sql(conn: Any, text: str) -> str:
    return text.replace("?", "%s") if _postgres(conn) else text


def _execute(conn: Any, text: str, params: Iterable[Any] = ()) -> Any:
    return conn.execute(_sql(conn, text), tuple(params))


def _rows(conn: Any, text: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cursor = _execute(conn, text, params)
    names = [column.name if hasattr(column, "name") else column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def load_market_term_index(conn: Any) -> dict[str, dict[str, str]]:
    rows = _rows(
        conn,
        """SELECT s.classification_scheme_id,t.classification_term_id,t.term_code
           FROM classification_schemes s
           JOIN classification_terms t USING(classification_scheme_id)
           WHERE s.scheme_code=? AND s.governance_status='ACTIVE'
             AND t.governance_status='ACTIVE' AND t.is_assignable=1
           ORDER BY t.term_code""",
        (SCHEME_CODE,),
    )
    index = {
        row["term_code"]: {
            "classification_scheme_id": row["classification_scheme_id"],
            "classification_term_id": row["classification_term_id"],
        }
        for row in rows
    }
    required = {term for terms in LEGACY_TERM_MAP.values() for term in terms}
    required.update(term for terms in CONTENT_TERM_RULES.values() for term in terms)
    missing = sorted(required - index.keys())
    if missing:
        raise RuntimeError(f"missing active {SCHEME_CODE} terms: {', '.join(missing)}")
    return index


def load_candidate_mentions(
    conn: Any,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    document_version_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Read eligible mentions from the latest version of each document.

    Explicit version IDs are an authoritative runner hand-off and therefore do
    not also receive the publication-date filter.  This avoids UTC/KST
    midnight boundaries dropping a version selected by the daily stage.
    """
    version_filter = ""
    date_filter = """AND COALESCE(
                         NULLIF(dv.published_at,''),NULLIF(dv.collected_at,''),sd.first_seen_at
                       )>=?
                     AND COALESCE(
                         NULLIF(dv.published_at,''),NULLIF(dv.collected_at,''),sd.first_seen_at
                       )<?"""
    params: list[Any] = [start_date, end_date]
    if document_version_ids is not None:
        selected = sorted(set(document_version_ids))
        if not selected:
            return []
        version_filter = f" AND dv.document_version_id IN ({','.join('?' for _ in selected)})"
        date_filter = ""
        params = list(selected)

    return _rows(
        conn,
        f"""WITH ranked_versions AS (
               SELECT dv.*,
                      row_number() OVER (
                        PARTITION BY dv.document_id
                        ORDER BY dv.version_no DESC,dv.document_version_id DESC
                      ) AS version_rank
               FROM document_versions dv
             ), ranked_scope AS (
               SELECT dsa.*,
                      row_number() OVER (
                        PARTITION BY dsa.document_version_id,dsa.scope_code
                        ORDER BY dsa.assessed_at DESC,dsa.document_scope_assessment_id DESC
                      ) AS scope_rank
               FROM document_scope_assessments dsa
               WHERE dsa.scope_code='CRE'
             )
             SELECT sd.document_id,dv.document_version_id,dv.title AS document_title,
                    dv.snippet_text AS document_snippet,
                    cs.source_code,cs.source_name,cs.source_kind,
                    em.event_mention_id,em.extraction_run_id,
                    em.status_code AS mention_status,em.confidence AS mention_confidence,
                    ec.code AS legacy_category_code
             FROM ranked_versions dv
             JOIN source_documents sd ON sd.document_id=dv.document_id
             LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
             JOIN ranked_scope dsa ON dsa.document_version_id=dv.document_version_id
                                  AND dsa.scope_rank=1
                                  AND dsa.status_code='CRE_CONFIRMED'
             JOIN extraction_runs er ON er.document_version_id=dv.document_version_id
             JOIN event_mentions em ON em.extraction_run_id=er.extraction_run_id
             JOIN event_categories ec ON ec.event_category_id=em.event_category_id
             WHERE dv.version_rank=1
               {date_filter}
               AND em.status_code NOT IN ('REJECTED','SUPERSEDED')
               {version_filter}
             ORDER BY sd.document_id,em.event_mention_id""",
        params,
    )


def plan_document_market_categories(
    mention_rows: Sequence[Mapping[str, Any]],
    term_index: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Collapse mention evidence to one deterministic document/term plan."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in mention_rows:
        inferred = infer_market_terms(
            str(row.get("legacy_category_code") or ""),
            row.get("document_title"),
            row.get("document_snippet"),
        )
        for term_code, rule in inferred.items():
            if term_code not in term_index:
                raise RuntimeError(f"managed term is missing from index: {term_code}")
            key = (str(row["document_id"]), term_code)
            if key not in grouped:
                term = term_index[term_code]
                scheme_id = str(term["classification_scheme_id"])
                term_id = str(term["classification_term_id"])
                grouped[key] = {
                    "record_classification_id": stable_assignment_id(
                        str(row["document_id"]), scheme_id, term_id
                    ),
                    "target_kind": "DOCUMENT",
                    "target_id": str(row["document_id"]),
                    "classification_scheme_id": scheme_id,
                    "classification_term_id": term_id,
                    "term_code": term_code,
                    "assignment_role": "DERIVED",
                    "is_primary": 0,
                    "confidence": 0.0,
                    "classifier_version": CLASSIFIER_VERSION,
                    "evidence_status": "INFERRED",
                    "source_document_version_id": str(row["document_version_id"]),
                    "source_code": row.get("source_code") or "UNKNOWN",
                    "source_name": row.get("source_name"),
                    "source_kind": row.get("source_kind"),
                    "mention_ids": set(),
                    "extraction_run_ids": set(),
                    "legacy_categories": set(),
                    "mention_statuses": set(),
                    "inference_rules": set(),
                }
            item = grouped[key]
            item["confidence"] = max(
                float(item["confidence"]), float(row.get("mention_confidence") or 0.0)
            )
            item["mention_ids"].add(str(row["event_mention_id"]))
            item["extraction_run_ids"].add(str(row["extraction_run_id"]))
            item["legacy_categories"].add(str(row["legacy_category_code"]))
            item["mention_statuses"].add(str(row["mention_status"]))
            item["inference_rules"].add(rule)

    plan: list[dict[str, Any]] = []
    for key in sorted(grouped):
        raw = grouped[key]
        mention_ids = sorted(raw.pop("mention_ids"))
        extraction_run_ids = sorted(raw.pop("extraction_run_ids"))
        legacy_categories = sorted(raw.pop("legacy_categories"))
        mention_statuses = sorted(raw.pop("mention_statuses"))
        inference_rules = sorted(raw.pop("inference_rules"))
        raw["evidence_locator"] = f"event_mentions:{mention_ids[0]}"
        raw["review_status"] = "PENDING"
        raw["lineage"] = {
            "projection_method": "DOCUMENT_EVENT_MENTION",
            "source_table": "event_mentions",
            "source_event_mention_ids": mention_ids,
            "source_extraction_run_ids": extraction_run_ids,
            "source_document_version_id": raw["source_document_version_id"],
            "legacy_event_category_codes": legacy_categories,
            "source_mention_status_codes": mention_statuses,
        }
        raw["metadata"] = {
            "source_code": raw.pop("source_code"),
            "source_name": raw.pop("source_name"),
            "source_kind": raw.pop("source_kind"),
            "inference_rules": inference_rules,
        }
        plan.append(raw)
    return plan


def _existing_assignment_state(
    conn: Any, plan: Sequence[Mapping[str, Any]]
) -> tuple[set[tuple[str, str]], set[str]]:
    if not plan:
        return set(), set()
    document_ids = sorted({str(item["target_id"]) for item in plan})
    placeholders = ",".join("?" for _ in document_ids)
    rows = _rows(
        conn,
        f"""SELECT r.record_classification_id,r.target_id,r.classification_term_id,
                    r.review_status,r.valid_to
             FROM record_classifications r
             JOIN classification_schemes s
               ON s.classification_scheme_id=r.classification_scheme_id
             WHERE r.target_kind='DOCUMENT' AND s.scheme_code=?
               AND r.target_id IN ({placeholders})""",
        (SCHEME_CODE, *document_ids),
    )
    current = {
        (str(row["target_id"]), str(row["classification_term_id"]))
        for row in rows
        if row["review_status"] not in {"REJECTED", "SUPERSEDED"} and row["valid_to"] is None
    }
    identities = {str(row["record_classification_id"]) for row in rows}
    return current, identities


def apply_document_market_category_plan(
    conn: Any,
    plan: Sequence[Mapping[str, Any]],
    *,
    apply: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    """Insert only missing plan rows; dry-run performs no writes."""
    current, identities = _existing_assignment_state(conn, plan)
    pending: list[Mapping[str, Any]] = []
    existing_current = existing_identity = 0
    for item in plan:
        term_key = (str(item["target_id"]), str(item["classification_term_id"]))
        if term_key in current:
            existing_current += 1
        elif str(item["record_classification_id"]) in identities:
            # Historical/rejected rows remain immutable.  Do not revive them by update.
            existing_identity += 1
        else:
            pending.append(item)

    inserted = 0
    if apply:
        for item in pending:
            cursor = _execute(
                conn,
                """INSERT INTO record_classifications(
                     record_classification_id,target_kind,target_id,
                     classification_scheme_id,classification_term_id,
                     assignment_role,is_primary,confidence,classifier_version,
                     evidence_status,source_document_version_id,evidence_locator,
                     review_status,lineage_json,metadata_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(target_kind,target_id,classification_scheme_id,
                               classification_term_id,assignment_role,classifier_version)
                   DO NOTHING""",
                (
                    item["record_classification_id"],
                    item["target_kind"],
                    item["target_id"],
                    item["classification_scheme_id"],
                    item["classification_term_id"],
                    "DERIVED",
                    0,
                    item["confidence"],
                    CLASSIFIER_VERSION,
                    "INFERRED",
                    item["source_document_version_id"],
                    item["evidence_locator"],
                    "PENDING",
                    json.dumps(item["lineage"], ensure_ascii=False, sort_keys=True),
                    json.dumps(item["metadata"], ensure_ascii=False, sort_keys=True),
                ),
            )
            inserted += max(cursor.rowcount, 0)
        if commit:
            conn.commit()

    return {
        "assignments_planned": len(plan),
        "assignments_existing_current": existing_current,
        "assignments_existing_identity": existing_identity,
        "assignments_would_insert": len(pending),
        "assignments_inserted": inserted,
    }


def _count_rows(
    mention_rows: Sequence[Mapping[str, Any]],
    plan: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"documents": set(), "mentions": set()}
    )
    for row in mention_rows:
        value = str(row.get(field) or "UNKNOWN")
        grouped[value]["documents"].add(str(row["document_id"]))
        grouped[value]["mentions"].add(str(row["event_mention_id"]))
    return [
        {
            "key": key,
            "documents": len(grouped[key]["documents"]),
            "mentions": len(grouped[key]["mentions"]),
        }
        for key in sorted(grouped)
    ]


def _term_counts(
    mention_rows: Sequence[Mapping[str, Any]], plan: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    evidence: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"documents": set(), "mentions": set()}
    )
    for row in mention_rows:
        terms = infer_market_terms(
            str(row.get("legacy_category_code") or ""),
            row.get("document_title"),
            row.get("document_snippet"),
        )
        for term in terms:
            evidence[term]["documents"].add(str(row["document_id"]))
            evidence[term]["mentions"].add(str(row["event_mention_id"]))
    planned = defaultdict(int)
    for item in plan:
        planned[str(item["term_code"])] += 1
    return [
        {
            "key": term,
            "documents": len(evidence[term]["documents"]),
            "mentions": len(evidence[term]["mentions"]),
            "assignments_planned": planned[term],
        }
        for term in sorted(evidence)
    ]


def backfill_document_market_categories(
    conn: Any,
    *,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    document_version_ids: Sequence[str] | None = None,
    apply: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    """Build and optionally apply the document market-category projection."""
    _validate_dates(start_date, end_date)
    if _postgres(conn):
        conn.execute("SET search_path TO market_intelligence, public")
    mentions = load_candidate_mentions(
        conn,
        start_date=start_date,
        end_date=end_date,
        document_version_ids=document_version_ids,
    )
    term_index = load_market_term_index(conn)
    plan = plan_document_market_categories(mentions, term_index)
    result = apply_document_market_category_plan(
        conn, plan, apply=apply, commit=commit
    )
    unmapped = sorted(
        {
            str(row["legacy_category_code"])
            for row in mentions
            if not infer_market_terms(
                str(row.get("legacy_category_code") or ""),
                row.get("document_title"),
                row.get("document_snippet"),
            )
        }
    )
    return {
        "classifier_version": CLASSIFIER_VERSION,
        "start_date_inclusive": start_date,
        "end_date_exclusive": end_date,
        "eligible_documents": len({str(row["document_id"]) for row in mentions}),
        "eligible_mentions": len({str(row["event_mention_id"]) for row in mentions}),
        "projected_documents": len({str(item["target_id"]) for item in plan}),
        "unprojected_documents": len({str(row["document_id"]) for row in mentions})
        - len({str(item["target_id"]) for item in plan}),
        **result,
        "legacy_categories_with_unprojected_mentions": unmapped,
        "counts_by_term": _term_counts(mentions, plan),
        "counts_by_source": _count_rows(mentions, plan, "source_code"),
        "counts_by_status": _count_rows(mentions, plan, "mention_status"),
    }


def _validate_dates(start_date: str, end_date: str) -> None:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end <= start:
        raise ValueError("end date must be later than start date")


def _load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        text = raw.strip()
        if text and not text.startswith("#") and "=" in text:
            key, value = text.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill document MARKET_CATEGORY assignments from event mentions"
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--sqlite", nargs="?", const=DEFAULT_DB, type=Path)
    target.add_argument("--supabase", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--from-date", default=DEFAULT_START_DATE)
    parser.add_argument("--to-date", default=DEFAULT_END_DATE)
    parser.add_argument("--document-version", action="append", dest="document_versions")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    _validate_dates(args.from_date, args.to_date)

    if args.supabase:
        import psycopg

        env = _load_env(args.env_file)
        dsn = (
            os.environ.get("SUPABASE_DB_URL")
            or os.environ.get("DATABASE_URL")
            or env.get("SUPABASE_DB_URL")
            or env.get("DATABASE_URL")
        )
        if not dsn:
            raise RuntimeError("missing SUPABASE_DB_URL or DATABASE_URL")
        conn = psycopg.connect(dsn)
    else:
        db_path = Path(args.sqlite or DEFAULT_DB).resolve()
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")

    try:
        result = backfill_document_market_categories(
            conn,
            start_date=args.from_date,
            end_date=args.to_date,
            document_version_ids=args.document_versions,
            apply=args.apply,
        )
        payload = {
            "status": "applied" if args.apply else "dry_run",
            "target": "supabase" if args.supabase else "sqlite",
            "result": result,
        }
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
