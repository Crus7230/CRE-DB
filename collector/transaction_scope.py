from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

from collector.post_collection_relationships import reconcile_relationships
import uuid


RESIDENTIAL_USE_TOKENS = (
    "아파트",
    "공동주택",
    "단독주택",
    "다가구",
    "다세대",
    "연립",
    "주택",
    "주거",
)
AUTO_EXCLUDE_MAX_AREA_M2 = Decimal("1000")
REVIEW_MAX_AREA_M2 = Decimal("3300")
TRANSACTION_GROUP_FIELDS = (
    "sggCd",
    "umdNm",
    "jibun",
    "dealYear",
    "dealMonth",
    "dealDay",
    "dealAmount",
    "buyerGbn",
    "slerGbn",
    "dealingGbn",
    "buildYear",
    "buildingType",
)
POLICY_CODE = "MOLIT_SCOPE_TIERED_V2"


@dataclass(frozen=True)
class ScopeDecision:
    status: str
    reason_code: str | None
    building_use: str
    building_area_m2: Decimal | None


def classify_molit_transaction_scope(
    record: dict,
    *,
    auto_exclude_max_area_m2: Decimal = AUTO_EXCLUDE_MAX_AREA_M2,
    review_max_area_m2: Decimal = REVIEW_MAX_AREA_M2,
) -> ScopeDecision:
    building_use = str(record.get("buildingUse") or "").strip()
    if any(token in building_use for token in RESIDENTIAL_USE_TOKENS):
        return ScopeDecision(
            status="EXCLUDED",
            reason_code="OUT_OF_SCOPE_RESIDENTIAL_USE",
            building_use=building_use,
            building_area_m2=None,
        )
    try:
        raw_area = record.get("buildingAr")
        if raw_area is None or str(raw_area).strip() == "":
            raise InvalidOperation
        area = Decimal(str(raw_area).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return ScopeDecision(
            status="EXCLUDED",
            reason_code="OUT_OF_SCOPE_AREA_MISSING",
            building_use=building_use,
            building_area_m2=None,
        )
    if area <= auto_exclude_max_area_m2:
        return ScopeDecision(
            status="EXCLUDED",
            reason_code="OUT_OF_SCOPE_AREA_LE_1000_M2",
            building_use=building_use,
            building_area_m2=area,
        )
    if area <= review_max_area_m2:
        return ScopeDecision(
            status="REVIEW_REQUIRED",
            reason_code="SCOPE_REVIEW_AREA_1000_3300_M2",
            building_use=building_use,
            building_area_m2=area,
        )
    return ScopeDecision(
        status="IN_SCOPE",
        reason_code=None,
        building_use=building_use,
        building_area_m2=area,
    )


def transaction_group_key(record: dict) -> str:
    values = [str(record.get(field) or "").strip() for field in TRANSACTION_GROUP_FIELDS]
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ScopeApplicationResult:
    evaluated: int
    in_scope: int
    review_area: int
    review_group_count: int
    review_group_rows: int
    excluded_residential: int
    excluded_small_area: int
    excluded_missing_area: int
    mentions_updated: int
    review_tasks_inserted: int


def _stable_id(namespace: str, value: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"market-intel:{namespace}:{value}").hex


def apply_molit_transaction_scope(
    *,
    db_path: str | Path,
    auto_exclude_max_area_m2: Decimal = AUTO_EXCLUDE_MAX_AREA_M2,
    review_max_area_m2: Decimal = REVIEW_MAX_AREA_M2,
) -> ScopeApplicationResult:
    con = sqlite3.connect(str(db_path), timeout=30)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 30000")
    rows = con.execute(
        """SELECT v.document_version_id, v.metadata_json
           FROM document_versions v
           JOIN source_documents d ON d.document_id = v.document_id
           JOIN collection_sources s ON s.source_id = d.source_id
           WHERE s.source_code = 'MOLIT_REAL_TRANSACTION'
             AND v.version_no = (
               SELECT MAX(v2.version_no)
               FROM document_versions v2
               WHERE v2.document_id = v.document_id
             )"""
    ).fetchall()

    records: dict[str, dict] = {}
    decisions: dict[str, ScopeDecision] = {}
    groups: dict[str, list[str]] = defaultdict(list)
    for document_version_id, metadata_json in rows:
        record = json.loads(metadata_json).get("api_record", {})
        records[document_version_id] = record
        decision = classify_molit_transaction_scope(
            record,
            auto_exclude_max_area_m2=auto_exclude_max_area_m2,
            review_max_area_m2=review_max_area_m2,
        )
        decisions[document_version_id] = decision
        if decision.building_area_m2 is not None and decision.building_area_m2 <= review_max_area_m2:
            groups[transaction_group_key(record)].append(document_version_id)

    group_review: dict[str, tuple[str, Decimal, int]] = {}
    review_group_count = 0
    for group_key, version_ids in groups.items():
        if len(version_ids) <= 1:
            continue
        group_area = sum(
            (decisions[version_id].building_area_m2 or Decimal("0"))
            for version_id in version_ids
        )
        if group_area <= review_max_area_m2:
            continue
        review_group_count += 1
        for version_id in version_ids:
            if decisions[version_id].reason_code == "OUT_OF_SCOPE_RESIDENTIAL_USE":
                continue
            group_review[version_id] = (group_key, group_area, len(version_ids))

    counts = {
        "in_scope": 0,
        "review_area": 0,
        "review_group_count": review_group_count,
        "review_group_rows": len(group_review),
        "excluded_residential": 0,
        "excluded_small_area": 0,
        "excluded_missing_area": 0,
        "mentions_updated": 0,
        "review_tasks_inserted": 0,
    }
    decision_rows = []
    for version_id, decision in decisions.items():
        group = group_review.get(version_id)
        if group is not None:
            group_key, group_area, group_count = group
            scope_status = "REVIEW_REQUIRED"
            reason_code = "SCOPE_REVIEW_GROUP_SUM_GT_3300_M2"
            payload = {
                "policyCode": POLICY_CODE,
                "groupKey": json.loads(group_key),
                "groupAreaM2": str(group_area),
                "groupRowCount": group_count,
                "rowAreaM2": str(decision.building_area_m2),
            }
        else:
            scope_status = decision.status
            reason_code = decision.reason_code
            payload = {
                "policyCode": POLICY_CODE,
                "rowAreaM2": None if decision.building_area_m2 is None else str(decision.building_area_m2),
            }
        decision_rows.append(
            (version_id, scope_status, reason_code, json.dumps(payload, ensure_ascii=False))
        )
        if group is not None:
            continue
        if decision.status == "IN_SCOPE":
            counts["in_scope"] += 1
        elif decision.status == "REVIEW_REQUIRED":
            counts["review_area"] += 1
        elif decision.reason_code == "OUT_OF_SCOPE_RESIDENTIAL_USE":
            counts["excluded_residential"] += 1
        elif decision.reason_code == "OUT_OF_SCOPE_AREA_LE_1000_M2":
            counts["excluded_small_area"] += 1
        else:
            counts["excluded_missing_area"] += 1

    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """CREATE TEMP TABLE molit_scope_decisions(
                   document_version_id TEXT PRIMARY KEY,
                   scope_status TEXT NOT NULL,
                   reason_code TEXT,
                   payload_json TEXT NOT NULL
               ) WITHOUT ROWID"""
        )
        con.executemany(
            "INSERT INTO molit_scope_decisions VALUES (?, ?, ?, ?)", decision_rows
        )
        excluded_cursor = con.execute(
            """UPDATE event_mentions AS em
               SET status_code = 'REJECTED', rejection_code = sd.reason_code
               FROM extraction_runs AS er
               JOIN molit_scope_decisions AS sd
                 ON sd.document_version_id = er.document_version_id
               WHERE em.extraction_run_id = er.extraction_run_id
                 AND sd.scope_status = 'EXCLUDED'
                 AND em.status_code IN ('EXTRACTED','REJECTED','REVIEW_READY')
                 AND (em.status_code <> 'REJECTED' OR em.rejection_code IS NOT sd.reason_code)"""
        )
        in_scope_cursor = con.execute(
            """UPDATE event_mentions AS em
               SET status_code = 'EXTRACTED', rejection_code = NULL
               FROM extraction_runs AS er
               JOIN molit_scope_decisions AS sd
                 ON sd.document_version_id = er.document_version_id
               WHERE em.extraction_run_id = er.extraction_run_id
                 AND sd.scope_status = 'IN_SCOPE'
                 AND em.status_code IN ('EXTRACTED','REJECTED','REVIEW_READY')
                 AND (em.status_code <> 'EXTRACTED' OR em.rejection_code IS NOT NULL)"""
        )
        review_cursor = con.execute(
            """UPDATE event_mentions AS em
               SET status_code = 'REVIEW_READY', rejection_code = NULL
               FROM extraction_runs AS er
               JOIN molit_scope_decisions AS sd
                 ON sd.document_version_id = er.document_version_id
               WHERE em.extraction_run_id = er.extraction_run_id
                 AND sd.scope_status = 'REVIEW_REQUIRED'
                 AND em.status_code IN ('EXTRACTED','REJECTED','REVIEW_READY')
                 AND (em.status_code <> 'REVIEW_READY' OR em.rejection_code IS NOT NULL)"""
        )
        counts["mentions_updated"] = (
            excluded_cursor.rowcount + in_scope_cursor.rowcount + review_cursor.rowcount
        )

        review_mentions = con.execute(
            """SELECT em.event_mention_id, sd.reason_code, sd.payload_json
               FROM event_mentions em
               JOIN extraction_runs er ON er.extraction_run_id = em.extraction_run_id
               JOIN molit_scope_decisions sd ON sd.document_version_id = er.document_version_id
               WHERE sd.scope_status = 'REVIEW_REQUIRED'
                 AND em.status_code = 'REVIEW_READY'"""
        ).fetchall()
        con.execute(
            """UPDATE review_tasks SET status_code='APPROVED',
                       completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                       decision_note='AUTO_CLOSED_SCOPE_DECISION_CHANGED'
                 WHERE review_type='MOLIT_TRANSACTION_SCOPE'
                   AND status_code IN ('PENDING','IN_PROGRESS','CHANGES_REQUESTED')
                   AND NOT EXISTS (
                       SELECT 1 FROM event_mentions em
                       JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
                       JOIN molit_scope_decisions sd ON sd.document_version_id=er.document_version_id
                       WHERE em.event_mention_id=review_tasks.target_id
                         AND sd.scope_status='REVIEW_REQUIRED'
                         AND em.status_code='REVIEW_READY'
                   )"""
        )
        for mention_id, reason_code, payload_json in review_mentions:
            open_task = con.execute(
                """SELECT 1 FROM review_tasks WHERE target_kind='EVENT_MENTION'
                     AND target_id=? AND review_type='MOLIT_TRANSACTION_SCOPE'
                     AND status_code IN ('PENDING','IN_PROGRESS','CHANGES_REQUESTED')""",
                (mention_id,),
            ).fetchone()
            if open_task:
                continue
            task_id = "review-task_" + uuid.uuid4().hex
            cursor = con.execute(
                """INSERT OR IGNORE INTO review_tasks(
                       review_task_id, target_kind, target_id, review_type,
                       status_code, priority, reason_code, payload_json
                   ) VALUES (?, 'EVENT_MENTION', ?, 'MOLIT_TRANSACTION_SCOPE',
                             'PENDING', ?, ?, ?)""",
                (
                    task_id,
                    mention_id,
                    2 if reason_code == "SCOPE_REVIEW_GROUP_SUM_GT_3300_M2" else 3,
                    reason_code,
                    payload_json,
                ),
            )
            counts["review_tasks_inserted"] += cursor.rowcount
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    reconcile_relationships(db_path, allow_live=True)
    return ScopeApplicationResult(evaluated=len(rows), **counts)
