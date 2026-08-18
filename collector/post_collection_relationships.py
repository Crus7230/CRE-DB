from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_VERSION = "post-collection-relationships-v1"


@dataclass(frozen=True)
class RelationshipResult:
    relationship_run_id: str
    resolved_mentions: int = 0
    ambiguous_mentions: int = 0
    event_participants_created: int = 0
    occupancies_created: int = 0
    business_activities_created: int = 0
    unresolved_mentions: int = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def normalize_entity_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def _in_scope_sql(alias: str, collection_run_id: str | None) -> tuple[str, tuple[str, ...]]:
    if collection_run_id is None:
        return "1=1", ()
    return (
        f"EXISTS (SELECT 1 FROM extraction_runs er_scope "
        f"JOIN run_documents rd_scope ON rd_scope.document_version_id=er_scope.document_version_id "
        f"WHERE er_scope.extraction_run_id={alias}.extraction_run_id AND rd_scope.run_id=?)",
        (collection_run_id,),
    )


def _insert_review_task(
    con: sqlite3.Connection,
    *,
    target_kind: str,
    target_id: str,
    review_type: str,
    reason_code: str,
    payload: dict,
    priority: int = 2,
) -> int:
    exists = con.execute(
        """SELECT 1 FROM review_tasks
             WHERE target_kind=? AND target_id=? AND review_type=?
               AND status_code IN ('PENDING','IN_PROGRESS','CHANGES_REQUESTED')
             LIMIT 1""",
        (target_kind, target_id, review_type),
    ).fetchone()
    if exists:
        return 0
    task_id = "review_" + uuid.uuid4().hex
    cur = con.execute(
        """INSERT OR IGNORE INTO review_tasks(
               review_task_id,target_kind,target_id,review_type,status_code,
               priority,reason_code,payload_json
           ) VALUES(?,?,?,?,'PENDING',?,?,?)""",
        (task_id, target_kind, target_id, review_type, priority, reason_code,
         json.dumps(payload, ensure_ascii=False, sort_keys=True)),
    )
    return cur.rowcount


def _close_open_review_tasks(
    con: sqlite3.Connection,
    *,
    target_kind: str,
    target_id: str,
    review_type: str,
    note: str,
) -> int:
    cur = con.execute(
        """UPDATE review_tasks
              SET status_code='APPROVED', completed_at=?, decision_note=?
            WHERE target_kind=? AND target_id=? AND review_type=?
              AND status_code IN ('PENDING','IN_PROGRESS','CHANGES_REQUESTED')""",
        (_utc_now(), note, target_kind, target_id, review_type),
    )
    return cur.rowcount


def _verification_meets_rule_sql(claim_alias: str = "c", rule_alias: str = "r") -> str:
    return (
        f"(({rule_alias}.minimum_verification_status='VERIFIED' AND {claim_alias}.verification_status='VERIFIED') OR "
        f"({rule_alias}.minimum_verification_status='PENDING' AND {claim_alias}.verification_status IN ('VERIFIED','PENDING')) OR "
        f"({rule_alias}.minimum_verification_status='UNVERIFIED' AND {claim_alias}.verification_status IN ('VERIFIED','PENDING','UNVERIFIED')))"
    )


