#!/usr/bin/env python
"""Add conservative title/snippet MARKET_CATEGORY review candidates.

Only the latest CRE-confirmed version of a document with no current governed
market category is eligible. Collection-query categories are intentionally not
an input, canonical events are never mutated, and every result stays
PENDING/INFERRED until human review.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backfill_document_market_categories import (  # noqa: E402
    DEFAULT_DB,
    load_market_term_index,
    stable_assignment_id,
)


CLASSIFIER_VERSION = "DOCUMENT_HEADLINE_MARKET_CATEGORY_V1"

ASSET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"오피스", r"업무시설", r"업무용\s*빌딩", r"사옥", r"빌딩", r"타워",
        r"호텔", r"리조트", r"골프장", r"물류(?:센터|창고)", r"데이터\s*센터",
        r"상업시설", r"리테일", r"쇼핑몰", r"백화점", r"복합(?:시설|개발)",
        r"부동산", r"실물\s*자산", r"commercial\s+real\s+estate",
    )
)

CATEGORY_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (term, tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns))
    for term, patterns in (
        ("PERMIT", (r"건축\s*(?:허가|신고)", r"착공\s*신고", r"용도\s*변경", r"사업시행\s*인가", r"사용\s*승인")),
        ("ACQUISITION", (r"매입", r"매수", r"취득", r"인수(?!\s*금융)", r"\bacquisition\b")),
        ("SALE", (r"매각", r"매도", r"유찰", r"예비\s*입찰", r"본\s*입찰", r"우선협상대상자", r"우협", r"매매\s*계약", r"\bdisposition\b")),
        ("AUCTION", (r"경\s*[·ㆍ/]?\s*공매", r"경매", r"공매", r"\bauction\b")),
        ("LEASE", (r"임대차\s*계약", r"신규\s*임차", r"임차인\s*모집", r"재계약", r"마스터\s*리스", r"\blease\s+(?:signed|executed)\b")),
        ("SUPPLY", (r"개발\s*(?:계획|확정|추진)", r"신축", r"착공", r"준공", r"완공", r"개장", r"개관")),
        ("PF", (r"부동산\s*PF", r"프로젝트\s*파이낸싱", r"브릿지\s*론", r"본\s*PF", r"대주단")),
        ("LOAN", (r"담보\s*대출", r"(?:선|중|후)순위\s*대출", r"인수\s*금융", r"리파이낸싱", r"차환")),
    )
)


def _normalized(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _first_match(patterns: Sequence[re.Pattern[str]], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def infer_headline_market_category(
    title: str | None,
    snippet: str | None,
) -> dict[str, Any] | None:
    """Return one deterministic leaf category backed by asset+action wording."""
    title_text = _normalized(title)
    snippet_text = _normalized(snippet)
    combined = f"{title_text} {snippet_text}".strip()
    asset_title = _first_match(ASSET_PATTERNS, title_text)
    asset_any = asset_title or _first_match(ASSET_PATTERNS, combined)
    if not asset_any:
        return None
    for term_code, patterns in CATEGORY_PATTERNS:
        action_title = _first_match(patterns, title_text)
        action_any = action_title or _first_match(patterns, combined)
        if action_any:
            title_grounded = bool(asset_title and action_title)
            return {
                "term_code": term_code,
                "confidence": 0.9 if title_grounded else 0.82,
                "asset_evidence": asset_any,
                "action_evidence": action_any,
                "evidence_fields": ["title"] if title_grounded else ["title", "snippet"],
            }
    return None


def _postgres(conn: Any) -> bool:
    return conn.__class__.__module__.startswith("psycopg")


def _sql(conn: Any, text: str) -> str:
    return text.replace("?", "%s") if _postgres(conn) else text


def _rows(conn: Any, text: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(_sql(conn, text), tuple(params))
    names = [column.name if hasattr(column, "name") else column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def load_unclassified_cre_documents(
    conn: Any,
    *,
    start_date: str,
    end_date: str,
    document_version_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    version_filter = ""
    date_filter = "AND date(dv.published_at,'+9 hours')>=? AND date(dv.published_at,'+9 hours')<?"
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
        f"""WITH latest_versions AS MATERIALIZED (
               SELECT dv.* FROM document_versions dv
               WHERE NOT EXISTS (
                 SELECT 1 FROM document_versions newer
                 WHERE newer.document_id=dv.document_id
                   AND (newer.version_no>dv.version_no OR
                        (newer.version_no=dv.version_no AND
                         newer.document_version_id>dv.document_version_id))
               )
             )
             SELECT sd.document_id,dv.document_version_id,dv.title,dv.snippet_text
             FROM latest_versions dv
             JOIN source_documents sd ON sd.document_id=dv.document_id
             WHERE sd.document_type IN ('RSS_ITEM','ARTICLE')
               AND dv.published_at IS NOT NULL
               {date_filter}
               {version_filter}
               AND (
                 SELECT dsa.status_code FROM document_scope_assessments dsa
                 WHERE dsa.document_version_id=dv.document_version_id
                   AND dsa.scope_code='CRE'
                 ORDER BY dsa.assessed_at DESC,dsa.classifier_version DESC,
                          dsa.document_scope_assessment_id DESC LIMIT 1
               )='CRE_CONFIRMED'
               AND NOT EXISTS (
                 SELECT 1 FROM record_classifications rc
                 JOIN classification_schemes scheme
                   ON scheme.classification_scheme_id=rc.classification_scheme_id
                 WHERE rc.target_kind='DOCUMENT' AND rc.target_id=sd.document_id
                   AND scheme.scheme_code='MARKET_CATEGORY'
                   AND rc.review_status NOT IN ('REJECTED','SUPERSEDED')
                   AND rc.valid_to IS NULL
               )
             ORDER BY sd.document_id""",
        params,
    )


def plan_headline_market_categories(
    rows: Sequence[Mapping[str, Any]],
    term_index: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for row in rows:
        evidence = infer_headline_market_category(row.get("title"), row.get("snippet_text"))
        if evidence is None:
            continue
        term_code = str(evidence["term_code"])
        term = term_index.get(term_code)
        if term is None:
            raise RuntimeError(f"managed MARKET_CATEGORY term is unavailable: {term_code}")
        document_id = str(row["document_id"])
        version_id = str(row["document_version_id"])
        scheme_id = str(term["classification_scheme_id"])
        term_id = str(term["classification_term_id"])
        plan.append({
            "record_classification_id": stable_assignment_id(
                document_id, scheme_id, term_id, CLASSIFIER_VERSION
            ),
            "target_id": document_id,
            "classification_scheme_id": scheme_id,
            "classification_term_id": term_id,
            "term_code": term_code,
            "source_document_version_id": version_id,
            "confidence": evidence["confidence"],
            "evidence_locator": f"document_versions:{version_id}#title+snippet",
            "lineage": {
                "projection_method": "DETERMINISTIC_HEADLINE_FALLBACK",
                "source_table": "document_versions",
                "source_document_version_id": version_id,
                "input_fields": evidence["evidence_fields"],
                "collection_query_used": False,
            },
            "metadata": {
                "rule_version": CLASSIFIER_VERSION,
                "asset_evidence": evidence["asset_evidence"],
                "action_evidence": evidence["action_evidence"],
            },
        })
    return plan


def apply_headline_market_category_plan(
    conn: Any,
    plan: Sequence[Mapping[str, Any]],
    *,
    apply: bool,
    commit: bool,
) -> dict[str, int]:
    inserted = 0
    if apply:
        for item in plan:
            cursor = conn.execute(
                _sql(conn, """INSERT INTO record_classifications(
                     record_classification_id,target_kind,target_id,
                     classification_scheme_id,classification_term_id,
                     assignment_role,is_primary,confidence,classifier_version,
                     evidence_status,source_document_version_id,evidence_locator,
                     review_status,lineage_json,metadata_json
                   ) VALUES(?,'DOCUMENT',?,?,?,?,1,?,?, 'INFERRED',?,?,'PENDING',?,?)
                   ON CONFLICT(target_kind,target_id,classification_scheme_id,
                               classification_term_id,assignment_role,classifier_version)
                   DO NOTHING"""),
                (
                    item["record_classification_id"], item["target_id"],
                    item["classification_scheme_id"], item["classification_term_id"],
                    "DERIVED", item["confidence"], CLASSIFIER_VERSION,
                    item["source_document_version_id"], item["evidence_locator"],
                    json.dumps(item["lineage"], ensure_ascii=False, sort_keys=True),
                    json.dumps(item["metadata"], ensure_ascii=False, sort_keys=True),
                ),
            )
            inserted += max(cursor.rowcount, 0)
        if commit:
            conn.commit()
    return {
        "assignments_planned": len(plan),
        "assignments_would_insert": len(plan),
        "assignments_inserted": inserted,
    }


def backfill_headline_market_categories(
    conn: Any,
    *,
    start_date: str = "2026-01-01",
    end_date: str = "2027-01-01",
    document_version_ids: Sequence[str] | None = None,
    apply: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    if date.fromisoformat(end_date) <= date.fromisoformat(start_date):
        raise ValueError("end date must be later than start date")
    candidates = load_unclassified_cre_documents(
        conn,
        start_date=start_date,
        end_date=end_date,
        document_version_ids=document_version_ids,
    )
    plan = plan_headline_market_categories(candidates, load_market_term_index(conn))
    result = apply_headline_market_category_plan(
        conn, plan, apply=apply, commit=commit
    )
    return {
        "classifier_version": CLASSIFIER_VERSION,
        "status": "applied" if apply else "dry_run",
        "eligible_unclassified_documents": len(candidates),
        "projected_documents": len(plan),
        "unresolved_documents": len(candidates) - len(plan),
        "counts_by_term": [
            {"key": term, "documents": sum(item["term_code"] == term for item in plan)}
            for term in sorted({str(item["term_code"]) for item in plan})
        ],
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_DB)
    parser.add_argument("--from-date", default="2026-01-01")
    parser.add_argument("--to-date", default="2027-01-01")
    parser.add_argument("--document-version", action="append", dest="document_versions")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with sqlite3.connect(args.sqlite.resolve()) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        report = backfill_headline_market_categories(
            conn,
            start_date=args.from_date,
            end_date=args.to_date,
            document_version_ids=args.document_versions,
            apply=args.apply,
        )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
