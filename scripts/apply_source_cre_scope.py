#!/usr/bin/env python
"""Assess and safely remove out-of-scope NEWS or MOLIT source documents.

Dry-run is the default and writes a full-row gzip rollback bundle. Apply is
fail-closed on source counts, decision manifest, bundle hash/content, dependency
closure, schema version, and immutable-delete trigger state.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.news_cre_scope import (
    CLASSIFIER_VERSION as NEWS_CLASSIFIER_VERSION,
    classify_news_cre_scope,
)
from collector.transaction_scope import (
    POLICY_CODE as MOLIT_SCOPE_RULE_VERSION,
    classify_molit_transaction_scope,
    transaction_group_key,
)

SUPPORTED_SOURCES = {"GOOGLE_NEWS_RSS", "MOLIT_REAL_TRANSACTION"}
CLASSIFIER_VERSIONS = {
    "GOOGLE_NEWS_RSS": NEWS_CLASSIFIER_VERSION,
    "MOLIT_REAL_TRANSACTION": MOLIT_SCOPE_RULE_VERSION,
}
ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
CACHE = Path(r"C:\Users\10137\AppData\Local\hermes\cache")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LOCK_TABLES = (
    "schema_meta", "collection_sources", "source_documents", "document_versions",
    "document_scope_assessments", "document_enrichments", "run_documents",
    "extraction_runs", "document_tokens", "mentions", "mention_fragments",
    "mention_values", "mention_relations", "mention_resolutions", "event_mentions",
    "event_mention_members", "claims", "claim_arguments", "claim_evidence",
    "event_mention_links", "event_transitions", "measurement_facts",
    "document_families", "document_family_members", "review_tasks",
    "duplicate_candidates", "industry_taxonomies", "macro_observations",
    "macro_releases", "market_universe_snapshots",
)


def load_env(path: Path) -> dict[str, str]:
    out = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if IDENTIFIER.fullmatch(key.strip()):
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def value_sha256(value: object) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_dicts(cur, sql: str, params: tuple = ()) -> list[dict]:
    cur.execute(sql, params)
    cols = [column.name for column in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _latest_rows(cur, schema: str, source_code: str) -> list[dict]:
    return fetch_dicts(cur, f"""
        WITH latest AS (
            SELECT dv.*,row_number() OVER(
                PARTITION BY document_id ORDER BY version_no DESC,document_version_id DESC
            ) rn FROM {schema}.document_versions dv
        )
        SELECT sd.document_id,l.document_version_id,l.title,l.snippet_text,
               l.content_sha256,l.metadata_json,sd.publisher_name,sd.canonical_url
          FROM {schema}.source_documents sd
          JOIN {schema}.collection_sources cs ON cs.source_id=sd.source_id
          JOIN latest l ON l.document_id=sd.document_id AND l.rn=1
         WHERE cs.source_code=%s
         ORDER BY sd.document_id
    """, (source_code,))


def _news_categories(cur, schema: str) -> dict[str, tuple[str, ...]]:
    rows = cur.execute(f"""
        SELECT dv.document_id,ec.code
          FROM {schema}.run_documents rd
          JOIN {schema}.document_versions dv ON dv.document_version_id=rd.document_version_id
          JOIN {schema}.collection_runs cr ON cr.run_id=rd.run_id
          JOIN {schema}.collection_job_categories cjc ON cjc.job_id=cr.job_id
          JOIN {schema}.event_categories ec ON ec.event_category_id=cjc.event_category_id
         GROUP BY dv.document_id,ec.code
    """).fetchall()
    grouped: dict[str, set[str]] = defaultdict(set)
    for document_id, code in rows:
        grouped[document_id].add(code)
    return {key: tuple(sorted(values)) for key, values in grouped.items()}


def classify_documents(cur, schema: str, source_code: str) -> list[dict]:
    rows = _latest_rows(cur, schema, source_code)
    decisions: list[dict] = []
    if source_code == "GOOGLE_NEWS_RSS":
        categories = _news_categories(cur, schema)
        for row in rows:
            codes = categories.get(row["document_id"], ())
            result = classify_news_cre_scope(
                title=row["title"], snippet=row["snippet_text"], category_codes=codes
            )
            decisions.append({
                "document_id": row["document_id"],
                "document_version_id": row["document_version_id"],
                "content_sha256": row["content_sha256"],
                "status": result.status_code,
                "reason_codes": list(result.reason_codes),
                "evidence": {"categoryCodes": list(codes)},
            })
        return decisions

    records: list[tuple[dict, dict, object]] = []
    group_totals: dict[tuple, Decimal] = defaultdict(Decimal)
    group_counts: dict[tuple, int] = defaultdict(int)
    for row in rows:
        metadata = row["metadata_json"] if isinstance(row["metadata_json"], dict) else json.loads(row["metadata_json"] or "{}")
        record = metadata.get("api_record") if isinstance(metadata, dict) else None
        if not isinstance(record, dict):
            record = {}
        scope = classify_molit_transaction_scope(record)
        key = transaction_group_key(record)
        area = scope.building_area_m2 or Decimal("0")
        group_totals[key] += area
        group_counts[key] += 1
        records.append((row, record, scope))
    for row, record, scope in records:
        key = transaction_group_key(record)
        if scope.status == "IN_SCOPE":
            status, reasons = "CRE_CONFIRMED", []
        elif scope.status == "REVIEW_REQUIRED":
            status, reasons = "CRE_REVIEW_AREA_1000_3300", [scope.reason_code]
        elif scope.reason_code == "OUT_OF_SCOPE_RESIDENTIAL_USE":
            status, reasons = "OUT_OF_SCOPE_RESIDENTIAL", [scope.reason_code]
        elif scope.reason_code == "OUT_OF_SCOPE_AREA_MISSING":
            status, reasons = "CRE_REVIEW_PARSE_FAILED", [scope.reason_code]
        else:
            status, reasons = "OUT_OF_SCOPE_NON_CRE", [scope.reason_code]
        if scope.reason_code == "OUT_OF_SCOPE_AREA_LE_1000_M2" and group_totals[key] > Decimal("3300"):
            status = "CRE_REVIEW_GROUP_GT_3300"
            reasons = ["GROUP_BUILDING_AREA_GT_3300"]
        decisions.append({
            "document_id": row["document_id"],
            "document_version_id": row["document_version_id"],
            "content_sha256": row["content_sha256"],
            "status": status,
            "reason_codes": reasons,
            "evidence": {
                "buildingAreaSqm": str(scope.building_area_m2) if scope.building_area_m2 is not None else None,
                "groupBuildingAreaSqm": str(group_totals[key]),
                "groupRowCount": group_counts[key],
                "transactionGroupKey": key,
            },
        })
    return decisions


def partition(decisions: list[dict]) -> tuple[list[str], list[str], list[str]]:
    confirmed = [row["document_id"] for row in decisions if row["status"] == "CRE_CONFIRMED"]
    review = [row["document_id"] for row in decisions if row["status"].startswith("CRE_REVIEW")]
    excluded = [row["document_id"] for row in decisions if row["status"].startswith("OUT_OF_SCOPE_")]
    return confirmed, review, excluded


def assessment_rows(decisions: list[dict], classifier_version: str, assessed_at: str) -> list[tuple]:
    rows = []
    for decision in decisions:
        if decision["status"].startswith("OUT_OF_SCOPE_"):
            continue
        canonical_status = "CRE_CONFIRMED" if decision["status"] == "CRE_CONFIRMED" else "CRE_REVIEW"
        evidence = dict(decision["evidence"])
        evidence["nativeStatusCode"] = decision["status"]
        assessment_id = hashlib.sha256(
            f"document-scope:{decision['document_version_id']}:CRE:{classifier_version}".encode()
        ).hexdigest()[:32]
        rows.append((
            assessment_id, decision["document_version_id"], "CRE", classifier_version,
            canonical_status, json.dumps(decision["reason_codes"], ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False, default=str), assessed_at,
        ))
    return rows


def gather_closure(cur, schema: str, excluded_ids: list[str]) -> dict:
    versions = fetch_dicts(cur, f"SELECT * FROM {schema}.document_versions WHERE document_id=ANY(%s) ORDER BY document_version_id", (excluded_ids,))
    version_ids = [row["document_version_id"] for row in versions]
    extraction_ids = [row[0] for row in cur.execute(
        f"SELECT extraction_run_id FROM {schema}.extraction_runs WHERE document_version_id=ANY(%s)", (version_ids,)
    ).fetchall()]
    mention_ids = [row[0] for row in cur.execute(
        f"SELECT mention_id FROM {schema}.mentions WHERE extraction_run_id=ANY(%s)", (extraction_ids,)
    ).fetchall()]
    event_mention_ids = [row[0] for row in cur.execute(
        f"SELECT event_mention_id FROM {schema}.event_mentions WHERE extraction_run_id=ANY(%s)", (extraction_ids,)
    ).fetchall()]
    resolution_ids = [row[0] for row in cur.execute(
        f"SELECT mention_resolution_id FROM {schema}.mention_resolutions WHERE mention_id=ANY(%s)", (mention_ids,)
    ).fetchall()]
    rows = {
        "document_scope_assessments": fetch_dicts(cur, f"SELECT * FROM {schema}.document_scope_assessments WHERE document_version_id=ANY(%s) ORDER BY document_scope_assessment_id", (version_ids,)),
        "document_enrichments": fetch_dicts(cur, f"SELECT * FROM {schema}.document_enrichments WHERE document_version_id=ANY(%s) ORDER BY document_enrichment_id", (version_ids,)),
        "run_documents": fetch_dicts(cur, f"SELECT * FROM {schema}.run_documents WHERE document_version_id=ANY(%s) ORDER BY run_id,document_version_id", (version_ids,)),
        "extraction_runs": fetch_dicts(cur, f"SELECT * FROM {schema}.extraction_runs WHERE extraction_run_id=ANY(%s) ORDER BY extraction_run_id", (extraction_ids,)),
        "document_tokens": fetch_dicts(cur, f"SELECT * FROM {schema}.document_tokens WHERE extraction_run_id=ANY(%s) ORDER BY extraction_run_id,token_index", (extraction_ids,)),
        "mentions": fetch_dicts(cur, f"SELECT * FROM {schema}.mentions WHERE mention_id=ANY(%s) ORDER BY mention_id", (mention_ids,)),
        "mention_fragments": fetch_dicts(cur, f"SELECT * FROM {schema}.mention_fragments WHERE mention_id=ANY(%s) ORDER BY mention_id,fragment_no", (mention_ids,)),
        "mention_values": fetch_dicts(cur, f"SELECT * FROM {schema}.mention_values WHERE mention_id=ANY(%s) ORDER BY mention_id", (mention_ids,)),
        "mention_relations": fetch_dicts(cur, f"SELECT * FROM {schema}.mention_relations WHERE extraction_run_id=ANY(%s) ORDER BY mention_relation_id", (extraction_ids,)),
        "mention_resolutions": fetch_dicts(cur, f"SELECT * FROM {schema}.mention_resolutions WHERE mention_resolution_id=ANY(%s) ORDER BY mention_resolution_id", (resolution_ids,)),
        "event_mentions": fetch_dicts(cur, f"SELECT * FROM {schema}.event_mentions WHERE event_mention_id=ANY(%s) ORDER BY event_mention_id", (event_mention_ids,)),
        "event_mention_members": fetch_dicts(cur, f"SELECT * FROM {schema}.event_mention_members WHERE event_mention_id=ANY(%s) ORDER BY event_mention_id,mention_id,semantic_role", (event_mention_ids,)),
        "review_tasks": fetch_dicts(cur, f"""SELECT * FROM {schema}.review_tasks WHERE
            (target_kind='EVENT_MENTION' AND target_id=ANY(%s)) OR
            (target_kind='MENTION' AND target_id=ANY(%s)) OR
            (target_kind='RESOLUTION' AND target_id=ANY(%s)) ORDER BY review_task_id""", (event_mention_ids, mention_ids, resolution_ids)),
    }
    source_documents = fetch_dicts(cur, f"SELECT * FROM {schema}.source_documents WHERE document_id=ANY(%s) ORDER BY document_id", (excluded_ids,))
    blockers: dict[str, int] = {}
    checks = {
        "claims_event_mentions": (f"SELECT count(*) FROM {schema}.claims WHERE event_mention_id=ANY(%s)", (event_mention_ids,)),
        "claims_mentions": (f"SELECT count(*) FROM {schema}.claims WHERE subject_mention_id=ANY(%s) OR object_mention_id=ANY(%s)", (mention_ids, mention_ids)),
        "claim_arguments_event_mentions": (f"SELECT count(*) FROM {schema}.claim_arguments WHERE event_mention_argument_id=ANY(%s)", (event_mention_ids,)),
        "claim_arguments_mentions": (f"SELECT count(*) FROM {schema}.claim_arguments WHERE mention_id=ANY(%s)", (mention_ids,)),
        "claim_evidence_mentions": (f"SELECT count(*) FROM {schema}.claim_evidence WHERE mention_id=ANY(%s)", (mention_ids,)),
        "event_mention_links": (f"SELECT count(*) FROM {schema}.event_mention_links WHERE event_mention_id=ANY(%s)", (event_mention_ids,)),
        "event_transitions": (f"SELECT count(*) FROM {schema}.event_transitions WHERE source_event_mention_id=ANY(%s)", (event_mention_ids,)),
        "measurement_facts": (f"SELECT count(*) FROM {schema}.measurement_facts WHERE source_mention_id=ANY(%s)", (mention_ids,)),
        "cross_run_relations": (f"SELECT count(*) FROM {schema}.mention_relations WHERE (subject_mention_id=ANY(%s) OR object_mention_id=ANY(%s)) AND NOT extraction_run_id=ANY(%s)", (mention_ids, mention_ids, extraction_ids)),
        "document_family_members": (f"SELECT count(*) FROM {schema}.document_family_members WHERE document_id=ANY(%s)", (excluded_ids,)),
        "representative_families": (f"SELECT count(*) FROM {schema}.document_families WHERE representative_document_id=ANY(%s)", (excluded_ids,)),
        "duplicate_candidates": (f"SELECT count(*) FROM {schema}.duplicate_candidates WHERE record_kind='DOCUMENT' AND ARRAY[record_id_a,record_id_b] && %s::text[]", (excluded_ids,)),
        "industry_taxonomies": (f"SELECT count(*) FROM {schema}.industry_taxonomies WHERE source_document_version_id=ANY(%s)", (version_ids,)),
        "macro_observations": (f"SELECT count(*) FROM {schema}.macro_observations WHERE source_document_version_id=ANY(%s)", (version_ids,)),
        "macro_releases": (f"SELECT count(*) FROM {schema}.macro_releases WHERE source_document_version_id=ANY(%s)", (version_ids,)),
        "market_universe_snapshots": (f"SELECT count(*) FROM {schema}.market_universe_snapshots WHERE source_document_version_id=ANY(%s)", (version_ids,)),
    }
    for key, (sql, params) in checks.items():
        blockers[key] = cur.execute(sql, params).fetchone()[0]
    return {
        "source_documents": source_documents, "document_versions": versions,
        "dependent_rows": rows, "blockers": blockers,
        "version_ids": version_ids, "extraction_ids": extraction_ids,
        "mention_ids": mention_ids, "event_mention_ids": event_mention_ids,
        "resolution_ids": resolution_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-code", choices=sorted(SUPPORTED_SOURCES), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback-after-apply", action="store_true")
    parser.add_argument("--expected-total", type=int, required=True)
    parser.add_argument("--expected-excluded", type=int, required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--rollback-bundle", type=Path)
    parser.add_argument("--expected-backup-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.rollback_after_apply and not args.apply:
        raise SystemExit("--rollback-after-apply requires --apply")
    classifier_version = CLASSIFIER_VERSIONS[args.source_code]
    slug = args.source_code.lower()
    bundle_path = args.rollback_bundle or CACHE / f"cre-db-{slug}-scope-rollback.json.gz"
    output_path = args.output or CACHE / f"cre-db-{slug}-scope-result.json"
    if args.apply and not all((args.expected_manifest_sha256, args.expected_backup_sha256)):
        raise SystemExit("apply requires --expected-manifest-sha256 and --expected-backup-sha256")
    if args.apply and (not bundle_path.is_file() or file_sha256(bundle_path) != args.expected_backup_sha256):
        raise SystemExit("rollback bundle missing or hash mismatch")

    import psycopg
    env = load_env(ENV)
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    if not IDENTIFIER.fullmatch(schema):
        raise SystemExit("invalid schema")
    assessed_at = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(env["SUPABASE_DB_URL"], connect_timeout=20) as conn:
        with conn.cursor() as cur:
            if args.apply:
                cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                cur.execute("SET LOCAL statement_timeout = '5min'")
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"{args.source_code}:{classifier_version}:hard-delete",))
                cur.execute("LOCK TABLE " + ",".join(f"{schema}.{table}" for table in LOCK_TABLES) + " IN SHARE MODE")
            else:
                cur.execute("BEGIN READ ONLY")
            version = cur.execute(f"SELECT schema_value FROM {schema}.schema_meta WHERE schema_key='schema_version'").fetchone()
            if version != ("2.9.0",):
                raise RuntimeError(f"expected schema 2.9.0, found {version}")
            decisions = classify_documents(cur, schema, args.source_code)
            confirmed, review, excluded = partition(decisions)
            if len(decisions) != args.expected_total or len(excluded) != args.expected_excluded:
                raise RuntimeError(f"count mismatch total={len(decisions)} excluded={len(excluded)}")
            manifest = {
                "sourceCode": args.source_code,
                "classifierVersion": classifier_version,
                "decisions": sorted((d["document_id"], d["document_version_id"], d["content_sha256"], d["status"], d["reason_codes"], d["evidence"]) for d in decisions),
            }
            manifest_hash = value_sha256(manifest)
            if args.expected_manifest_sha256 and manifest_hash != args.expected_manifest_sha256:
                raise RuntimeError("decision manifest hash mismatch")
            closure = gather_closure(cur, schema, excluded)
            if any(closure["blockers"].values()):
                raise RuntimeError(f"canonical dependencies block deletion: {closure['blockers']}")
            closure_identity = {
                "excludedDocumentIds": sorted(excluded),
                "excludedVersionIds": sorted(closure["version_ids"]),
                "extractionIds": sorted(closure["extraction_ids"]),
                "mentionIds": sorted(closure["mention_ids"]),
                "eventMentionIds": sorted(closure["event_mention_ids"]),
                "resolutionIds": sorted(closure["resolution_ids"]),
            }
            bundle = {
                "policy": "HARD_DELETE_OUT_OF_SCOPE_KEEP_REVIEW",
                "schema": schema, "source_code": args.source_code,
                "classifier_version": classifier_version,
                "manifest_sha256": manifest_hash,
                "closure_identity": closure_identity,
                "closure_identity_sha256": value_sha256(closure_identity),
                "excluded_source_documents": closure["source_documents"],
                "excluded_document_versions": closure["document_versions"],
                "dependent_rows": closure["dependent_rows"],
                "dependent_rows_sha256": value_sha256(closure["dependent_rows"]),
                "blockers": closure["blockers"],
                "created_at": assessed_at,
            }
            if args.apply:
                with gzip.open(bundle_path, "rt", encoding="utf-8") as handle:
                    expected_bundle = json.load(handle)
                for key in ("policy", "schema", "source_code", "classifier_version", "manifest_sha256", "closure_identity_sha256", "dependent_rows_sha256"):
                    if expected_bundle.get(key) != bundle.get(key):
                        raise RuntimeError(f"rollback bundle {key} mismatch")
                if expected_bundle.get("excluded_source_documents") != json.loads(stable_json(bundle["excluded_source_documents"])):
                    raise RuntimeError("rollback bundle source rows mismatch")
                if expected_bundle.get("excluded_document_versions") != json.loads(stable_json(bundle["excluded_document_versions"])):
                    raise RuntimeError("rollback bundle version rows mismatch")
                if expected_bundle.get("dependent_rows") != json.loads(stable_json(bundle["dependent_rows"])):
                    raise RuntimeError("rollback bundle dependent rows mismatch")
            else:
                bundle_path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(bundle_path, "wt", encoding="utf-8") as handle:
                    json.dump(bundle, handle, ensure_ascii=False, sort_keys=True, default=str)

            deleted: dict[str, int] = {}
            assessment_counts: dict[str, int] = {}
            remaining = len(decisions)
            if args.apply:
                trigger = cur.execute("""SELECT t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname='document_versions'
                    AND t.tgname='document_version_no_delete' AND NOT t.tgisinternal""", (schema,)).fetchone()
                if trigger != ("O",):
                    raise RuntimeError(f"immutable delete trigger is not enabled: {trigger}")
                rows = assessment_rows(decisions, classifier_version, assessed_at)
                cur.executemany(f"""INSERT INTO {schema}.document_scope_assessments(
                    document_scope_assessment_id,document_version_id,scope_code,classifier_version,status_code,
                    reason_codes_json,evidence_json,assessed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(document_version_id,scope_code,classifier_version) DO UPDATE SET
                    status_code=excluded.status_code,reason_codes_json=excluded.reason_codes_json,
                    evidence_json=excluded.evidence_json,assessed_at=excluded.assessed_at""", rows)
                event_ids, mention_ids, resolution_ids = closure["event_mention_ids"], closure["mention_ids"], closure["resolution_ids"]
                for kind, ids in (("EVENT_MENTION", event_ids), ("MENTION", mention_ids), ("RESOLUTION", resolution_ids)):
                    cur.execute(f"DELETE FROM {schema}.review_tasks WHERE target_kind=%s AND target_id=ANY(%s)", (kind, ids))
                    deleted[f"review_tasks_{kind.lower()}"] = cur.rowcount
                cur.execute(f"DELETE FROM {schema}.run_documents WHERE document_version_id=ANY(%s)", (closure["version_ids"],))
                deleted["run_documents"] = cur.rowcount
                cur.execute(f"DELETE FROM {schema}.extraction_runs WHERE extraction_run_id=ANY(%s)", (closure["extraction_ids"],))
                deleted["extraction_runs"] = cur.rowcount
                cur.execute(f"ALTER TABLE {schema}.document_versions DISABLE TRIGGER document_version_no_delete")
                deleted["source_documents"] = 0
                for start in range(0, len(excluded), 1000):
                    batch = excluded[start:start + 1000]
                    cur.execute(f"DELETE FROM {schema}.source_documents WHERE document_id=ANY(%s)", (batch,))
                    deleted["source_documents"] += cur.rowcount
                cur.execute(f"ALTER TABLE {schema}.document_versions ENABLE TRIGGER document_version_no_delete")
                trigger = cur.execute("""SELECT t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname='document_versions'
                    AND t.tgname='document_version_no_delete' AND NOT t.tgisinternal""", (schema,)).fetchone()
                if trigger != ("O",):
                    raise RuntimeError("immutable delete trigger was not re-enabled")
                remaining = cur.execute(f"""SELECT count(*) FROM {schema}.source_documents sd
                    JOIN {schema}.collection_sources cs ON cs.source_id=sd.source_id WHERE cs.source_code=%s""", (args.source_code,)).fetchone()[0]
                if deleted["source_documents"] != args.expected_excluded or remaining != args.expected_total - args.expected_excluded:
                    raise RuntimeError(f"post-delete mismatch remaining={remaining} deleted={deleted['source_documents']}")
                assessment_counts = dict(cur.execute(f"""SELECT dsa.status_code,count(*) FROM {schema}.document_scope_assessments dsa
                    JOIN {schema}.document_versions dv ON dv.document_version_id=dsa.document_version_id
                    JOIN {schema}.source_documents sd ON sd.document_id=dv.document_id
                    JOIN {schema}.collection_sources cs ON cs.source_id=sd.source_id
                    WHERE cs.source_code=%s AND dsa.classifier_version=%s GROUP BY dsa.status_code""", (args.source_code, classifier_version)).fetchall())
                if sum(assessment_counts.values()) != remaining:
                    raise RuntimeError(f"assessment count mismatch: {assessment_counts}")
                if args.rollback_after_apply:
                    conn.rollback()
                else:
                    conn.commit()
            else:
                conn.rollback()

    report = {
        "sourceCode": args.source_code, "classifierVersion": classifier_version,
        "applied": bool(args.apply and not args.rollback_after_apply),
        "rollbackRehearsal": bool(args.rollback_after_apply),
        "assessed": len(decisions), "confirmed": len(confirmed), "review": len(review),
        "excluded": len(excluded), "remainingInTransaction": remaining,
        "manifestSha256": manifest_hash, "closureIdentitySha256": bundle["closure_identity_sha256"],
        "dependentRowsSha256": bundle["dependent_rows_sha256"],
        "rollbackBundle": str(bundle_path), "rollbackBundleSha256": file_sha256(bundle_path),
        "blockers": closure["blockers"],
        "dependencyCounts": {key: len(value) for key, value in closure["dependent_rows"].items()},
        "deleted": deleted, "assessmentCounts": assessment_counts,
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