def _resolve_organization_mentions(
    con: sqlite3.Connection,
    collection_run_id: str | None,
) -> tuple[int, int, int]:
    con.execute(
        """UPDATE review_tasks SET status_code='APPROVED',completed_at=?,
                   decision_note='AUTO_CLOSED_SELECTED_RESOLUTION'
             WHERE review_type='ORGANIZATION_RESOLUTION_REVIEW'
               AND status_code IN ('PENDING','IN_PROGRESS','CHANGES_REQUESTED')
               AND EXISTS (SELECT 1 FROM mention_resolutions mr
                            WHERE mr.mention_id=review_tasks.target_id AND mr.selected=1)""",
        (_utc_now(),),
    )
    candidates: dict[str, dict[str, str]] = {}
    for organization_id, canonical_name in con.execute(
        "SELECT organization_id,canonical_name FROM organizations WHERE status_code='ACTIVE'"
    ):
        key = normalize_entity_name(canonical_name)
        if key:
            candidates.setdefault(key, {})[organization_id] = canonical_name
    for organization_id, alias_text, normalized_alias in con.execute(
        """SELECT oa.organization_id,oa.alias_text,oa.normalized_alias
             FROM organization_aliases oa
             JOIN organizations o ON o.organization_id=oa.organization_id
            WHERE o.status_code='ACTIVE'"""
    ):
        key = normalize_entity_name(normalized_alias or alias_text)
        if key:
            candidates.setdefault(key, {})[organization_id] = alias_text

    scope_sql, params = _in_scope_sql("m", collection_run_id)
    mentions = con.execute(
        f"""SELECT m.mention_id,m.surface_text,m.normalized_text
               FROM mentions m
              WHERE m.mention_type='ORGANIZATION'
                AND m.review_status<>'REJECTED'
                AND {scope_sql}
                AND NOT EXISTS (
                    SELECT 1 FROM mention_resolutions mr
                     WHERE mr.mention_id=m.mention_id AND mr.selected=1
                )""",
        params,
    ).fetchall()

    resolved = 0
    ambiguous = 0
    for mention_id, surface_text, normalized_text in mentions:
        key = normalize_entity_name(normalized_text or surface_text)
        matches = candidates.get(key, {})
        if len(matches) == 1:
            organization_id = next(iter(matches))
            resolution_id = _stable_id("resolution", mention_id, organization_id, "selected")
            cur = con.execute(
                """INSERT OR IGNORE INTO mention_resolutions(
                       mention_resolution_id,mention_id,target_kind,organization_id,
                       resolution_status,match_score,match_features_json,method_code,selected
                   ) VALUES(?,?,'ORGANIZATION',?,'RESOLVED',1.0,?,'ALIAS',1)""",
                (resolution_id, mention_id, organization_id,
                 json.dumps({"normalized_key": key, "match": "unique_exact_name_or_alias"}, ensure_ascii=False)),
            )
            resolved += cur.rowcount
            _close_open_review_tasks(
                con, target_kind="MENTION", target_id=mention_id,
                review_type="ORGANIZATION_RESOLUTION_REVIEW",
                note="AUTO_CLOSED_UNIQUE_EXACT_RESOLUTION",
            )
        elif len(matches) > 1:
            inserted_any = False
            for organization_id, matched_name in sorted(matches.items()):
                resolution_id = _stable_id("resolution", mention_id, organization_id, "ambiguous")
                cur = con.execute(
                    """INSERT OR IGNORE INTO mention_resolutions(
                           mention_resolution_id,mention_id,target_kind,organization_id,
                           resolution_status,match_score,match_features_json,method_code,selected
                       ) VALUES(?,?,'ORGANIZATION',?,'AMBIGUOUS',0.75,?,'ALIAS',0)""",
                    (resolution_id, mention_id, organization_id,
                     json.dumps({"normalized_key": key, "matched_name": matched_name}, ensure_ascii=False)),
                )
                inserted_any = inserted_any or bool(cur.rowcount)
            if inserted_any:
                ambiguous += 1
            _insert_review_task(
                con,
                target_kind="MENTION",
                target_id=mention_id,
                review_type="ORGANIZATION_RESOLUTION_REVIEW",
                reason_code="AMBIGUOUS_EXACT_ALIAS",
                payload={"surface_text": surface_text, "normalized_key": key,
                         "candidate_organization_ids": sorted(matches)},
                priority=2,
            )

    unresolved = con.execute(
        f"""SELECT COUNT(*) FROM mentions m
              WHERE m.mention_type='ORGANIZATION' AND m.review_status<>'REJECTED'
                AND {scope_sql}
                AND NOT EXISTS (
                    SELECT 1 FROM mention_resolutions mr
                     WHERE mr.mention_id=m.mention_id AND mr.selected=1
                )""",
        params,
    ).fetchone()[0]
    return resolved, ambiguous, unresolved


