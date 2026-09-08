"""Import an explicitly approved, normalized sale-process manifest.

This module intentionally performs no NLP or Korean amount parsing.  Normalized
amounts and stable IDs must be supplied by a human-approved manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3

from collector.post_collection_relationships import reconcile_relationships
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
LIVE_DB_PATHS = {(ROOT / "data" / "market.db").resolve(), (ROOT / "db" / "market.db").resolve()}
DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
SOURCE_ID = "src_approved_sale_manifest"
RELATION_TYPES = {
    "RELAUNCHED_AS", "PREVIOUS_ATTEMPT", "SUCCESSOR_ATTEMPT",
    "PREFERRED_SWITCH_CONTINUATION", "PACKAGE_COMPONENT_OF",
    "STRUCTURE_CHANGED_TO", "DUPLICATE_OF", "OTHER",
}


class ManifestValidationError(ValueError):
    """Raised before import when an approved manifest violates its contract."""


@dataclass(frozen=True)
class ImportResult:
    manifest_id: str
    inserted_rows: int
    dry_run: bool


def _required(obj: Mapping[str, Any], key: str, path: str) -> Any:
    value = obj.get(key)
    if value is None or value == "":
        raise ManifestValidationError(f"{path}.{key} is required")
    return value


def _evidence_ids(record: Mapping[str, Any], path: str, source_ids: set[str]) -> list[str]:
    evidence = record.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ManifestValidationError(f"{path}.evidence is required")
    ids = evidence.get("source_ids")
    if not isinstance(ids, list) or not ids:
        raise ManifestValidationError(f"{path}.evidence.source_ids must be non-empty")
    unknown = set(ids) - source_ids
    if unknown:
        raise ManifestValidationError(f"{path} references unknown sources: {sorted(unknown)}")
    return ids


def _validate_amount(amount: Any, path: str) -> None:
    if amount is None:
        return
    if not isinstance(amount, Mapping):
        raise ManifestValidationError(f"{path} must be an object or null")
    kind = _required(amount, "kind", path)
    _required(amount, "raw_value", path)
    _required(amount, "currency", path)
    if kind not in {"EXACT", "APPROX", "RANGE", "AT_LEAST", "AT_MOST", "GREATER_THAN", "LESS_THAN", "UNKNOWN"}:
        raise ManifestValidationError(f"{path}.kind is invalid")
    if kind == "RANGE":
        for key in ("lower_decimal", "upper_decimal"):
            value = _required(amount, key, path)
            if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
                raise ManifestValidationError(f"{path}.{key} must be a normalized decimal string")
    elif kind != "UNKNOWN":
        value = amount.get("decimal")
        if value is None:
            raise ManifestValidationError(f"{path}.decimal is required for {kind}")
        if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
            raise ManifestValidationError(f"{path}.decimal must be a normalized decimal string")


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("manifest_version") != "1.0":
        raise ManifestValidationError("manifest_version must be 1.0")
    _required(manifest, "manifest_id", "manifest")
    if manifest.get("status") != "APPROVED":
        raise ManifestValidationError("status must be APPROVED")
    review = manifest.get("review")
    if not isinstance(review, Mapping):
        raise ManifestValidationError("review is required")
    for key in ("reviewed_by", "reviewed_at", "approved_by", "approved_at"):
        _required(review, key, "review")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ManifestValidationError("sources must be non-empty")
    source_ids: set[str] = set()
    for i, source in enumerate(sources):
        path = f"sources[{i}]"
        if not isinstance(source, Mapping):
            raise ManifestValidationError(f"{path} must be an object")
        source_id = _required(source, "id", path)
        if source_id in source_ids:
            raise ManifestValidationError(f"duplicate source id: {source_id}")
        source_ids.add(source_id)
        for key in ("url", "publisher", "document_type", "published_at", "accessed_at", "rights_status"):
            _required(source, key, path)

    for key in ("asset", "event", "process"):
        if not isinstance(manifest.get(key), Mapping):
            raise ManifestValidationError(f"{key} is required")
        _required(manifest[key], "id", key)
        _evidence_ids(manifest[key], key, source_ids)

    collections = ("organizations", "roles", "rounds", "participations", "participation_members", "submissions", "funding", "decisions", "milestones")
    for name in collections:
        records = manifest.get(name)
        if not isinstance(records, list):
            raise ManifestValidationError(f"{name} must be an array")
        seen: set[str] = set()
        for i, record in enumerate(records):
            path = f"{name}[{i}]"
            if not isinstance(record, Mapping):
                raise ManifestValidationError(f"{path} must be an object")
            record_id = _required(record, "id", path)
            if record_id in seen:
                raise ManifestValidationError(f"duplicate id in {name}: {record_id}")
            seen.add(record_id)
            _evidence_ids(record, path, source_ids)
            if name == "submissions":
                _required(record, "claim_id", path)
                _validate_amount(record.get("amount"), f"{path}.amount")

    relations = manifest.get("process_relations", [])
    if not isinstance(relations, list):
        raise ManifestValidationError("process_relations must be an array")
    seen_relations: set[str] = set()
    for i, record in enumerate(relations):
        path = f"process_relations[{i}]"
        if not isinstance(record, Mapping):
            raise ManifestValidationError(f"{path} must be an object")
        record_id = _required(record, "id", path)
        if record_id in seen_relations:
            raise ManifestValidationError(f"duplicate id in process_relations: {record_id}")
        seen_relations.add(record_id)
        from_id = _required(record, "from_sale_process_id", path)
        to_id = _required(record, "to_sale_process_id", path)
        if from_id == to_id:
            raise ManifestValidationError(f"{path} cannot relate a process to itself")
        if _required(record, "relation_type", path) not in RELATION_TYPES:
            raise ManifestValidationError(f"{path}.relation_type is invalid")
        _evidence_ids(record, path, source_ids)

    org_ids = {x["id"] for x in manifest["organizations"]}
    round_ids = {x["id"] for x in manifest["rounds"]}
    part_ids = {x["id"] for x in manifest["participations"]}
    submission_ids = {x["id"] for x in manifest["submissions"]}
    for i, row in enumerate(manifest["roles"]):
        if row.get("organization_id") not in org_ids:
            raise ManifestValidationError(f"roles[{i}].organization_id is unknown")
    for i, row in enumerate(manifest["participations"]):
        if row.get("round_id") not in round_ids or row.get("bidder_organization_id") not in org_ids:
            raise ManifestValidationError(f"participations[{i}] has an unknown round or organization")
    for i, row in enumerate(manifest["participation_members"]):
        if row.get("participation_id") not in part_ids or row.get("organization_id") not in org_ids:
            raise ManifestValidationError(f"participation_members[{i}] has an unknown participation or organization")
    for i, row in enumerate(manifest["submissions"]):
        if row.get("participation_id") not in part_ids:
            raise ManifestValidationError(f"submissions[{i}].participation_id is unknown")
    for i, row in enumerate(manifest["funding"]):
        if row.get("submission_id") not in submission_ids:
            raise ManifestValidationError(f"funding[{i}].submission_id is unknown")
        for key in ("provider_organization_id", "recipient_vehicle_id"):
            if row.get(key) is not None and row[key] not in org_ids:
                raise ManifestValidationError(f"funding[{i}].{key} is unknown")
    for i, row in enumerate(manifest["decisions"]):
        if row.get("round_id") is not None and row["round_id"] not in round_ids:
            raise ManifestValidationError(f"decisions[{i}].round_id is unknown")
        if row.get("participation_id") is not None and row["participation_id"] not in part_ids:
            raise ManifestValidationError(f"decisions[{i}].participation_id is unknown")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _metadata(manifest: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    return _json({
        "manifest_id": manifest["manifest_id"],
        "evidence": row["evidence"],
        "review": manifest["review"],
        "record_context": row.get("metadata", {}),
    })


def _entity_metadata(row: Mapping[str, Any]) -> str:
    """Canonical entity metadata must remain stable across manifests/attempts."""
    return _json(row.get("metadata", {}))


def _insert(con: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> None:
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    cur = con.execute(f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))
    if cur.rowcount:
        return
    # Idempotency is only valid when the stable ID points to the same content.
    # Never let INSERT OR IGNORE conceal a revised manifest or a uniqueness
    # collision with a different source/canonical entity.
    pk_columns = [
        name
        for _, name, _, _, _, pk_order in sorted(
            con.execute(f"PRAGMA table_info({table})").fetchall(),
            key=lambda item: item[5] or 999,
        )
        if pk_order
    ]
    if not pk_columns or any(key not in values for key in pk_columns):
        pk_columns = [next(iter(values))]
    where = " AND ".join(f"{key}=?" for key in pk_columns)
    row = con.execute(
        f"SELECT {columns} FROM {table} WHERE {where}",
        tuple(values[key] for key in pk_columns),
    ).fetchone()
    expected = tuple(values.values())
    if row is None or tuple(row) != expected:
        identity = ",".join(f"{key}={values[key]}" for key in pk_columns)
        raise ManifestValidationError(f"conflicting existing row in {table} for {identity}")


def _amount_fields(amount: Mapping[str, Any]) -> dict[str, Any]:
    kind = amount["kind"]
    comparator = {"APPROX": "ABOUT", "UNKNOWN": "UNKNOWN"}.get(kind, kind)
    precision = {"EXACT": "EXACT", "APPROX": "ROUNDED", "RANGE": "REPORTED_RANGE", "UNKNOWN": "UNKNOWN"}.get(kind, "RELATIVE_ONLY")
    return {
        "bid_amount_decimal": amount.get("decimal"), "currency_code": amount["currency"],
        "comparator_code": comparator, "amount_precision": precision,
        "lower_amount_decimal": amount.get("lower_decimal"), "upper_amount_decimal": amount.get("upper_decimal"),
        "price_basis": amount.get("price_basis", "UNKNOWN"), "vat_inclusion": amount.get("vat_inclusion", "UNKNOWN"),
        "debt_assumption": amount.get("debt_assumption", "UNKNOWN"),
    }


def _load_manifest(value: Path | str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return json.loads(Path(value).read_text(encoding="utf-8"))


def import_manifest(
    db_path: Path | str,
    manifest_value: Path | str | Mapping[str, Any],
    *,
    dry_run: bool = False,
    allow_live: bool = False,
) -> ImportResult:
    manifest = _load_manifest(manifest_value)
    validate_manifest(manifest)
    db = Path(db_path).resolve()
    if db in LIVE_DB_PATHS and not allow_live:
        raise ManifestValidationError(f"live database path is blocked: {db}")
    if not db.exists():
        raise ManifestValidationError(f"database does not exist: {db}")

    con = sqlite3.connect(db, timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    before = con.total_changes
    try:
        con.execute("BEGIN IMMEDIATE")
        version = con.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()
        if version is None or version[0] not in {"2.5.0", "2.6.0", "2.7.0", "2.8.0", "2.9.0", "3.0.0", "3.1.0", "3.2.0", "3.3.0", "3.4.0", "3.4.1", "3.5.0"}:
            raise ManifestValidationError("database schema_version must be a supported version from 2.5.0 through 3.5.0")
        approved_at = manifest["review"]["approved_at"]
        _insert(con, "collection_sources", {"source_id":SOURCE_ID,"source_code":"APPROVED_SALE_MANIFEST","source_name":"Approved sale-process manifests","source_kind":"MANUAL","authority_tier":2,"collection_policy":"MANUAL_ONLY"})
        for source in manifest["sources"]:
            existing = con.execute(
                """SELECT d.document_id,v.document_version_id
                   FROM source_documents d JOIN document_versions v ON v.document_id=d.document_id
                   WHERE d.canonical_url=?
                   ORDER BY v.version_no DESC LIMIT 1""",
                (source["url"],),
            ).fetchone()
            if existing:
                document_id, version_id = existing
            else:
                document_id, version_id = source["id"], source["id"]+"_v1"
                _insert(con, "source_documents", {"document_id":document_id,"source_id":SOURCE_ID,"canonical_url":source["url"],"publisher_name":source["publisher"],"document_type":source["document_type"],"first_seen_at":source["accessed_at"],"last_seen_at":source["accessed_at"]})
                payload = _json(source)
                _insert(con, "document_versions", {"document_version_id":version_id,"document_id":document_id,"version_no":1,"title":source.get("title"),"published_at":source["published_at"],"collected_at":source["accessed_at"],"content_sha256":hashlib.sha256(payload.encode()).hexdigest(),"snippet_text":None,"rights_status":source["rights_status"],"metadata_json":payload})
            extraction_id = source["id"]+"_ext"
            existing_extraction = con.execute(
                "SELECT pipeline_version FROM extraction_runs WHERE extraction_run_id=?",
                (extraction_id,),
            ).fetchone()
            extraction_pipeline = (
                existing_extraction[0]
                if existing_extraction
                else "approved-sale-manifest-v1:" + source["id"]
            )
            _insert(con, "extraction_runs", {"extraction_run_id":extraction_id,"document_version_id":version_id,"pipeline_version":extraction_pipeline,"model_name":"human-approved-manifest","status_code":"COMPLETED"})
            _insert(con, "event_mentions", {"event_mention_id":source["id"]+"_em","extraction_run_id":extraction_id,"extraction_key":manifest["manifest_id"],"event_category_id":"cat_sale","stage_code_hint":manifest["event"]["current_stage_code"],"title_raw":source.get("title") or manifest["event"]["canonical_title"],"confidence":1.0,"status_code":"APPROVED"})

        asset = manifest["asset"]
        _insert(con, "assets", {"asset_id":asset["id"],"canonical_name":asset["canonical_name"],"asset_class_id":asset.get("asset_class_id"),"road_address":asset.get("road_address"),"jibun_address":asset.get("jibun_address"),"status_code":asset.get("status_code","ACTIVE"),"metadata_json":_entity_metadata(asset)})
        for org in manifest["organizations"]:
            _insert(con, "organizations", {"organization_id":org["id"],"organization_type":org["organization_type"],"canonical_name":org["canonical_name"],"corporate_no":org.get("corporate_no"),"business_no":org.get("business_no"),"status_code":org.get("status_code","ACTIVE"),"metadata_json":_entity_metadata(org)})
        event = manifest["event"]
        _insert(con, "events", {"event_id":event["id"],"canonical_title":event["canonical_title"],"primary_category_id":"cat_sale","current_stage_code":event["current_stage_code"],"event_date_start":event.get("event_date_start"),"event_date_end":event.get("event_date_end"),"date_precision":event.get("date_precision","UNKNOWN"),"lifecycle_status":event.get("lifecycle_status","ACTIVE"),"verification_level":event.get("verification_level","V2"),"overall_confidence":event.get("overall_confidence"),"approved_at":approved_at})
        _insert(con, "event_assets", {"event_id":event["id"],"asset_id":asset["id"],"role_code":"SUBJECT","confidence":event.get("overall_confidence")})
        for source in manifest["sources"]:
            _insert(con, "event_mention_links", {"event_mention_id":source["id"]+"_em","event_id":event["id"],"relation_code":"SUPPORTING","linked_at":approved_at})
        process = manifest["process"]
        _insert(con, "sale_processes", {"sale_process_id":process["id"],"event_id":event["id"],"process_code":process["process_code"],"sale_method":process["sale_method"],"process_status":process["process_status"],"launched_at":process.get("launched_at"),"closed_at":process.get("closed_at"),"currency_code":process.get("currency_code","KRW"),"evidence_status":"MANUAL_VERIFIED","review_status":"APPROVED","metadata_json":_metadata(manifest,process)})
        for row in manifest["roles"]:
            _insert(con, "sale_process_roles", {"process_role_id":row["id"],"sale_process_id":process["id"],"organization_id":row["organization_id"],"role_code":row["role_code"],"valid_from":row.get("valid_from"),"valid_to":row.get("valid_to"),"evidence_status":"MANUAL_VERIFIED","review_status":"APPROVED","metadata_json":_metadata(manifest,row)})
            _insert(con, "event_participants", {"event_id":event["id"],"organization_id":row["organization_id"],"role_code":row["role_code"],"confidence":1.0})
        for row in manifest["rounds"]:
            _insert(con, "bid_rounds", {"bid_round_id":row["id"],"sale_process_id":process["id"],"round_no":row["round_no"],"round_code":row["round_code"],"round_type":row["round_type"],"invited_at":row.get("invited_at"),"deadline_at":row.get("deadline_at"),"announced_at":row.get("announced_at"),"round_status":row.get("round_status","REPORTED"),"evidence_status":"MANUAL_VERIFIED","review_status":"APPROVED","metadata_json":_metadata(manifest,row)})
        for row in manifest["participations"]:
            _insert(con, "bidder_participations", {"participation_id":row["id"],"bid_round_id":row["round_id"],"bidder_organization_id":row["bidder_organization_id"],"participation_status":row["participation_status"],"status_as_of":row.get("status_as_of"),"evidence_status":"MANUAL_VERIFIED","review_status":"APPROVED","confidence":row.get("confidence"),"metadata_json":_metadata(manifest,row)})
        for row in manifest["participation_members"]:
            _insert(con, "bidder_participation_members", {"participation_member_id":row["id"],"participation_id":row["participation_id"],"organization_id":row["organization_id"],"member_role":row["member_role"],"ownership_percent_decimal":row.get("ownership_percent_decimal"),"evidence_status":"MANUAL_VERIFIED","review_status":"APPROVED","metadata_json":_metadata(manifest,row)})
        for row in manifest["submissions"]:
            amount = row.get("amount")
            claim_id = None
            if amount and amount["kind"] != "UNKNOWN":
                claim_id = row["claim_id"]
                evidence_source = row["evidence"]["source_ids"][0]
                fields = _amount_fields(amount)
                _insert(con, "claims", {"claim_id":claim_id,"event_mention_id":evidence_source+"_em","predicate_code":"BID_PRICE","value_kind":"MONEY","raw_value":amount["raw_value"],"value_decimal_text":amount.get("decimal"),"lower_decimal_text":amount.get("lower_decimal"),"upper_decimal_text":amount.get("upper_decimal"),"comparator_code":fields["comparator_code"],"currency_code":amount["currency"],"certainty_code":"REPORTED","confidence":row.get("confidence",1.0),"verification_status":"VERIFIED","review_status":"ACCEPTED","extraction_method":"MANUAL"})
            values = {"bid_submission_id":row["id"],"participation_id":row["participation_id"],"submission_no":row.get("submission_no",1),"submitted_at":row.get("submitted_at"),"reported_rank":row.get("reported_rank"),"rank_scope":row.get("rank_scope"),"rank_as_of":row.get("rank_as_of"),"evidence_status":"SOURCE_CLAIM" if claim_id else "MANUAL_VERIFIED","source_claim_id":claim_id,"review_status":"APPROVED","confidence":row.get("confidence"),"metadata_json":_metadata(manifest,row)}
            values.update(_amount_fields(amount) if amount else {"comparator_code":"UNKNOWN","amount_precision":"UNKNOWN"})
            _insert(con, "bid_submissions", values)
        for row in manifest["funding"]:
            _insert(con, "bid_funding_components", {"funding_component_id":row["id"],"bid_submission_id":row["submission_id"],"funding_type":row["funding_type"],"provider_organization_id":row.get("provider_organization_id"),"recipient_vehicle_id":row.get("recipient_vehicle_id"),"amount_decimal":row.get("amount_decimal"),"currency_code":row.get("currency_code"),"comparator_code":row.get("comparator_code","UNKNOWN"),"lower_amount_decimal":row.get("lower_amount_decimal"),"upper_amount_decimal":row.get("upper_amount_decimal"),"commitment_status":row.get("commitment_status","REPORTED"),"evidence_status":"MANUAL_VERIFIED","review_status":"APPROVED","confidence":row.get("confidence"),"metadata_json":_metadata(manifest,row)})
        for row in manifest["decisions"]:
            _insert(con, "bid_decisions", {"bid_decision_id":row["id"],"sale_process_id":process["id"],"bid_round_id":row.get("round_id"),"participation_id":row.get("participation_id"),"decision_type":row["decision_type"],"decision_date":row.get("decision_date"),"decision_status":row.get("decision_status","VERIFIED"),"source_reason":row.get("source_reason"),"evidence_status":"MANUAL_VERIFIED","review_status":"APPROVED","confidence":row.get("confidence"),"metadata_json":_metadata(manifest,row)})
        for row in manifest["milestones"]:
            _insert(con, "transaction_milestones", {"milestone_id":row["id"],"sale_process_id":process["id"],"milestone_code":row["milestone_code"],"milestone_status":row.get("milestone_status","CONFIRMED"),"announced_at":row.get("announced_at"),"effective_date":row.get("effective_date"),"expected_date":row.get("expected_date"),"source_note":row.get("source_note"),"evidence_status":"MANUAL_VERIFIED","review_status":"APPROVED","confidence":row.get("confidence"),"metadata_json":_metadata(manifest,row)})
        for row in manifest.get("process_relations", []):
            _insert(con, "sale_process_relations", {
                "sale_process_relation_id": row["id"],
                "from_sale_process_id": row["from_sale_process_id"],
                "to_sale_process_id": row["to_sale_process_id"],
                "relation_type": row["relation_type"],
                "evidence_status": "MANUAL_VERIFIED",
                "review_status": "APPROVED",
                "metadata_json": _metadata(manifest, row),
            })
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("foreign key validation failed")
        inserted = con.total_changes - before
        if dry_run:
            con.rollback()
        else:
            con.commit()
            reconcile_relationships(db, allow_live=True)
        return ImportResult(manifest["manifest_id"], inserted, dry_run)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a normalized APPROVED sale-process manifest")
    parser.add_argument("database", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="permit an explicitly approved live DB import; use only after backup and dry-run",
    )
    args = parser.parse_args()
    result = import_manifest(
        args.database,
        args.manifest,
        dry_run=args.dry_run,
        allow_live=args.allow_live,
    )
    print(_json({"manifest_id":result.manifest_id,"inserted_rows":result.inserted_rows,"dry_run":result.dry_run}))


if __name__ == "__main__":
    main()
