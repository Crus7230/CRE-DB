#!/usr/bin/env python
"""Import approved institutional-LP manifests into Supabase PostgreSQL main."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from collector.approved_lp_mandate_manifest import (
    SOURCE_ID,
    _amount_fields,
    _amount_predicate,
    _claim_amount_fields,
    _entity_metadata,
    _metadata,
    _stable_id,
    validate_manifest,
)

DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        text = raw.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def quote_ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValueError("invalid PostgreSQL identifier")
    return f'"{value}"'


def insert_row(conn: Any, *, schema: str, table: str, values: Mapping[str, Any]) -> int:
    ns, target = quote_ident(schema), quote_ident(table)
    columns = ",".join(quote_ident(key) for key in values)
    placeholders = ",".join("%s" for _ in values)
    cur = conn.execute(
        f"INSERT INTO {ns}.{target} ({columns}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
        tuple(values.values()),
    )
    return cur.rowcount


def import_manifest(conn: Any, *, schema: str, manifest: Mapping[str, Any], apply: bool) -> dict[str, Any]:
    validate_manifest(manifest)
    inserted = 0
    approved_at = manifest["review"]["approved_at"]
    mention_ids: dict[str, str] = {}
    ns = quote_ident(schema)
    with conn.transaction(force_rollback=not apply):
        inserted += insert_row(conn, schema=schema, table="collection_sources", values={
            "source_id": SOURCE_ID,
            "source_code": "APPROVED_LP_MANDATE_MANIFEST",
            "source_name": "Approved institutional-LP mandate manifests",
            "source_kind": "MANUAL",
            "authority_tier": 1,
            "collection_policy": "MANUAL_ONLY",
        })
        for source in manifest["sources"]:
            existing = conn.execute(
                f"""SELECT d.document_id,v.document_version_id
                    FROM {ns}.source_documents d
                    JOIN {ns}.document_versions v ON v.document_id=d.document_id
                    WHERE d.canonical_url=%s ORDER BY v.version_no DESC LIMIT 1""",
                (source["url"],),
            ).fetchone()
            if existing:
                document_id, version_id = existing
            else:
                document_id, version_id = source["id"], source["id"] + "_v1"
                inserted += insert_row(conn, schema=schema, table="source_documents", values={
                    "document_id": document_id,
                    "source_id": SOURCE_ID,
                    "canonical_url": source["url"],
                    "publisher_name": source["publisher"],
                    "document_type": source["document_type"],
                    "first_seen_at": source["accessed_at"],
                    "last_seen_at": source["accessed_at"],
                    "access_status": "ACCESSIBLE",
                })
                inserted += insert_row(conn, schema=schema, table="document_versions", values={
                    "document_version_id": version_id,
                    "document_id": document_id,
                    "version_no": 1,
                    "title": source.get("title"),
                    "published_at": source["published_at"],
                    "collected_at": source["accessed_at"],
                    "content_sha256": hashlib.sha256(source["exact_text"].encode("utf-8")).hexdigest(),
                    "snippet_text": source["exact_text"],
                    "rights_status": source["rights_status"],
                    "metadata_json": json.dumps(source, ensure_ascii=False, sort_keys=True),
                })
            extraction_id = _stable_id("lp_ext", source["id"], version_id)
            inserted += insert_row(conn, schema=schema, table="extraction_runs", values={
                "extraction_run_id": extraction_id,
                "document_version_id": version_id,
                "pipeline_version": "approved-lp-mandate-manifest-pg-v1",
                "model_name": "human-approved-manifest",
                "started_at": approved_at,
                "completed_at": approved_at,
                "status_code": "COMPLETED",
            })
            mention_id = _stable_id("lp_em", manifest["manifest_id"], source["id"])
            mention_ids[source["id"]] = mention_id
            inserted += insert_row(conn, schema=schema, table="event_mentions", values={
                "event_mention_id": mention_id,
                "extraction_run_id": extraction_id,
                "extraction_key": manifest["manifest_id"],
                "event_category_id": "cat_invest",
                "stage_code_hint": manifest["event"]["current_stage_code"],
                "title_raw": source.get("title") or manifest["event"]["canonical_title"],
                "summary_raw": source["exact_text"],
                "confidence": 1.0,
                "status_code": "APPROVED",
            })
        for org in manifest["organizations"]:
            inserted += insert_row(conn, schema=schema, table="organizations", values={
                "organization_id": org["id"],
                "organization_type": org["organization_type"],
                "canonical_name": org["canonical_name"],
                "corporate_no": org.get("corporate_no"),
                "business_no": org.get("business_no"),
                "status_code": org.get("status_code", "ACTIVE"),
                "metadata_json": _entity_metadata(org),
            })
        event = manifest["event"]
        inserted += insert_row(conn, schema=schema, table="events", values={
            "event_id": event["id"],
            "canonical_title": event["canonical_title"],
            "primary_category_id": "cat_invest",
            "current_stage_code": event["current_stage_code"],
            "event_date_start": event.get("event_date_start"),
            "event_date_end": event.get("event_date_end"),
            "date_precision": event.get("date_precision", "UNKNOWN"),
            "lifecycle_status": event.get("lifecycle_status", "ACTIVE"),
            "verification_level": event.get("verification_level", "V2"),
            "overall_confidence": event.get("overall_confidence", 1.0),
            "approved_at": approved_at,
        })
        for source_id in event["evidence"]["source_ids"]:
            inserted += insert_row(conn, schema=schema, table="event_mention_links", values={
                "event_mention_id": mention_ids[source_id],
                "event_id": event["id"],
                "relation_code": "SUPPORTING",
                "linked_at": approved_at,
            })
        mandate = manifest["mandate"]
        inserted += insert_row(conn, schema=schema, table="lp_mandates", values={
            "mandate_id": mandate["id"],
            "event_id": event["id"],
            "lp_organization_id": mandate["lp_organization_id"],
            "mandate_code": mandate["mandate_code"],
            "mandate_name": mandate["mandate_name"],
            "vintage_year": mandate["vintage_year"],
            "announced_at": mandate.get("announced_at"),
            "application_deadline": mandate.get("application_deadline"),
            "selected_at": mandate.get("selected_at"),
            "mandate_status": mandate["mandate_status"],
            "mandate_scope": mandate.get("mandate_scope", "UNKNOWN"),
            "evidence_status": "MANUAL_VERIFIED",
            "review_status": "APPROVED",
            "metadata_json": _metadata(manifest, mandate),
        })
        for row in manifest["tracks"]:
            inserted += insert_row(conn, schema=schema, table="lp_mandate_tracks", values={
                "mandate_track_id": row["id"],
                "mandate_id": mandate["id"],
                "track_code": row["track_code"],
                "track_name": row["track_name"],
                "strategy_code": row["strategy_code"],
                "geography_code": row.get("geography_code"),
                "target_manager_count": row.get("target_manager_count"),
                "evidence_status": "MANUAL_VERIFIED",
                "review_status": "APPROVED",
                "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["guidelines"]:
            source_id = row["evidence"]["source_ids"][0]
            claim_id = row["id"] + "_claim"
            inserted += insert_row(conn, schema=schema, table="claims", values={
                "claim_id": claim_id,
                "event_mention_id": mention_ids[source_id],
                "predicate_code": "LP_MANDATE_TARGET_RETURN" if row["term_type"] == "TARGET_RETURN" else "LP_MANDATE_GUIDELINE",
                "value_kind": row["value_kind"],
                "raw_value": row["raw_text"],
                "text_value": row.get("text_value"),
                "value_decimal_text": row.get("value_decimal_text"),
                "lower_decimal_text": row.get("lower_decimal_text"),
                "upper_decimal_text": row.get("upper_decimal_text"),
                "comparator_code": row.get("comparator_code", "EXACT"),
                "currency_code": row.get("currency_code"),
                "unit_code": row.get("unit_code"),
                "certainty_code": "REPORTED",
                "confidence": row.get("confidence", 1.0),
                "verification_status": "VERIFIED",
                "review_status": "ACCEPTED",
                "extraction_method": "MANUAL",
            })
            inserted += insert_row(conn, schema=schema, table="lp_mandate_guidelines", values={
                "mandate_guideline_id": row["id"],
                "mandate_track_id": row["track_id"],
                "term_type": row["term_type"],
                "requirement_level": row.get("requirement_level", "UNKNOWN"),
                "raw_text": row["raw_text"],
                "value_kind": row.get("value_kind", "TEXT"),
                "text_value": row.get("text_value"),
                "value_decimal_text": row.get("value_decimal_text"),
                "lower_decimal_text": row.get("lower_decimal_text"),
                "upper_decimal_text": row.get("upper_decimal_text"),
                "comparator_code": row.get("comparator_code", "EXACT"),
                "currency_code": row.get("currency_code"),
                "unit_code": row.get("unit_code"),
                "return_basis": row.get("return_basis"),
                "evidence_status": "SOURCE_CLAIM",
                "source_claim_id": claim_id,
                "review_status": "APPROVED",
                "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["selections"]:
            inserted += insert_row(conn, schema=schema, table="lp_mandate_selections", values={
                "mandate_selection_id": row["id"],
                "mandate_track_id": row["track_id"],
                "manager_organization_id": row["manager_organization_id"],
                "selection_status": row["selection_status"],
                "selected_at": row.get("selected_at"),
                "rank_no": row.get("rank_no"),
                "evidence_status": "MANUAL_VERIFIED",
                "review_status": "APPROVED",
                "confidence": row.get("confidence", 1.0),
                "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["selection_members"]:
            inserted += insert_row(conn, schema=schema, table="lp_mandate_selection_members", values={
                "mandate_selection_id": row["selection_id"],
                "organization_id": row["organization_id"],
                "member_role": row["member_role"],
                "evidence_status": "MANUAL_VERIFIED",
                "review_status": "APPROVED",
                "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["selection_vehicles"]:
            inserted += insert_row(conn, schema=schema, table="lp_mandate_selection_vehicles", values={
                "mandate_selection_id": row["selection_id"],
                "vehicle_organization_id": row["vehicle_organization_id"],
                "vehicle_role": row["vehicle_role"],
                "evidence_status": "MANUAL_VERIFIED",
                "review_status": "APPROVED",
                "metadata_json": _metadata(manifest, row),
            })
        for row in manifest["amounts"]:
            amount, source_id = row["amount"], row["evidence"]["source_ids"][0]
            claim_id = row["id"] + "_claim"
            claim_values = {
                "claim_id": claim_id,
                "event_mention_id": mention_ids[source_id],
                "predicate_code": _amount_predicate(row["amount_basis"]),
                "value_kind": "MONEY",
                "raw_value": amount["raw_value"],
                **_claim_amount_fields(amount),
                "certainty_code": "REPORTED",
                "confidence": row.get("confidence", 1.0),
                "verification_status": "VERIFIED",
                "review_status": "ACCEPTED",
                "extraction_method": "MANUAL",
            }
            inserted += insert_row(conn, schema=schema, table="claims", values=claim_values)
            scope = {"mandate_id": None, "mandate_track_id": None, "mandate_selection_id": None}
            scope[{"MANDATE":"mandate_id","TRACK":"mandate_track_id","SELECTION":"mandate_selection_id"}[row["scope_type"]]] = row["scope_id"]
            inserted += insert_row(conn, schema=schema, table="lp_mandate_amounts", values={
                "mandate_amount_id": row["id"],
                **scope,
                "amount_basis": row["amount_basis"],
                **_amount_fields(amount),
                "amount_status": row["amount_status"],
                "is_current": row.get("is_current", 1),
                "supersedes_amount_id": row.get("supersedes_amount_id"),
                "evidence_status": "SOURCE_CLAIM",
                "source_claim_id": claim_id,
                "review_status": "APPROVED",
                "metadata_json": _metadata(manifest, row),
            })
        return {"manifest_id": manifest["manifest_id"], "inserted_rows": inserted, "dry_run": not apply}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, nargs="+")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    env = load_env(args.env)
    dsn = os.environ.get("SUPABASE_DB_URL") or env.get("SUPABASE_DB_URL")
    schema = os.environ.get("SUPABASE_DB_SCHEMA") or env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is missing")
    import psycopg
    results = []
    with psycopg.connect(dsn, connect_timeout=20) as conn:
        for path in args.manifest:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            results.append(import_manifest(conn, schema=schema, manifest=manifest, apply=args.apply))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