def _promote_event_participants(con: sqlite3.Connection, collection_run_id: str | None) -> int:
    scope_sql, params = _in_scope_sql("em", collection_run_id)
    verification_sql = _verification_meets_rule_sql()
    rows = con.execute(
        f"""SELECT DISTINCT eml.event_id,ca.organization_id,r.participant_role_code,
                           c.claim_id,c.confidence,c.date_start,c.date_end,c.verification_status
              FROM claims c
              JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
              JOIN event_mention_links eml ON eml.event_mention_id=em.event_mention_id
                                          AND eml.relation_code IN ('PRIMARY','SUPPORTING')
              JOIN claim_arguments ca ON ca.claim_id=c.claim_id
              JOIN predicate_relationship_rules r
                ON r.predicate_code=c.predicate_code
               AND r.claim_role_code=ca.role_code
               AND r.target_relation='EVENT_PARTICIPANT'
               AND r.auto_apply=1
             WHERE c.review_status='ACCEPTED'
               AND {verification_sql}
               AND ca.argument_kind='ENTITY' AND ca.organization_id IS NOT NULL
               AND {scope_sql}""",
        params,
    ).fetchall()
    created = 0
    for event_id, organization_id, role_code, claim_id, confidence, valid_from, valid_to, _ in rows:
        cur = con.execute(
            """INSERT OR IGNORE INTO event_participants(
                   event_id,organization_id,role_code,valid_from,valid_to,confidence,supporting_claim_id
               ) VALUES(?,?,?,?,?,?,?)""",
            (event_id, organization_id, role_code, valid_from, valid_to, confidence, claim_id),
        )
        created += cur.rowcount

    pending_rows = con.execute(
        f"""SELECT DISTINCT c.claim_id,c.verification_status,ca.role_code,ca.organization_id
              FROM claims c
              JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
              JOIN claim_arguments ca ON ca.claim_id=c.claim_id
              JOIN predicate_relationship_rules r
                ON r.predicate_code=c.predicate_code AND r.claim_role_code=ca.role_code
               AND r.target_relation='EVENT_PARTICIPANT' AND r.auto_apply=1
             WHERE c.review_status IN ('ACCEPTED','UNREVIEWED')
               AND NOT {verification_sql}
               AND ca.argument_kind='ENTITY' AND ca.organization_id IS NOT NULL
               AND {scope_sql}""",
        params,
    ).fetchall()
    for claim_id, verification_status, role_code, organization_id in pending_rows:
        _insert_review_task(
            con, target_kind="CLAIM", target_id=claim_id,
            review_type="RELATION_PROMOTION_REVIEW",
            reason_code="RELATION_CLAIM_NOT_VERIFIED",
            payload={"role_code": role_code, "organization_id": organization_id,
                     "verification_status": verification_status},
            priority=2,
        )
    return created


def _occupancy_status(stage_code: str | None) -> str:
    return {
        "LEASE_MARKETING": "REPORTED",
        "LEASE_NEGOTIATING": "NEGOTIATING",
        "LEASE_SIGNED": "CONTRACTED",
        "TENANT_OCCUPIED": "OCCUPIED",
        "RELOCATION_REPORTED": "REPORTED",
        "RELOCATION_ANNOUNCED": "PLANNED",
        "RELOCATION_SITE_SELECTED": "PLANNED",
        "RELOCATION_CONTRACTED": "CONTRACTED",
        "RELOCATION_COMPLETED": "OCCUPIED",
        "RELOCATION_CANCELLED": "CANCELLED",
    }.get(stage_code, "UNKNOWN")


