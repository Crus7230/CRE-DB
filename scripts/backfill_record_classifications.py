#!/usr/bin/env python
"""Deterministically backfill governed classifications from canonical V3.2 fields.

The operation is additive and idempotent. Dry-run is the default; --apply commits.
Source/evidence identifiers are logical lineage references so assignments survive
active-serving retirement of detailed evidence rows.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")

EVENT_CATEGORY_CROSSWALK = {
    "INVESTMENT": "EQUITY_INVESTMENT",
    "NEW_SUPPLY": "SUPPLY",
    "CORPORATE_RELOCATION": "RELOCATION",
}
DOCUMENT_PURPOSE_BY_SOURCE = {
    "OPENDART": "COMPANY_EVIDENCE",
    "MOLIT_REAL_TRANSACTION": "TRANSACTION_EVIDENCE",
    "GOOGLE_NEWS_RSS": "MARKET_INTELLIGENCE",
    "APPROVED_LP_MANDATE_MANIFEST": "PROCEDURE_NOTICE",
    "CUTOFF_RESEARCH_20260819": "MARKET_INTELLIGENCE",
    "APPROVED_SALE_MANIFEST": "TRANSACTION_EVIDENCE",
}
DOCUMENT_PURPOSE_BY_TYPE = {
    "RSS_ITEM": "MARKET_INTELLIGENCE",
    "ARTICLE": "MARKET_INTELLIGENCE",
    "DISCLOSURE": "COMPANY_EVIDENCE",
    "BID_NOTICE": "PROCEDURE_NOTICE",
    "NOTICE": "PROCEDURE_NOTICE",
    "PRESS_RELEASE": "OFFICIAL_SOURCE",
}
OFFICIAL_SOURCE_CODES = {"OPENDART", "MOLIT_REAL_TRANSACTION", "APPROVED_LP_MANDATE_MANIFEST"}


def archived_market_code(target_kind: str, category_code: str | None) -> str | None:
    """Interpret compact category_code according to its record-kind contract."""
    if target_kind == "EVENT" and category_code:
        return EVENT_CATEGORY_CROSSWALK.get(category_code, category_code)
    if target_kind == "LP_MANDATE":
        return "LP_MANDATE"
    if target_kind == "SALE_PROCESS":
        return "SALE"
    return None


def stable_id(prefix: str, *parts: str) -> str:
    raw = ":".join([prefix, *[str(p) for p in parts]])
    return f"{prefix}-{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def _postgres(conn: Any) -> bool:
    return conn.__class__.__module__.startswith("psycopg")


def _sql(conn: Any, text: str) -> str:
    return text.replace("?", "%s") if _postgres(conn) else text


def _execute(conn: Any, text: str, params: Iterable[Any] = ()) -> Any:
    return conn.execute(_sql(conn, text), tuple(params))


def _rows(conn: Any, text: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cur = _execute(conn, text, params)
    names = [d.name if hasattr(d, "name") else d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _upsert_term(
    conn: Any, scheme_code: str, term_code: str, term_name_ko: str,
    *, parent_term_code: str | None = None, metadata: dict[str, Any] | None = None,
) -> tuple[str, str, bool]:
    scheme = _rows(conn, "SELECT classification_scheme_id FROM classification_schemes WHERE scheme_code=?", (scheme_code,))[0]
    scheme_id = scheme["classification_scheme_id"]
    existing = _rows(conn, "SELECT classification_term_id FROM classification_terms WHERE classification_scheme_id=? AND term_code=?", (scheme_id, term_code))
    if existing:
        return scheme_id, existing[0]["classification_term_id"], False
    parent_id = None
    if parent_term_code:
        parent = _rows(conn, "SELECT classification_term_id FROM classification_terms WHERE classification_scheme_id=? AND term_code=?", (scheme_id, parent_term_code))
        parent_id = parent[0]["classification_term_id"] if parent else None
    term_id = stable_id("term", scheme_code, term_code)
    cur = _execute(conn, """INSERT INTO classification_terms(
      classification_term_id,classification_scheme_id,term_code,term_name_ko,parent_term_id,
      synonyms_json,sort_order,is_assignable,governance_status,metadata_json
    ) VALUES(?,?,?,?,?,'[]',900,1,'ACTIVE',?)
    ON CONFLICT(classification_scheme_id,term_code) DO NOTHING""",
      (term_id, scheme_id, term_code, term_name_ko, parent_id, json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)))
    return scheme_id, term_id, bool(cur.rowcount)


def _insert_assignment(conn: Any, item: dict[str, Any], occupied_primary: set[tuple[str, str, str]]) -> bool:
    key = (item["target_kind"], item["target_id"], item["classification_scheme_id"])
    requested_primary = bool(item.get("is_primary"))
    is_primary = 1 if requested_primary and key not in occupied_primary else 0
    if is_primary:
        occupied_primary.add(key)
    assignment_id = stable_id(
        "class", item["target_kind"], item["target_id"], item["classification_scheme_id"],
        item["classification_term_id"], item["assignment_role"], item["classifier_version"],
    )
    cur = _execute(conn, """INSERT INTO record_classifications(
      record_classification_id,target_kind,target_id,classification_scheme_id,classification_term_id,
      assignment_role,is_primary,confidence,classifier_version,evidence_status,source_claim_id,
      source_document_version_id,evidence_locator,review_status,lineage_json,metadata_json
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'APPROVED',?,?)
    ON CONFLICT(target_kind,target_id,classification_scheme_id,classification_term_id,assignment_role,classifier_version)
    DO NOTHING""", (
      assignment_id,item["target_kind"],item["target_id"],item["classification_scheme_id"],
      item["classification_term_id"],item["assignment_role"],is_primary,item.get("confidence",1.0),
      item["classifier_version"],item.get("evidence_status","DIRECT_STRUCTURED"),item.get("source_claim_id"),
      item.get("source_document_version_id"),item.get("evidence_locator"),
      json.dumps(item["lineage"],ensure_ascii=False,sort_keys=True),
      json.dumps(item.get("metadata",{}),ensure_ascii=False,sort_keys=True),
    ))
    return bool(cur.rowcount)


def backfill_classifications(conn: Any, *, apply: bool = False, commit: bool = True) -> dict[str, Any]:
    if _postgres(conn):
        conn.execute("SET search_path TO market_intelligence, public")
    version = _rows(conn, "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'")[0]["schema_value"]
    if version not in {"3.3.0", "3.4.0", "3.4.1", "3.5.0"}:
        raise RuntimeError(f"classification backfill requires schema 3.3.0, 3.4.0, 3.4.1 or 3.5.0, found {version}")

    stats: Counter[str] = Counter()
    assignments: list[dict[str, Any]] = []

    # V1 treated every compact category_code as a market category. That is invalid
    # for document types and lifecycle statuses. Preserve the audit rows but retire them.
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    retired = _execute(conn, """UPDATE record_classifications
      SET review_status='SUPERSEDED',valid_to=coalesce(valid_to,?)
      WHERE classifier_version='ARCHIVE_CATEGORY_V1' AND review_status<>'SUPERSEDED'""", (now,))
    stats["assignments_superseded"] += max(retired.rowcount, 0)
    deprecated = _execute(conn, """UPDATE classification_terms
      SET governance_status='DEPRECATED',valid_to=coalesce(valid_to,?)
      WHERE classification_scheme_id=(SELECT classification_scheme_id FROM classification_schemes WHERE scheme_code='MARKET_CATEGORY')
        AND sort_order=900 AND metadata_json='{}' AND governance_status='ACTIVE'
        AND NOT EXISTS (
          SELECT 1 FROM record_classifications r
          WHERE r.classification_scheme_id=classification_terms.classification_scheme_id
            AND r.classification_term_id=classification_terms.classification_term_id
            AND r.review_status NOT IN ('REJECTED','SUPERSEDED') AND r.valid_to IS NULL
        )""", (now,))
    stats["terms_deprecated"] += max(deprecated.rowcount, 0)

    # Dynamic controlled vocabulary from existing canonical masters.
    event_terms: dict[str, tuple[str, str]] = {}
    for row in _rows(conn, "SELECT event_category_id,code,name_ko FROM event_categories ORDER BY code"):
        code = EVENT_CATEGORY_CROSSWALK.get(row["code"], row["code"])
        sid, tid, created = _upsert_term(conn, "MARKET_CATEGORY", code, row["name_ko"], metadata={"legacy_event_category_id": row["event_category_id"]})
        stats["terms_created"] += int(created); event_terms[row["event_category_id"]] = (sid, tid)
    asset_terms: dict[str, tuple[str, str]] = {}
    for row in _rows(conn, "SELECT asset_class_id,code,name_ko FROM asset_classes ORDER BY code"):
        sid, tid, created = _upsert_term(conn, "ASSET_CLASS", row["code"], row["name_ko"], metadata={"legacy_asset_class_id": row["asset_class_id"]})
        stats["terms_created"] += int(created); asset_terms[row["asset_class_id"]] = (sid, tid)
    org_terms: dict[str, tuple[str, str]] = {}
    for row in _rows(conn, "SELECT DISTINCT organization_type FROM organizations ORDER BY organization_type"):
        code = row["organization_type"]
        sid, tid, created = _upsert_term(conn, "ORGANIZATION_TYPE", code, code.replace("_", " ").title())
        stats["terms_created"] += int(created); org_terms[code] = (sid, tid)
    industry_terms: dict[str, tuple[str, str]] = {}
    for row in _rows(conn, "SELECT industry_node_id,industry_code,industry_name,taxonomy_code FROM industry_nodes ORDER BY taxonomy_code,industry_code"):
        code = f'{row["taxonomy_code"]}:{row["industry_code"]}'
        sid, tid, created = _upsert_term(conn, "INDUSTRY", code, row["industry_name"], metadata={"legacy_industry_node_id": row["industry_node_id"], "taxonomy_code": row["taxonomy_code"]})
        stats["terms_created"] += int(created); industry_terms[row["industry_node_id"]] = (sid, tid)

    # Existing primary assignments are authoritative and are never displaced.
    occupied_primary = {
      (r["target_kind"],r["target_id"],r["classification_scheme_id"])
      for r in _rows(conn, """SELECT target_kind,target_id,classification_scheme_id FROM record_classifications
        WHERE is_primary=1 AND valid_to IS NULL AND review_status IN ('UNREVIEWED','PENDING','APPROVED')""")
    }

    for row in _rows(conn, "SELECT event_id,primary_category_id FROM events WHERE primary_category_id IS NOT NULL ORDER BY event_id"):
        sid,tid=event_terms[row["primary_category_id"]]
        assignments.append(dict(target_kind="EVENT",target_id=row["event_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="EVENT_CATEGORY_V1",lineage={"source_table":"events","source_column":"primary_category_id","source_value":row["primary_category_id"]}))
    for row in _rows(conn, "SELECT asset_id,asset_class_id FROM assets WHERE asset_class_id IS NOT NULL ORDER BY asset_id"):
        sid,tid=asset_terms[row["asset_class_id"]]
        assignments.append(dict(target_kind="ASSET",target_id=row["asset_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="ASSET_CLASS_V1",lineage={"source_table":"assets","source_column":"asset_class_id","source_value":row["asset_class_id"]}))
    for row in _rows(conn, "SELECT organization_id,organization_type FROM organizations ORDER BY organization_id"):
        sid,tid=org_terms[row["organization_type"]]
        assignments.append(dict(target_kind="ORGANIZATION",target_id=row["organization_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="ORGANIZATION_TYPE_V1",lineage={"source_table":"organizations","source_column":"organization_type","source_value":row["organization_type"]}))
    for row in _rows(conn, """SELECT organization_id,industry_node_id,is_primary,assignment_basis,source_claim_id
      FROM organization_industry_assignments WHERE review_status<>'REJECTED'
      ORDER BY organization_id,is_primary DESC,organization_industry_assignment_id"""):
        sid,tid=industry_terms[row["industry_node_id"]]
        assignments.append(dict(target_kind="ORGANIZATION",target_id=row["organization_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=bool(row["is_primary"]),classifier_version="ORGANIZATION_INDUSTRY_V1",source_claim_id=row["source_claim_id"],lineage={"source_table":"organization_industry_assignments","source_column":"industry_node_id","source_value":row["industry_node_id"],"assignment_basis":row["assignment_basis"]}))

    # Document purpose and evidence grade are source-aware, not a blind document_type mapping.
    purpose_terms = {r["term_code"]:(r["classification_scheme_id"],r["classification_term_id"]) for r in _rows(conn, """SELECT t.term_code,t.classification_scheme_id,t.classification_term_id FROM classification_terms t JOIN classification_schemes s USING(classification_scheme_id) WHERE s.scheme_code='DOCUMENT_PURPOSE'""")}
    evidence_terms = {r["term_code"]:(r["classification_scheme_id"],r["classification_term_id"]) for r in _rows(conn, """SELECT t.term_code,t.classification_scheme_id,t.classification_term_id FROM classification_terms t JOIN classification_schemes s USING(classification_scheme_id) WHERE s.scheme_code='EVIDENCE_GRADE'""")}
    for row in _rows(conn, """SELECT d.document_id,d.document_type,s.source_code FROM source_documents d LEFT JOIN collection_sources s ON s.source_id=d.source_id ORDER BY d.document_id"""):
        purpose = DOCUMENT_PURPOSE_BY_SOURCE.get(row["source_code"]) or DOCUMENT_PURPOSE_BY_TYPE.get(row["document_type"])
        if purpose in purpose_terms:
            sid,tid=purpose_terms[purpose]
            assignments.append(dict(target_kind="DOCUMENT",target_id=row["document_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="DOCUMENT_PURPOSE_SOURCE_V1",lineage={"source_table":"source_documents","source_columns":["source_id","document_type"],"source_code":row["source_code"],"document_type":row["document_type"]}))
        grade = "OFFICIAL_DIRECT" if row["source_code"] in OFFICIAL_SOURCE_CODES or row["document_type"] in {"BID_NOTICE","NOTICE","PRESS_RELEASE"} else "MEDIA_DIRECT"
        sid,tid=evidence_terms[grade]
        assignments.append(dict(target_kind="DOCUMENT",target_id=row["document_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="DOCUMENT_EVIDENCE_SOURCE_V1",evidence_status="DIRECT_OFFICIAL" if grade=="OFFICIAL_DIRECT" else "MEDIA_DIRECT",lineage={"source_table":"source_documents","source_columns":["source_id","document_type"],"source_code":row["source_code"],"document_type":row["document_type"]}))

    market_terms = {r["term_code"]:(r["classification_scheme_id"],r["classification_term_id"]) for r in _rows(conn, """SELECT t.term_code,t.classification_scheme_id,t.classification_term_id FROM classification_terms t JOIN classification_schemes s USING(classification_scheme_id) WHERE s.scheme_code='MARKET_CATEGORY'""")}
    for row in _rows(conn, "SELECT sale_process_id,source_claim_id FROM sale_processes ORDER BY sale_process_id"):
        sid,tid=market_terms["SALE"]
        assignments.append(dict(target_kind="SALE_PROCESS",target_id=row["sale_process_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="SALE_PROCESS_V1",source_claim_id=row["source_claim_id"],lineage={"source_table":"sale_processes","source_column":"sale_process_id"}))
    for row in _rows(conn, "SELECT mandate_id,source_claim_id FROM lp_mandates ORDER BY mandate_id"):
        sid,tid=market_terms["LP_MANDATE"]
        assignments.append(dict(target_kind="LP_MANDATE",target_id=row["mandate_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="LP_MANDATE_V1",source_claim_id=row["source_claim_id"],lineage={"source_table":"lp_mandates","source_column":"mandate_id"}))
    strategy_terms = {r["term_code"]:(r["classification_scheme_id"],r["classification_term_id"]) for r in _rows(conn, """SELECT t.term_code,t.classification_scheme_id,t.classification_term_id FROM classification_terms t JOIN classification_schemes s USING(classification_scheme_id) WHERE s.scheme_code='INVESTMENT_STRATEGY'""")}
    for row in _rows(conn, """SELECT mandate_id,strategy_code,min(track_code) AS first_track,min(source_claim_id) AS source_claim_id
      FROM lp_mandate_tracks GROUP BY mandate_id,strategy_code ORDER BY mandate_id,first_track,strategy_code"""):
        if row["strategy_code"] not in strategy_terms:
            sid,tid,created=_upsert_term(conn,"INVESTMENT_STRATEGY",row["strategy_code"],row["strategy_code"].replace("_"," ").title())
            stats["terms_created"]+=int(created); strategy_terms[row["strategy_code"]]=(sid,tid)
        sid,tid=strategy_terms[row["strategy_code"]]
        assignments.append(dict(target_kind="LP_MANDATE",target_id=row["mandate_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="LP_TRACK_STRATEGY_V1",source_claim_id=row["source_claim_id"],lineage={"source_table":"lp_mandate_tracks","source_column":"strategy_code","source_value":row["strategy_code"]}))

    # Compact historical rows remain classifiable even when detailed active rows are retired.
    for row in _rows(conn, "SELECT record_kind,record_id,category_code,source_document_version_id FROM archived_serving_index ORDER BY record_kind,record_id"):
        code=archived_market_code(row["record_kind"],row["category_code"])
        if not code:
            continue
        if code not in market_terms:
            sid,tid,created=_upsert_term(conn,"MARKET_CATEGORY",code,code.replace("_"," ").title())
            stats["terms_created"]+=int(created);market_terms[code]=(sid,tid)
        sid,tid=market_terms[code]
        assignments.append(dict(target_kind=row["record_kind"],target_id=row["record_id"],classification_scheme_id=sid,classification_term_id=tid,assignment_role="LEGACY_BACKFILL",is_primary=True,classifier_version="ARCHIVED_MARKET_CATEGORY_V2",source_document_version_id=row["source_document_version_id"],evidence_locator=f'archived_serving_index:{row["record_kind"]}:{row["record_id"]}',lineage={"source_table":"archived_serving_index","source_column":"category_code","source_value":row["category_code"],"kind_aware_mapping":True}))

    stats["assignments_planned"] = len(assignments)
    for item in assignments:
        stats["assignments_inserted"] += int(_insert_assignment(conn,item,occupied_primary))
    stats["assignments_existing"] = stats["assignments_planned"] - stats["assignments_inserted"]
    result = dict(sorted(stats.items()))
    if apply and commit:
        conn.commit()
    elif not apply:
        conn.rollback()
    return result


def classification_qa(conn: Any) -> dict[str, Any]:
    by_scheme_target = _rows(conn, """SELECT s.scheme_code,r.target_kind,count(*) AS assignment_count,
      sum(CASE WHEN r.is_primary=1 THEN 1 ELSE 0 END) AS primary_count
      FROM record_classifications r JOIN classification_schemes s USING(classification_scheme_id)
      WHERE r.review_status NOT IN ('REJECTED','SUPERSEDED') AND r.valid_to IS NULL
      GROUP BY s.scheme_code,r.target_kind ORDER BY s.scheme_code,r.target_kind""")
    targets = [
      ("DOCUMENT","source_documents"), ("EVENT","events"), ("ASSET","assets"),
      ("ORGANIZATION","organizations"), ("LP_MANDATE","lp_mandates"),
      ("SALE_PROCESS","sale_processes"),
    ]
    coverage: dict[str, Any] = {}
    for kind, table in targets:
        total = _rows(conn, f"SELECT count(*) AS n FROM {table}")[0]["n"]
        classified = _rows(conn, """SELECT count(DISTINCT target_id) AS n FROM record_classifications
          WHERE target_kind=? AND review_status NOT IN ('REJECTED','SUPERSEDED') AND valid_to IS NULL""", (kind,))[0]["n"]
        coverage[kind] = {"total": total, "classified": classified, "unclassified": total-classified}
    primary_conflicts = _rows(conn, """SELECT count(*) AS n FROM (
      SELECT target_kind,target_id,classification_scheme_id
      FROM record_classifications
      WHERE is_primary=1 AND valid_to IS NULL AND review_status IN ('UNREVIEWED','PENDING','APPROVED')
      GROUP BY target_kind,target_id,classification_scheme_id HAVING count(*)>1
    ) conflicts""")[0]["n"]
    return {"by_scheme_target": by_scheme_target, "coverage": coverage, "primary_conflicts": primary_conflicts}


def _load_env(path: Path) -> dict[str,str]:
    values={}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        text=raw.strip()
        if text and not text.startswith("#") and "=" in text:
            k,v=text.split("=",1);values[k.strip()]=v.strip().strip("\"'")
    return values


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--sqlite",type=Path)
    parser.add_argument("--supabase",action="store_true")
    parser.add_argument("--env-file",type=Path,default=DEFAULT_ENV)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    if args.supabase and args.sqlite:
        parser.error("choose one target")
    if args.supabase:
        import psycopg
        env=_load_env(args.env_file);dsn=env.get("SUPABASE_DB_URL") or env.get("DATABASE_URL")
        if not dsn: raise RuntimeError("missing SUPABASE_DB_URL or DATABASE_URL")
        conn=psycopg.connect(dsn)
    else:
        path=(args.sqlite or DEFAULT_DB).resolve()
        conn=sqlite3.connect(path);conn.execute("PRAGMA foreign_keys=ON")
    try:
        result=backfill_classifications(conn,apply=args.apply)
        payload={"status":"applied" if args.apply else "dry_run","result":result}
        if args.apply:
            payload["qa"] = classification_qa(conn)
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(payload,ensure_ascii=False,indent=2))
    finally:
        conn.close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
