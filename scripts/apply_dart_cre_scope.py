#!/usr/bin/env python
"""Classify OpenDART documents by CRE scope and optionally hard-delete out-of-scope rows.

Dry-run is the default. Apply mode is fail-closed on expected counts, rollback bundle
hash, and canonical claim/event dependencies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.dart_cre_scope import CLASSIFIER_VERSION, classify_dart_cre_scope

ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
DEFAULT_BACKUP = Path(r"C:\Users\10137\AppData\Local\hermes\cache\cre-db-dart-scope-rollback-20260820.json.gz")
MIGRATION = ROOT / "db" / "v2" / "migrations" / "2.9.0_document_cre_scope.sql"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LIVE_DISCLOSURES_SQL = """WITH latest AS (
    SELECT dv.*,row_number() over(
        partition by document_id order by version_no desc,document_version_id desc
    ) rn FROM {schema}.document_versions dv
) SELECT sd.document_id,l.document_version_id,l.title,l.stored_text,l.content_sha256
    FROM {schema}.source_documents sd
    JOIN {schema}.collection_sources cs ON cs.source_id=sd.source_id
    JOIN latest l ON l.document_id=sd.document_id AND l.rn=1
   WHERE sd.document_type='DISCLOSURE' AND cs.source_code='OPENDART'
   ORDER BY l.published_at,sd.document_id"""
REMAINING_DISCLOSURES_SQL = """SELECT count(*)
    FROM {schema}.source_documents sd
    JOIN {schema}.collection_sources cs ON cs.source_id=sd.source_id
   WHERE sd.document_type='DISCLOSURE' AND cs.source_code='OPENDART'"""
REVIEW_STATUSES = {"CRE_REVIEW", "CRE_REVIEW_MIXED", "CRE_REVIEW_PARSE_FAILED"}
LOCK_TABLES = (
    "schema_meta", "collection_sources", "source_documents", "document_versions", "document_enrichments", "run_documents",
    "extraction_runs", "document_tokens", "mentions", "mention_fragments", "mention_values",
    "mention_relations", "mention_resolutions",
    "event_mentions", "event_mention_members", "claims", "claim_arguments", "claim_evidence",
    "event_mention_links", "event_transitions", "measurement_facts",
    "document_families", "document_family_members", "review_tasks", "duplicate_candidates",
    "industry_taxonomies", "macro_observations", "macro_releases", "market_universe_snapshots",
)


class DecisionPartition(NamedTuple):
    confirmed_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]


def partition_decisions(decisions: list[dict]) -> DecisionPartition:
    return DecisionPartition(
        tuple(row["document_id"] for row in decisions if row["status"] == "CRE_CONFIRMED"),
        tuple(row["document_id"] for row in decisions if row["status"] in REVIEW_STATUSES),
        tuple(row["document_id"] for row in decisions if row["status"].startswith("OUT_OF_SCOPE_")),
    )


def assessment_row(
    document_version_id: str,
    status: str,
    reason_codes: list[str],
    evidence: dict,
    assessed_at: str,
) -> tuple[str, str, str, str, str, str, str, str]:
    assessment_id = hashlib.sha256(
        f"document-scope:{document_version_id}:CRE:{CLASSIFIER_VERSION}".encode()
    ).hexdigest()[:32]
    return (
        assessment_id,
        document_version_id,
        "CRE",
        CLASSIFIER_VERSION,
        status,
        json.dumps(reason_codes, ensure_ascii=False, sort_keys=True),
        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        assessed_at,
    )


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if IDENTIFIER.fullmatch(key):
            values[key] = value.strip().strip('"').strip("'")
    return values


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_sha256(value: dict) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fetch_dict_rows(cur, query: str, params: tuple) -> list[dict]:
    cur.execute(query, params)
    columns = [column.name for column in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def load_rollback_bundle(path: Path) -> dict:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("rollback bundle is not valid gzip JSON") from exc
    if not isinstance(value, dict):
        raise SystemExit("rollback bundle root must be an object")
    return value


def validate_rollback_bundle(
    bundle: dict,
    *,
    schema: str,
    decisions: list[dict],
    excluded_version_ids: list[str],
    dependency_counts: dict[str, int],
    closure_manifest_sha256: str,
    dependent_rows_sha256: str,
) -> None:
    current_decisions = {
        row["document_id"]: {
            "status": row["status"],
            "report_kind": row["report_kind"],
            "reason_codes": row["reason_codes"],
            "document_version_id": row["document_version_id"],
            "content_sha256": row["content_sha256"],
        }
        for row in decisions
    }
    bundle_decisions = bundle.get("decisions")
    bundle_documents = bundle.get("excluded_source_documents")
    bundle_versions = bundle.get("excluded_document_versions")
    if bundle.get("policy") != "HARD_DELETE_OUT_OF_SCOPE_KEEP_REVIEW":
        raise RuntimeError("rollback bundle policy mismatch")
    if bundle.get("classifier_version") != CLASSIFIER_VERSION or bundle.get("schema") != schema:
        raise RuntimeError("rollback bundle classifier/schema mismatch")
    if bundle_decisions != current_decisions:
        raise RuntimeError("rollback bundle decision identity mismatch")
    current_excluded_ids = sorted(
        row["document_id"] for row in decisions if row["status"].startswith("OUT_OF_SCOPE_")
    )
    if not isinstance(bundle_documents, list) or sorted(row.get("document_id") for row in bundle_documents) != current_excluded_ids:
        raise RuntimeError("rollback bundle source-document identity mismatch")
    if not isinstance(bundle_versions, list) or sorted(row.get("document_version_id") for row in bundle_versions) != sorted(excluded_version_ids):
        raise RuntimeError("rollback bundle version identity mismatch")
    if bundle.get("dependencies") != dependency_counts:
        raise RuntimeError("rollback bundle dependency-count mismatch")
    if bundle.get("closure_manifest_sha256") != closure_manifest_sha256:
        raise RuntimeError("rollback bundle closure manifest mismatch")
    bundle_dependent_rows = bundle.get("dependent_rows")
    if not isinstance(bundle_dependent_rows, dict):
        raise RuntimeError("rollback bundle dependent rows are missing")
    if bundle.get("dependent_rows_sha256") != manifest_sha256(bundle_dependent_rows):
        raise RuntimeError("rollback bundle dependent-row content is corrupt")
    if bundle.get("dependent_rows_sha256") != dependent_rows_sha256:
        raise RuntimeError("rollback bundle dependent-row content mismatch")
    if bundle.get("sqlite_latest_hash_mismatches"):
        raise RuntimeError("rollback bundle contains SQLite identity mismatches")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply conservative CRE scope to OpenDART documents")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback-after-apply", action="store_true")
    parser.add_argument("--validate-bundle", action="store_true")
    parser.add_argument("--expected-total", type=int, required=True)
    parser.add_argument("--expected-excluded", type=int, required=True)
    parser.add_argument("--rollback-bundle", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--expected-backup-sha256")
    parser.add_argument("--output", type=Path, default=Path(r"C:\Users\10137\AppData\Local\hermes\cache\dart-cre-scope-apply-result.json"))
    args = parser.parse_args()

    if args.rollback_after_apply and not args.apply:
        raise SystemExit("--rollback-after-apply requires --apply")

    if (args.apply or args.validate_bundle) and not args.expected_backup_sha256:
        raise SystemExit("--expected-backup-sha256 is required for bundle validation")
    if args.apply or args.validate_bundle:
        if not args.rollback_bundle.is_file():
            raise SystemExit("rollback bundle missing")
        if sha256(args.rollback_bundle) != args.expected_backup_sha256:
            raise SystemExit("rollback bundle hash mismatch")
        rollback_bundle = load_rollback_bundle(args.rollback_bundle)
    else:
        rollback_bundle = None

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc

    env = load_env(ENV)
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not IDENTIFIER.fullmatch(schema):
        raise SystemExit("invalid schema identifier")
    assessed_at = datetime.now(timezone.utc).isoformat()
    result_report = {}

    with psycopg.connect(env["SUPABASE_DB_URL"], connect_timeout=20) as conn:
        with conn.cursor() as cur:
            if args.apply:
                cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("dart-cre-scope-rule-v1-hard-delete",))
                lock_targets = ",".join(f"{schema}.{table}" for table in LOCK_TABLES)
                cur.execute(f"LOCK TABLE {lock_targets} IN SHARE MODE")
            else:
                cur.execute("BEGIN READ ONLY")
            cur.execute(LIVE_DISCLOSURES_SQL.format(schema=schema))
            decisions = []
            assessment_rows = []
            for document_id, version_id, title, stored_text, content_sha256 in cur.fetchall():
                scope = classify_dart_cre_scope(title, stored_text)
                decision = {
                    "document_id": document_id,
                    "document_version_id": version_id,
                    "content_sha256": content_sha256,
                    "status": scope.status,
                    "report_kind": scope.report_kind,
                    "reason_codes": list(scope.reason_codes),
                }
                decisions.append(decision)
                assessment_rows.append(assessment_row(
                    version_id,
                    scope.status,
                    list(scope.reason_codes),
                    {
                        "reportKind": scope.report_kind,
                        "assetCategory": scope.asset_category,
                        "assetText": scope.asset_text,
                        "subjectText": scope.subject_text,
                        "detailText": scope.detail_text,
                    },
                    assessed_at,
                ))
            partition = partition_decisions(decisions)
            if len(decisions) != args.expected_total:
                raise RuntimeError(f"expected {args.expected_total} disclosures, got {len(decisions)}")
            if len(partition.excluded_ids) != args.expected_excluded:
                raise RuntimeError(f"expected {args.expected_excluded} exclusions, got {len(partition.excluded_ids)}")

            excluded_ids = list(partition.excluded_ids)
            cur.execute(
                f"SELECT document_version_id FROM {schema}.document_versions WHERE document_id=ANY(%s)",
                (excluded_ids,),
            )
            excluded_version_ids = [row[0] for row in cur.fetchall()]
            cur.execute(
                f"SELECT extraction_run_id FROM {schema}.extraction_runs WHERE document_version_id=ANY(%s)",
                (excluded_version_ids,),
            )
            extraction_ids = [row[0] for row in cur.fetchall()]
            event_mention_ids: list[str] = []
            mention_ids: list[str] = []
            if extraction_ids:
                cur.execute(f"SELECT event_mention_id FROM {schema}.event_mentions WHERE extraction_run_id=ANY(%s)", (extraction_ids,))
                event_mention_ids = [row[0] for row in cur.fetchall()]
                cur.execute(f"SELECT mention_id FROM {schema}.mentions WHERE extraction_run_id=ANY(%s)", (extraction_ids,))
                mention_ids = [row[0] for row in cur.fetchall()]

            resolution_ids: list[str] = []
            if mention_ids:
                cur.execute(
                    f"SELECT mention_resolution_id FROM {schema}.mention_resolutions WHERE mention_id=ANY(%s)",
                    (mention_ids,),
                )
                resolution_ids = [row[0] for row in cur.fetchall()]

            cur.execute(
                f"SELECT document_enrichment_id FROM {schema}.document_enrichments WHERE document_version_id=ANY(%s)",
                (excluded_version_ids,),
            )
            enrichment_ids = [row[0] for row in cur.fetchall()]
            cur.execute(
                f"SELECT run_id,document_version_id FROM {schema}.run_documents WHERE document_version_id=ANY(%s)",
                (excluded_version_ids,),
            )
            run_document_keys = [[row[0], row[1]] for row in cur.fetchall()]
            review_task_ids: dict[str, list[str]] = {}
            for kind, ids in (
                ("EVENT_MENTION", event_mention_ids),
                ("MENTION", mention_ids),
                ("RESOLUTION", resolution_ids),
            ):
                if ids:
                    cur.execute(
                        f"SELECT review_task_id FROM {schema}.review_tasks WHERE target_kind=%s AND target_id=ANY(%s)",
                        (kind, ids),
                    )
                    review_task_ids[kind] = [row[0] for row in cur.fetchall()]
                else:
                    review_task_ids[kind] = []

            dependent_rows = {
                "document_enrichments": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.document_enrichments WHERE document_version_id=ANY(%s) ORDER BY document_enrichment_id",
                    (excluded_version_ids,),
                ),
                "run_documents": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.run_documents WHERE document_version_id=ANY(%s) ORDER BY run_id,document_version_id",
                    (excluded_version_ids,),
                ),
                "extraction_runs": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.extraction_runs WHERE extraction_run_id=ANY(%s) ORDER BY extraction_run_id",
                    (extraction_ids,),
                ),
                "document_tokens": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.document_tokens WHERE extraction_run_id=ANY(%s) ORDER BY extraction_run_id,token_index",
                    (extraction_ids,),
                ),
                "mentions": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.mentions WHERE mention_id=ANY(%s) ORDER BY mention_id",
                    (mention_ids,),
                ),
                "mention_fragments": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.mention_fragments WHERE mention_id=ANY(%s) ORDER BY mention_id,fragment_no",
                    (mention_ids,),
                ),
                "mention_values": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.mention_values WHERE mention_id=ANY(%s) ORDER BY mention_id",
                    (mention_ids,),
                ),
                "mention_relations": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.mention_relations WHERE extraction_run_id=ANY(%s) ORDER BY mention_relation_id",
                    (extraction_ids,),
                ),
                "mention_resolutions": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.mention_resolutions WHERE mention_resolution_id=ANY(%s) ORDER BY mention_resolution_id",
                    (resolution_ids,),
                ),
                "event_mentions": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.event_mentions WHERE event_mention_id=ANY(%s) ORDER BY event_mention_id",
                    (event_mention_ids,),
                ),
                "event_mention_members": fetch_dict_rows(
                    cur, f"SELECT * FROM {schema}.event_mention_members WHERE event_mention_id=ANY(%s) ORDER BY event_mention_id,mention_id,semantic_role",
                    (event_mention_ids,),
                ),
                "review_tasks": fetch_dict_rows(
                    cur, f"""SELECT * FROM {schema}.review_tasks WHERE
                        (target_kind='EVENT_MENTION' AND target_id=ANY(%s)) OR
                        (target_kind='MENTION' AND target_id=ANY(%s)) OR
                        (target_kind='RESOLUTION' AND target_id=ANY(%s))
                        ORDER BY review_task_id""",
                    (event_mention_ids, mention_ids, resolution_ids),
                ),
            }
            dependent_rows_hash = manifest_sha256(dependent_rows)

            canonical_dependencies = {}
            checks = [
                ("claims", f"SELECT count(*) FROM {schema}.claims WHERE event_mention_id=ANY(%s)", event_mention_ids),
                ("claims_mentions", f"SELECT count(*) FROM {schema}.claims WHERE subject_mention_id=ANY(%s) OR object_mention_id=ANY(%s)", (mention_ids, mention_ids)),
                ("claim_arguments_event_mentions", f"SELECT count(*) FROM {schema}.claim_arguments WHERE event_mention_argument_id=ANY(%s)", event_mention_ids),
                ("claim_arguments_mentions", f"SELECT count(*) FROM {schema}.claim_arguments WHERE mention_id=ANY(%s)", mention_ids),
                ("claim_evidence_mentions", f"SELECT count(*) FROM {schema}.claim_evidence WHERE mention_id=ANY(%s)", mention_ids),
                ("event_mention_links", f"SELECT count(*) FROM {schema}.event_mention_links WHERE event_mention_id=ANY(%s)", event_mention_ids),
                ("event_mention_members_event_mentions", f"SELECT count(*) FROM {schema}.event_mention_members WHERE event_mention_id=ANY(%s)", event_mention_ids),
                ("event_mention_members_mentions", f"SELECT count(*) FROM {schema}.event_mention_members WHERE mention_id=ANY(%s)", mention_ids),
                ("event_transitions", f"SELECT count(*) FROM {schema}.event_transitions WHERE source_event_mention_id=ANY(%s)", event_mention_ids),
                ("measurement_facts_mentions", f"SELECT count(*) FROM {schema}.measurement_facts WHERE source_mention_id=ANY(%s)", mention_ids),
                ("cross_run_mention_relations", f"SELECT count(*) FROM {schema}.mention_relations WHERE (subject_mention_id=ANY(%s) OR object_mention_id=ANY(%s)) AND NOT (extraction_run_id=ANY(%s))", (mention_ids, mention_ids, extraction_ids)),
                ("document_family_members", f"SELECT count(*) FROM {schema}.document_family_members WHERE document_id=ANY(%s)", excluded_ids),
                ("representative_families", f"SELECT count(*) FROM {schema}.document_families WHERE representative_document_id=ANY(%s)", excluded_ids),
                ("duplicate_candidates", f"SELECT count(*) FROM {schema}.duplicate_candidates WHERE record_kind='DOCUMENT' AND ARRAY[record_id_a,record_id_b] && %s::text[]", excluded_ids),
                ("industry_taxonomies", f"SELECT count(*) FROM {schema}.industry_taxonomies WHERE source_document_version_id=ANY(%s)", excluded_version_ids),
                ("macro_observations", f"SELECT count(*) FROM {schema}.macro_observations WHERE source_document_version_id=ANY(%s)", excluded_version_ids),
                ("macro_releases", f"SELECT count(*) FROM {schema}.macro_releases WHERE source_document_version_id=ANY(%s)", excluded_version_ids),
                ("market_universe_snapshots", f"SELECT count(*) FROM {schema}.market_universe_snapshots WHERE source_document_version_id=ANY(%s)", excluded_version_ids),
            ]
            for key, query, ids in checks:
                if ids:
                    params = ids if isinstance(ids, tuple) else (ids,)
                    cur.execute(query, params)
                    canonical_dependencies[key] = cur.fetchone()[0]
                else:
                    canonical_dependencies[key] = 0
            if any(canonical_dependencies.values()):
                raise RuntimeError(f"canonical dependencies block deletion: {canonical_dependencies}")

            dependency_counts = {
                "document_versions": len(excluded_version_ids),
                "document_enrichments": len(enrichment_ids),
                "run_documents": len(run_document_keys),
                "extraction_runs": len(extraction_ids),
                "document_family_members": canonical_dependencies["document_family_members"],
                "representative_families": canonical_dependencies["representative_families"],
                "duplicate_candidates": canonical_dependencies["duplicate_candidates"],
                "industry_taxonomies": canonical_dependencies["industry_taxonomies"],
                "macro_observations": canonical_dependencies["macro_observations"],
                "macro_releases": canonical_dependencies["macro_releases"],
                "market_universe_snapshots": canonical_dependencies["market_universe_snapshots"],
                "mentions": len(mention_ids),
                "mention_resolutions": len(resolution_ids),
                "event_mentions": len(event_mention_ids),
                "claims": canonical_dependencies["claims"],
                "event_mention_links": canonical_dependencies["event_mention_links"],
                "event_transitions": canonical_dependencies["event_transitions"],
                "review_tasks_event_mentions": len(review_task_ids["EVENT_MENTION"]),
                "review_tasks_mentions": len(review_task_ids["MENTION"]),
                "review_tasks_resolutions": len(review_task_ids["RESOLUTION"]),
            }
            dependency_counts.update(canonical_dependencies)
            closure_manifest = {
                "decisions": sorted(
                    [
                        row["document_id"], row["document_version_id"], row["content_sha256"],
                        row["status"], row["report_kind"], row["reason_codes"],
                    ]
                    for row in decisions
                ),
                "excluded_version_ids": sorted(excluded_version_ids),
                "enrichment_ids": sorted(enrichment_ids),
                "run_document_keys": sorted(run_document_keys),
                "extraction_ids": sorted(extraction_ids),
                "mention_ids": sorted(mention_ids),
                "resolution_ids": sorted(resolution_ids),
                "event_mention_ids": sorted(event_mention_ids),
                "review_task_ids": sorted(
                    task_id for ids in review_task_ids.values() for task_id in ids
                ),
            }
            closure_manifest_hash = manifest_sha256(closure_manifest)
            if args.apply or args.validate_bundle:
                assert rollback_bundle is not None
                validate_rollback_bundle(
                    rollback_bundle,
                    schema=schema,
                    decisions=decisions,
                    excluded_version_ids=excluded_version_ids,
                    dependency_counts=dependency_counts,
                    closure_manifest_sha256=closure_manifest_hash,
                    dependent_rows_sha256=dependent_rows_hash,
                )

            deleted = {}
            if args.apply:
                cur.execute(
                    """SELECT t.tgenabled FROM pg_trigger t
                       JOIN pg_class c ON c.oid=t.tgrelid
                       JOIN pg_namespace n ON n.oid=c.relnamespace
                       WHERE n.nspname=%s AND c.relname='document_versions'
                         AND t.tgname='document_version_no_delete' AND NOT t.tgisinternal""",
                    (schema,),
                )
                trigger_state = cur.fetchone()
                if trigger_state != ("O",):
                    raise RuntimeError(f"document_version_no_delete must exist and be enabled: {trigger_state}")
                migration_sql = MIGRATION.read_text(encoding="utf-8")
                if schema != "market_intelligence":
                    migration_sql = migration_sql.replace("market_intelligence", schema)
                cur.execute(migration_sql, prepare=False)
                cur.executemany(
                    f"""INSERT INTO {schema}.document_scope_assessments(
                        document_scope_assessment_id,document_version_id,scope_code,classifier_version,
                        status_code,reason_codes_json,evidence_json,assessed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(document_version_id,scope_code,classifier_version) DO UPDATE SET
                        status_code=excluded.status_code,
                        reason_codes_json=excluded.reason_codes_json,
                        evidence_json=excluded.evidence_json,
                        assessed_at=excluded.assessed_at""",
                    assessment_rows,
                )
                for kind, ids in (
                    ("EVENT_MENTION", event_mention_ids),
                    ("MENTION", mention_ids),
                    ("RESOLUTION", resolution_ids),
                ):
                    if ids:
                        cur.execute(
                            f"DELETE FROM {schema}.review_tasks WHERE target_kind=%s AND target_id=ANY(%s)",
                            (kind, ids),
                        )
                        deleted[f"review_tasks_{kind.lower()}"] = cur.rowcount
                        expected_review_tasks = len(review_task_ids[kind])
                        if cur.rowcount != expected_review_tasks:
                            raise RuntimeError(
                                f"review-task delete mismatch for {kind}: expected={expected_review_tasks}, deleted={cur.rowcount}"
                            )
                cur.execute(f"DELETE FROM {schema}.run_documents WHERE document_version_id=ANY(%s)", (excluded_version_ids,))
                deleted["run_documents"] = cur.rowcount
                if cur.rowcount != dependency_counts["run_documents"]:
                    raise RuntimeError("run-document delete mismatch")
                if extraction_ids:
                    cur.execute(f"DELETE FROM {schema}.extraction_runs WHERE extraction_run_id=ANY(%s)", (extraction_ids,))
                    deleted["extraction_runs"] = cur.rowcount
                    if cur.rowcount != dependency_counts["extraction_runs"]:
                        raise RuntimeError("extraction-run delete mismatch")
                cur.execute(
                    f"ALTER TABLE {schema}.document_versions DISABLE TRIGGER document_version_no_delete"
                )
                cur.execute(f"DELETE FROM {schema}.source_documents WHERE document_id=ANY(%s)", (excluded_ids,))
                deleted["source_documents"] = cur.rowcount
                cur.execute(
                    f"ALTER TABLE {schema}.document_versions ENABLE TRIGGER document_version_no_delete"
                )
                cur.execute(
                    """SELECT t.tgenabled FROM pg_trigger t
                       JOIN pg_class c ON c.oid=t.tgrelid
                       JOIN pg_namespace n ON n.oid=c.relnamespace
                       WHERE n.nspname=%s AND c.relname='document_versions'
                         AND t.tgname='document_version_no_delete' AND NOT t.tgisinternal""",
                    (schema,),
                )
                if cur.fetchone() != ("O",):
                    raise RuntimeError("document_version_no_delete was not re-enabled")

                cur.execute(REMAINING_DISCLOSURES_SQL.format(schema=schema))
                remaining = cur.fetchone()[0]
                expected_remaining = args.expected_total - args.expected_excluded
                if remaining != expected_remaining or deleted["source_documents"] != args.expected_excluded:
                    raise RuntimeError(f"post-delete mismatch: remaining={remaining}, deleted={deleted['source_documents']}")
                cur.execute(
                    f"""SELECT status_code,count(*) FROM {schema}.document_scope_assessments
                         WHERE scope_code='CRE' AND classifier_version=%s GROUP BY status_code ORDER BY status_code""",
                    (CLASSIFIER_VERSION,),
                )
                assessment_counts = dict(cur.fetchall())
                if sum(assessment_counts.values()) != expected_remaining:
                    raise RuntimeError(f"assessment count mismatch: {assessment_counts}")
                if args.rollback_after_apply:
                    conn.rollback()
                else:
                    conn.commit()
            else:
                assessment_counts = {}
                remaining = len(decisions)
                conn.rollback()

            result_report = {
                "applied": bool(args.apply and not args.rollback_after_apply),
                "rollbackRehearsal": bool(args.rollback_after_apply),
                "classifierVersion": CLASSIFIER_VERSION,
                "assessed": len(decisions),
                "confirmed": len(partition.confirmed_ids),
                "review": len(partition.review_ids),
                "excluded": len(partition.excluded_ids),
                "remainingDisclosures": args.expected_total if args.rollback_after_apply else remaining,
                "transactionPostDeleteDisclosures": remaining if args.apply else None,
                "canonicalDependencies": canonical_dependencies,
                "dependencyCounts": dependency_counts,
                "closureManifestSha256": closure_manifest_hash,
                "dependentRowsSha256": dependent_rows_hash,
                "bundleValidated": bool(args.apply or args.validate_bundle),
                "deleted": deleted,
                "assessmentCounts": assessment_counts,
                "rollbackBundle": str(args.rollback_bundle) if args.apply else None,
                "completedAt": datetime.now(timezone.utc).isoformat(),
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result_report, ensure_ascii=False))


if __name__ == "__main__":
    main()