def _revoke_invalid_derived_relations(
    con: sqlite3.Connection,
    collection_run_id: str | None,
) -> None:
    scope_sql, params = _in_scope_sql("em", collection_run_id)
    verification_sql = _verification_meets_rule_sql()
    invalid_claims = con.execute(
        f"""SELECT DISTINCT c.claim_id,c.verification_status
              FROM claims c
              JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
              JOIN claim_arguments ca ON ca.claim_id=c.claim_id
              JOIN predicate_relationship_rules r
                ON r.predicate_code=c.predicate_code AND r.claim_role_code=ca.role_code
               AND r.auto_apply=1
             WHERE (c.review_status<>'ACCEPTED' OR NOT {verification_sql})
               AND {scope_sql}""",
        params,
    ).fetchall()
    for claim_id, verification_status in invalid_claims:
        con.execute("DELETE FROM event_participants WHERE supporting_claim_id=?", (claim_id,))
        con.execute(
            """UPDATE organization_property_occupancies
                  SET review_status='SUPERSEDED',
                      verification_status=CASE WHEN ? IN ('CONTRADICTED','INCONCLUSIVE') THEN ? ELSE 'UNVERIFIED' END
                WHERE source_claim_id=? AND review_status<>'SUPERSEDED'""",
            (verification_status, verification_status, claim_id),
        )
        con.execute(
            """UPDATE organization_business_activities
                  SET review_status='SUPERSEDED',
                      verification_status=CASE WHEN ? IN ('CONTRADICTED','INCONCLUSIVE') THEN ? ELSE 'UNVERIFIED' END
                WHERE source_claim_id=? AND review_status<>'SUPERSEDED'""",
            (verification_status, verification_status, claim_id),
        )
    con.execute(
        """UPDATE review_tasks SET status_code='APPROVED',completed_at=?,
                   decision_note='AUTO_CLOSED_RELATION_CONDITION_CLEARED'
             WHERE review_type IN ('RELATION_PROMOTION_REVIEW','PROPERTY_RELATION_REVIEW',
                                   'BUSINESS_ACTIVITY_RELATION_REVIEW')
               AND status_code IN ('PENDING','IN_PROGRESS','CHANGES_REQUESTED')
               AND ((target_kind='CLAIM' AND (
                       EXISTS (SELECT 1 FROM claims c WHERE c.claim_id=review_tasks.target_id AND c.review_status<>'ACCEPTED')
                       OR EXISTS (SELECT 1 FROM event_participants ep WHERE ep.supporting_claim_id=review_tasks.target_id)
                       OR EXISTS (SELECT 1 FROM organization_business_activities ba
                                   WHERE ba.source_claim_id=review_tasks.target_id AND ba.review_status<>'SUPERSEDED')
                    )) OR (target_kind='EVENT' AND (
                       EXISTS (SELECT 1 FROM event_assets ea WHERE ea.event_id=review_tasks.target_id)
                       OR EXISTS (SELECT 1 FROM event_projects ep WHERE ep.event_id=review_tasks.target_id)
                    )))""",
        (_utc_now(),),
    )


