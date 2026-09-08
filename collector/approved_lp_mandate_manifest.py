"""Import an explicitly approved institutional-LP manager-mandate manifest.

The importer performs no web extraction and no Korean amount parsing. Every
canonical amount, guideline and manager award must already be normalized and
approved, with an official-source exact text payload.
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
SOURCE_ID = "src_approved_lp_mandate_manifest"
DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
CANONICAL_SOURCE_TYPES = {
    "PRESS_RELEASE", "DISCLOSURE", "NOTICE", "BID_NOTICE", "REPORT",
    "API_RECORD", "LEGAL_DOCUMENT",
}


class ManifestValidationError(ValueError):
    """Raised before import or on stable-ID content conflicts."""


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


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _metadata(manifest: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    return _json({
        "manifest_id": manifest["manifest_id"],
        "evidence": row.get("evidence", {}),
        "review": manifest["review"],
        "record_context": row.get("metadata", {}),
    })


def _entity_metadata(row: Mapping[str, Any]) -> str:
    return _json(row.get("metadata", {}))


def _insert(con: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> None:
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    cur = con.execute(
        f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    if cur.rowcount:
        return
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
    if row is None or tuple(row) != tuple(values.values()):
        identity = ",".join(f"{key}={values[key]}" for key in pk_columns)
        raise ManifestValidationError(f"conflicting existing row in {table} for {identity}")


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


def _require_canonical_evidence(
    ids: list[str], path: str, source_types: Mapping[str, str]
) -> None:
    if not any(source_types[source_id] in CANONICAL_SOURCE_TYPES for source_id in ids):
        raise ManifestValidationError(
            f"{path} requires at least one official or party-primary source; "
            "article/RSS/other sources remain review candidates only"
        )


def _validate_amount(amount: Any, path: str) -> None:
    if not isinstance(amount, Mapping):
        raise ManifestValidationError(f"{path} must be an object")
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
        value = _required(amount, "decimal", path)
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
    source_text: dict[str, str] = {}
    source_types: dict[str, str] = {}
    for index, source in enumerate(sources):
        path = f"sources[{index}]"
        if not isinstance(source, Mapping):
            raise ManifestValidationError(f"{path} must be an object")
        source_id = _required(source, "id", path)
        if source_id in source_ids:
            raise ManifestValidationError(f"duplicate source id: {source_id}")
        source_ids.add(source_id)
        for key in ("url", "publisher", "document_type", "published_at", "accessed_at", "rights_status", "exact_text"):
            _required(source, key, path)
        if source["document_type"] not in {
            "ARTICLE", "PRESS_RELEASE", "DISCLOSURE", "NOTICE", "BID_NOTICE",
            "REPORT", "RSS_ITEM", "API_RECORD", "LEGAL_DOCUMENT", "OTHER",
        }:
            raise ManifestValidationError(f"{path}.document_type is invalid")
        if source["rights_status"] not in {
            "FULL_STORAGE_ALLOWED", "EXCERPT_ALLOWED", "METADATA_ONLY",
            "MANUAL_ACCESS", "UNKNOWN",
        }:
            raise ManifestValidationError(f"{path}.rights_status is invalid")
        source_text[source_id] = source["exact_text"]
        source_types[source_id] = source["document_type"]

    organizations = manifest.get("organizations")
    if not isinstance(organizations, list) or not organizations:
        raise ManifestValidationError("organizations must be non-empty")
    org_ids = set()
    for i, row in enumerate(organizations):
        path = f"organizations[{i}]"
        row_id = _required(row, "id", path)
        if row_id in org_ids:
            raise ManifestValidationError(f"duplicate organization id: {row_id}")
        org_ids.add(row_id)
        _required(row, "organization_type", path)
        _required(row, "canonical_name", path)

    for key in ("event", "mandate"):
        row = manifest.get(key)
        if not isinstance(row, Mapping):
            raise ManifestValidationError(f"{key} is required")
        _required(row, "id", key)
        ids = _evidence_ids(row, key, source_ids)
        _require_canonical_evidence(ids, key, source_types)
    if manifest["mandate"].get("lp_organization_id") not in org_ids:
        raise ManifestValidationError("mandate.lp_organization_id is unknown")

    collections = (
        "tracks", "guidelines", "selections", "selection_members",
        "selection_vehicles", "amounts", "deployments",
    )
    for name in collections:
        if not isinstance(manifest.get(name), list):
            raise ManifestValidationError(f"{name} must be an array")

    track_ids: set[str] = set()
    for i, row in enumerate(manifest["tracks"]):
        path = f"tracks[{i}]"; row_id = _required(row, "id", path)
        if row_id in track_ids: raise ManifestValidationError(f"duplicate track id: {row_id}")
        track_ids.add(row_id); ids = _evidence_ids(row, path, source_ids)
        _require_canonical_evidence(ids, path, source_types)
    selection_ids: set[str] = set()
    for i, row in enumerate(manifest["selections"]):
        path = f"selections[{i}]"; row_id = _required(row, "id", path)
        if row_id in selection_ids: raise ManifestValidationError(f"duplicate selection id: {row_id}")
        selection_ids.add(row_id); ids = _evidence_ids(row, path, source_ids)
        _require_canonical_evidence(ids, path, source_types)
        if row.get("track_id") not in track_ids or row.get("manager_organization_id") not in org_ids:
            raise ManifestValidationError(f"{path} has unknown track or manager")
    for i, row in enumerate(manifest["guidelines"]):
        path = f"guidelines[{i}]"; _required(row, "id", path); ids = _evidence_ids(row, path, source_ids)
        _require_canonical_evidence(ids, path, source_types)
        if row.get("track_id") not in track_ids: raise ManifestValidationError(f"{path}.track_id is unknown")
        raw = _required(row, "raw_text", path)
        if not any(raw in source_text[sid] for sid in ids):
            raise ManifestValidationError(f"{path}.raw_text is not an exact source substring")
    amount_ids: set[str] = set()
    for i, row in enumerate(manifest["amounts"]):
        path = f"amounts[{i}]"; row_id = _required(row, "id", path)
        if row_id in amount_ids: raise ManifestValidationError(f"duplicate amount id: {row_id}")
        amount_ids.add(row_id); ids = _evidence_ids(row, path, source_ids); _validate_amount(row.get("amount"), f"{path}.amount")
        _require_canonical_evidence(ids, path, source_types)
        scope = _required(row, "scope_type", path); scope_id = _required(row, "scope_id", path)
        valid = (scope == "MANDATE" and scope_id == manifest["mandate"]["id"]) or (scope == "TRACK" and scope_id in track_ids) or (scope == "SELECTION" and scope_id in selection_ids)
        if not valid: raise ManifestValidationError(f"{path} has invalid scope")
        raw = row["amount"]["raw_value"]
        if not any(raw in source_text[sid] for sid in ids):
            raise ManifestValidationError(f"{path}.amount.raw_value is not an exact source substring")
    for i, row in enumerate(manifest["selection_members"]):
        path = f"selection_members[{i}]"; ids = _evidence_ids(row, path, source_ids)
        _require_canonical_evidence(ids, path, source_types)
        if row.get("selection_id") not in selection_ids or row.get("organization_id") not in org_ids:
            raise ManifestValidationError(f"{path} has unknown selection or organization")
    for i, row in enumerate(manifest["selection_vehicles"]):
        path = f"selection_vehicles[{i}]"; ids = _evidence_ids(row, path, source_ids)
        _require_canonical_evidence(ids, path, source_types)
        if row.get("selection_id") not in selection_ids or row.get("vehicle_organization_id") not in org_ids:
            raise ManifestValidationError(f"{path} has unknown selection or vehicle")
    deployment_ids: set[str] = set()
    for i, row in enumerate(manifest["deployments"]):
        path = f"deployments[{i}]"; row_id = _required(row, "id", path)
        if row_id in deployment_ids: raise ManifestValidationError(f"duplicate deployment id: {row_id}")
        deployment_ids.add(row_id); ids = _evidence_ids(row, path, source_ids); _validate_amount(row.get("amount"), f"{path}.amount")
        _require_canonical_evidence(ids, path, source_types)
        if row.get("selection_id") not in selection_ids: raise ManifestValidationError(f"{path}.selection_id is unknown")
        if not any(row.get(key) for key in ("sale_process_id", "event_id", "asset_id", "project_id")):
            raise ManifestValidationError(f"{path} requires a deal/event/asset/project target")
        raw = row["amount"]["raw_value"]
        if not any(raw in source_text[sid] for sid in ids):
            raise ManifestValidationError(f"{path}.amount.raw_value is not an exact source substring")


def _amount_fields(amount: Mapping[str, Any]) -> dict[str, Any]:
    comparator = {"APPROX": "ABOUT"}.get(amount["kind"], amount["kind"])
    return {
        "amount_decimal": amount.get("decimal"),
        "lower_amount_decimal": amount.get("lower_decimal"),
        "upper_amount_decimal": amount.get("upper_decimal"),
        "currency_code": amount["currency"],
        "comparator_code": comparator,
        "raw_value": amount["raw_value"],
    }


def _claim_amount_fields(amount: Mapping[str, Any]) -> dict[str, Any]:
    comparator = {"APPROX": "ABOUT"}.get(amount["kind"], amount["kind"])
    return {
        "value_decimal_text": amount.get("decimal"),
        "lower_decimal_text": amount.get("lower_decimal"),
        "upper_decimal_text": amount.get("upper_decimal"),
        "comparator_code": comparator,
        "currency_code": amount["currency"],
    }


def _amount_predicate(basis: str) -> str:
    if basis == "PROGRAM_TOTAL": return "LP_MANDATE_PROGRAM_AMOUNT"
    if basis == "TARGET_FUND_SIZE": return "LP_MANDATE_TARGET_FUND_SIZE"
    return "LP_MANDATE_COMMITMENT_AMOUNT"


def _load_manifest(value: Path | str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping): return dict(value)
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
    if not db.exists(): raise ManifestValidationError(f"database does not exist: {db}")

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
        _insert(con, "collection_sources", {
            "source_id": SOURCE_ID, "source_code": "APPROVED_LP_MANDATE_MANIFEST",
            "source_name": "Approved institutional-LP mandate manifests",
            "source_kind": "MANUAL", "authority_tier": 1, "collection_policy": "MANUAL_ONLY",
        })
        mention_ids: dict[str, str] = {}
        for source in manifest["sources"]:
            existing = con.execute(
                """SELECT d.document_id,v.document_version_id FROM source_documents d
                     JOIN document_versions v ON v.document_id=d.document_id
                    WHERE d.canonical_url=? ORDER BY v.version_no DESC LIMIT 1""",
                (source["url"],),
            ).fetchone()
            if existing:
                document_id, version_id = existing
            else:
                document_id, version_id = source["id"], source["id"] + "_v1"
                _insert(con, "source_documents", {
                    "document_id": document_id, "source_id": SOURCE_ID,
                    "canonical_url": source["url"], "publisher_name": source["publisher"],
                    "document_type": source["document_type"], "first_seen_at": source["accessed_at"],
                    "last_seen_at": source["accessed_at"],
                })
                payload = _json(source)
                _insert(con, "document_versions", {
                    "document_version_id": version_id, "document_id": document_id, "version_no": 1,
                    "title": source.get("title"), "published_at": source["published_at"],
                    "collected_at": source["accessed_at"],
                    "content_sha256": hashlib.sha256(source["exact_text"].encode("utf-8")).hexdigest(),
                    "snippet_text": source["exact_text"], "rights_status": source["rights_status"],
                    "metadata_json": payload,
                })
            extraction_id = _stable_id("lp_ext", source["id"], version_id)
            _insert(con, "extraction_runs", {
                "extraction_run_id": extraction_id, "document_version_id": version_id,
                "pipeline_version": "approved-lp-mandate-manifest-v1",
                "model_name": "human-approved-manifest", "status_code": "COMPLETED",
            })
            mention_id = _stable_id("lp_em", manifest["manifest_id"], source["id"])
            mention_ids[source["id"]] = mention_id
            _insert(con, "event_mentions", {
                "event_mention_id": mention_id, "extraction_run_id": extraction_id,
                "extraction_key": manifest["manifest_id"], "event_category_id": "cat_invest",
                "stage_code_hint": manifest["event"]["current_stage_code"],
                "title_raw": source.get("title") or manifest["event"]["canonical_title"],
                "confidence": 1.0, "status_code": "APPROVED",
            })

        for org in manifest["organizations"]:
            _insert(con, "organizations", {
                "organization_id": org["id"], "organization_type": org["organization_type"],
                "canonical_name": org["canonical_name"], "corporate_no": org.get("corporate_no"),
                "business_no": org.get("business_no"), "status_code": org.get("status_code", "ACTIVE"),
                "metadata_json": _entity_metadata(org),
            })
        event = manifest["event"]
        _insert(con, "events", {
            "event_id": event["id"], "canonical_title": event["canonical_title"],
            "primary_category_id": "cat_invest", "current_stage_code": event["current_stage_code"],
            "event_date_start": event.get("event_date_start"), "event_date_end": event.get("event_date_end"),
            "date_precision": event.get("date_precision", "UNKNOWN"),
            "lifecycle_status": event.get("lifecycle_status", "ACTIVE"),
            "verification_level": event.get("verification_level", "V2"),
            "overall_confidence": event.get("overall_confidence", 1.0), "approved_at": approved_at,
        })
        for source_id in event["evidence"]["source_ids"]:
            _insert(con, "event_mention_links", {
                "event_mention_id": mention_ids[source_id], "event_id": event["id"],
                "relation_code": "SUPPORTING", "linked_at": approved_at,
            })
        mandate = manifest["mandate"]
        _insert(con, "lp_mandates", {
            "mandate_id": mandate["id"], "event_id": event["id"],
            "lp_organization_id": mandate["lp_organization_id"], "mandate_code": mandate["mandate_code"],
            "mandate_name": mandate["mandate_name"], "vintage_year": mandate["vintage_year"],
            "announced_at": mandate.get("announced_at"), "application_deadline": mandate.get("application_deadline"),
            "selected_at": mandate.get("selected_at"), "mandate_status": mandate["mandate_status"],
            "mandate_scope": mandate.get("mandate_scope", "UNKNOWN"),
            "evidence_status": "MANUAL_VERIFIED", "review_status": "APPROVED",
            "metadata_json": _metadata(manifest, mandate),
        })
        for row in manifest["tracks"]:
            _insert(con, "lp_mandate_tracks", {
                "mandate_track_id": row["id"], "mandate_id": mandate["id"],
                "track_code": row["track_code"], "track_name": row["track_name"],
                "strategy_code": row["strategy_code"], "geography_code": row.get("geography_code"),
                "target_manager_count": row.get("target_manager_count"),
                "evidence_status": "MANUAL_VERIFIED", "review_status": "APPROVED",
                "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["guidelines"]:
            source_id = row["evidence"]["source_ids"][0]
            claim_id = row["id"] + "_claim"
            predicate = "LP_MANDATE_TARGET_RETURN" if row["term_type"] == "TARGET_RETURN" else "LP_MANDATE_GUIDELINE"
            _insert(con, "claims", {
                "claim_id": claim_id, "event_mention_id": mention_ids[source_id],
                "predicate_code": predicate, "value_kind": row["value_kind"],
                "raw_value": row["raw_text"], "text_value": row.get("text_value"),
                "value_decimal_text": row.get("value_decimal_text"),
                "lower_decimal_text": row.get("lower_decimal_text"),
                "upper_decimal_text": row.get("upper_decimal_text"),
                "comparator_code": row.get("comparator_code", "EXACT"),
                "currency_code": row.get("currency_code"), "unit_code": row.get("unit_code"),
                "certainty_code": "REPORTED", "confidence": row.get("confidence", 1.0),
                "verification_status": "VERIFIED", "review_status": "ACCEPTED",
                "extraction_method": "MANUAL",
            })
            _insert(con, "lp_mandate_guidelines", {
                "mandate_guideline_id": row["id"], "mandate_track_id": row["track_id"],
                "term_type": row["term_type"], "requirement_level": row.get("requirement_level", "UNKNOWN"),
                "raw_text": row["raw_text"], "value_kind": row.get("value_kind", "TEXT"),
                "text_value": row.get("text_value"), "value_decimal_text": row.get("value_decimal_text"),
                "lower_decimal_text": row.get("lower_decimal_text"), "upper_decimal_text": row.get("upper_decimal_text"),
                "comparator_code": row.get("comparator_code", "EXACT"), "currency_code": row.get("currency_code"),
                "unit_code": row.get("unit_code"), "return_basis": row.get("return_basis"),
                "evidence_status": "SOURCE_CLAIM", "source_claim_id": claim_id,
                "review_status": "APPROVED", "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["selections"]:
            _insert(con, "lp_mandate_selections", {
                "mandate_selection_id": row["id"], "mandate_track_id": row["track_id"],
                "manager_organization_id": row["manager_organization_id"],
                "selection_status": row["selection_status"], "selected_at": row.get("selected_at"),
                "rank_no": row.get("rank_no"), "evidence_status": "MANUAL_VERIFIED",
                "review_status": "APPROVED", "confidence": row.get("confidence", 1.0),
                "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["selection_members"]:
            _insert(con, "lp_mandate_selection_members", {
                "mandate_selection_id": row["selection_id"], "organization_id": row["organization_id"],
                "member_role": row["member_role"], "evidence_status": "MANUAL_VERIFIED",
                "review_status": "APPROVED", "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["selection_vehicles"]:
            _insert(con, "lp_mandate_selection_vehicles", {
                "mandate_selection_id": row["selection_id"],
                "vehicle_organization_id": row["vehicle_organization_id"],
                "vehicle_role": row["vehicle_role"], "evidence_status": "MANUAL_VERIFIED",
                "review_status": "APPROVED", "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["amounts"]:
            amount = row["amount"]; source_id = row["evidence"]["source_ids"][0]
            claim_id = row["id"] + "_claim"
            _insert(con, "claims", {
                "claim_id": claim_id, "event_mention_id": mention_ids[source_id],
                "predicate_code": _amount_predicate(row["amount_basis"]), "value_kind": "MONEY",
                "raw_value": amount["raw_value"], **_claim_amount_fields(amount),
                "certainty_code": "REPORTED", "confidence": row.get("confidence", 1.0),
                "verification_status": "VERIFIED", "review_status": "ACCEPTED", "extraction_method": "MANUAL",
            })
            scope = {"mandate_id": None, "mandate_track_id": None, "mandate_selection_id": None}
            scope[{"MANDATE": "mandate_id", "TRACK": "mandate_track_id", "SELECTION": "mandate_selection_id"}[row["scope_type"]]] = row["scope_id"]
            _insert(con, "lp_mandate_amounts", {
                "mandate_amount_id": row["id"], **scope, "amount_basis": row["amount_basis"],
                **_amount_fields(amount), "amount_status": row["amount_status"],
                "is_current": row.get("is_current", 1), "supersedes_amount_id": row.get("supersedes_amount_id"),
                "evidence_status": "SOURCE_CLAIM", "source_claim_id": claim_id,
                "review_status": "APPROVED", "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["deployments"]:
            amount = row["amount"]; source_id = row["evidence"]["source_ids"][0]
            claim_id = row["id"] + "_claim"
            _insert(con, "claims", {
                "claim_id": claim_id, "event_mention_id": mention_ids[source_id],
                "predicate_code": "INVESTMENT_EXECUTED_AMOUNT", "value_kind": "MONEY",
                "raw_value": amount["raw_value"], **_claim_amount_fields(amount),
                "certainty_code": "REPORTED", "confidence": row.get("confidence", 1.0),
                "verification_status": "VERIFIED", "review_status": "ACCEPTED", "extraction_method": "MANUAL",
            })
            _insert(con, "lp_mandate_deployments", {
                "mandate_deployment_id": row["id"], "mandate_selection_id": row["selection_id"],
                "fund_vehicle_organization_id": row.get("fund_vehicle_organization_id"),
                "sale_process_id": row.get("sale_process_id"), "event_id": row.get("event_id"),
                "asset_id": row.get("asset_id"), "project_id": row.get("project_id"),
                "deployment_basis": row["deployment_basis"], **_amount_fields(amount),
                "deployment_status": row["deployment_status"], "deployed_at": row.get("deployed_at"),
                "is_current": row.get("is_current", 1), "evidence_status": "SOURCE_CLAIM",
                "source_claim_id": claim_id, "review_status": "APPROVED",
                "confidence": row.get("confidence", 1.0), "metadata_json": _metadata(manifest, row),
            })
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("foreign key validation failed")
        inserted = con.total_changes - before
        if dry_run: con.rollback()
        else:
            con.commit()
            reconcile_relationships(db, allow_live=True)
        return ImportResult(manifest["manifest_id"], inserted, dry_run)
    except Exception:
        con.rollback(); raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an APPROVED LP manager-mandate manifest")
    parser.add_argument("database", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    result = import_manifest(args.database, args.manifest, dry_run=args.dry_run, allow_live=args.allow_live)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