def _materialize_occupancies(con: sqlite3.Connection, collection_run_id: str | None) -> int:
    scope_sql, params = _in_scope_sql("em", collection_run_id)
    rows = con.execute(
        f"""SELECT ep.organization_id,e.event_id,e.current_stage_code,e.event_date_start,
                  ep.supporting_claim_id,ep.confidence,c.verification_status,
                  (SELECT ea.asset_id FROM event_assets ea WHERE ea.event_id=e.event_id
                    ORDER BY CASE ea.role_code WHEN 'LEASED_ASSET' THEN 0 WHEN 'SUBJECT' THEN 1 ELSE 2 END LIMIT 1) asset_id,
                  (SELECT ej.project_id FROM event_projects ej WHERE ej.event_id=e.event_id
                    ORDER BY CASE ej.role_code WHEN 'SUBJECT' THEN 0 ELSE 1 END LIMIT 1) project_id
             FROM event_participants ep
             JOIN claims c ON c.claim_id=ep.supporting_claim_id
             JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
             JOIN events e ON e.event_id=ep.event_id
             JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
            WHERE ep.role_code='TENANT'
              AND ep.supporting_claim_id IS NOT NULL
              AND ec.code IN ('LEASE','CORPORATE_RELOCATION')
              AND e.lifecycle_status<>'MERGED'
              AND {scope_sql}""",
        params,
    ).fetchall()
    created = 0
    for organization_id, event_id, stage_code, event_date, claim_id, confidence, claim_verification, asset_id, project_id in rows:
        if asset_id is None and project_id is None:
            _insert_review_task(
                con, target_kind="EVENT", target_id=event_id,
                review_type="PROPERTY_RELATION_REVIEW",
                reason_code="TENANT_EVENT_WITHOUT_PLACE",
                payload={"organization_id": organization_id, "supporting_claim_id": claim_id},
                priority=2,
            )
            continue
        exists = con.execute(
            """SELECT 1 FROM organization_property_occupancies
                 WHERE organization_id=? AND event_id=? AND source_claim_id=?
                   AND coalesce(asset_id,'')=coalesce(?,'')
                   AND coalesce(project_id,'')=coalesce(?,'') LIMIT 1""",
            (organization_id, event_id, claim_id, asset_id, project_id),
        ).fetchone()
        if exists:
            continue
        occupancy_id = _stable_id("occupancy", organization_id, event_id, claim_id,
                                  asset_id or "", project_id or "")
        con.execute(
            """INSERT INTO organization_property_occupancies(
                   occupancy_id,organization_id,asset_id,project_id,occupancy_type,tenure_type,
                   occupancy_status,valid_from,event_id,source_claim_id,verification_status,
                   review_status,confidence,metadata_json
               ) VALUES(?,?,?,?, 'UNKNOWN','TENANT',?,?,?,?, ?,?,?,?)""",
            (occupancy_id, organization_id, asset_id, project_id,
             _occupancy_status(stage_code), event_date, event_id, claim_id,
             claim_verification, 'APPROVED' if claim_verification == 'VERIFIED' else 'PENDING',
             confidence or 1.0,
             json.dumps({"derived_by": PIPELINE_VERSION, "stage_code": stage_code}, sort_keys=True)),
        )
        created += 1
    return created


def _materialize_business_activities(
    con: sqlite3.Connection,
    collection_run_id: str | None,
) -> int:
    scope_sql, params = _in_scope_sql("em", collection_run_id)
    verification_sql = _verification_meets_rule_sql()
    rows = con.execute(
        f"""SELECT DISTINCT c.claim_id,ca.organization_id,
                           coalesce(c.text_value,c.raw_value) activity_name,
                           coalesce(c.valid_time_start,c.date_start) valid_from,
                           c.valid_time_end,c.confidence,c.verification_status
              FROM claims c
              JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
              JOIN claim_arguments ca ON ca.claim_id=c.claim_id
              JOIN predicate_relationship_rules r
                ON r.predicate_code=c.predicate_code
               AND r.claim_role_code=ca.role_code
               AND r.target_relation='BUSINESS_ACTIVITY'
               AND r.auto_apply=1
             WHERE c.review_status='ACCEPTED'
               AND {verification_sql}
               AND ca.argument_kind='ENTITY' AND ca.organization_id IS NOT NULL
               AND {scope_sql}""",
        params,
    ).fetchall()
    created = 0
    for claim_id, organization_id, activity_name, valid_from, valid_to, confidence, claim_verification in rows:
        if not valid_from:
            _insert_review_task(
                con, target_kind="CLAIM", target_id=claim_id,
                review_type="BUSINESS_ACTIVITY_RELATION_REVIEW",
                reason_code="BUSINESS_ACTIVITY_DATE_REQUIRED",
                payload={"organization_id": organization_id, "activity_name": activity_name},
                priority=2,
            )
            continue
        activity_code = "BUSINESS_DOMAIN_" + hashlib.sha256(
            normalize_entity_name(activity_name).encode("utf-8")
        ).hexdigest()[:16]
        activity_id = _stable_id("business-activity", organization_id, activity_code, valid_from)
        cur = con.execute(
            """INSERT OR IGNORE INTO organization_business_activities(
                   organization_business_activity_id,organization_id,activity_code,
                   activity_name,activity_importance,valid_from,valid_to,source_claim_id,
                   verification_status,review_status,metadata_json
               ) VALUES(?,?,?,?,'UNKNOWN',?,?,?,?,?,?)""",
            (activity_id, organization_id, activity_code, activity_name, valid_from,
             valid_to, claim_id, claim_verification,
             'APPROVED' if claim_verification == 'VERIFIED' else 'PENDING',
             json.dumps({"derived_by": PIPELINE_VERSION, "confidence": confidence}, sort_keys=True)),
        )
        created += cur.rowcount
    return created


def reconcile_relationships(
    db_path: str | Path,
    *,
    collection_run_id: str | None = None,
    allow_live: bool = False,
) -> RelationshipResult:
    path = Path(db_path)
    if path.name == "market.db" and not allow_live:
        raise PermissionError("live market.db requires allow_live=True")
    relationship_run_id = "relationship-run_" + uuid.uuid4().hex
    started_at = _utc_now()
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """INSERT INTO relationship_resolution_runs(
                   relationship_run_id,collection_run_id,scope_code,pipeline_version,started_at,status_code
               ) VALUES(?,?,?,?,?,'RUNNING')""",
            (relationship_run_id, collection_run_id,
             "COLLECTION_RUN" if collection_run_id else "ALL_EXISTING",
             PIPELINE_VERSION, started_at),
        )
        _revoke_invalid_derived_relations(con, collection_run_id)
        resolved, ambiguous, unresolved = _resolve_organization_mentions(con, collection_run_id)
        participants = _promote_event_participants(con, collection_run_id)
        occupancies = _materialize_occupancies(con, collection_run_id)
        business_activities = _materialize_business_activities(con, collection_run_id)
        completed_at = _utc_now()
        con.execute(
            """UPDATE relationship_resolution_runs SET
                   completed_at=?,status_code='COMPLETED',resolved_mentions=?,ambiguous_mentions=?,
                   event_participants_created=?,occupancies_created=?,business_activities_created=?,
                   unresolved_mentions=?
                 WHERE relationship_run_id=?""",
            (completed_at, resolved, ambiguous, participants, occupancies, business_activities,
             unresolved, relationship_run_id),
        )
        con.commit()
        return RelationshipResult(relationship_run_id, resolved, ambiguous, participants,
                                  occupancies, business_activities, unresolved)
    except Exception as exc:
        con.rollback()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                """INSERT INTO relationship_resolution_runs(
                       relationship_run_id,collection_run_id,scope_code,pipeline_version,
                       started_at,completed_at,status_code,error_message,metadata_json
                   ) VALUES(?,?,?,?,?,?,'FAILED',?,?)""",
                (relationship_run_id, collection_run_id,
                 "COLLECTION_RUN" if collection_run_id else "ALL_EXISTING",
                 PIPELINE_VERSION, started_at, _utc_now(), str(exc),
                 json.dumps({"error_type": type(exc).__name__},
                            ensure_ascii=False, sort_keys=True)),
            )
            con.commit()
        except Exception:
            con.rollback()
        raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run post-collection relationship reconciliation")
    parser.add_argument("db")
    parser.add_argument("--collection-run-id")
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    result = reconcile_relationships(args.db, collection_run_id=args.collection_run_id,
                                     allow_live=args.allow_live)
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
