"""Enrich existing contextual projections with deterministic provenance.

Only contextual_* derived tables are updated. Immutable source documents and
versions are guarded by count + canonical hash invariance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backfill_contextual_intelligence import MODEL_VERSION, PIPELINE_VERSION, RULE_VERSION, TAXONOMY_VERSION

DEFAULT_DB = ROOT / "data/market.db"


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _merge(raw: str | None, additions: dict[str, object]) -> str:
    value = json.loads(raw or "{}")
    value.update(additions)
    return _stable_json(value)


def _source_guard(conn: sqlite3.Connection) -> tuple[int, int, str]:
    count_documents = conn.execute("SELECT count(*) FROM source_documents").fetchone()[0]
    rows = conn.execute(
        """SELECT document_version_id,document_id,version_no,content_sha256,title,
                  snippet_text,stored_text,published_at,collected_at
           FROM document_versions ORDER BY document_version_id"""
    ).fetchall()
    return count_documents, len(rows), _hash(rows)


def enrich(conn: sqlite3.Connection, *, apply: bool = False) -> dict[str, object]:
    guard_before = _source_guard(conn)
    report: dict[str, object] = {
        "status": "applied" if apply else "rollback_rehearsal",
        "campaignsUpdated": 0,
        "runsUpdated": 0,
        "framesUpdated": 0,
        "searchRecordsUpdated": 0,
    }
    conn.execute("SAVEPOINT contextual_provenance")
    try:
        generation_by_campaign: dict[str, tuple[str, str]] = {}
        campaigns = conn.execute(
            """SELECT campaign_id,metadata_json,taxonomy_version,rule_set_version,
                      model_version,pipeline_version
               FROM contextual_processing_campaigns ORDER BY campaign_id"""
        ).fetchall()
        for campaign_id, metadata, taxonomy, rules, model, pipeline in campaigns:
            manifest = [
                {"documentVersionId": row[0], "contentSha256": row[1]}
                for row in conn.execute(
                    """SELECT document_version_id,input_sha256
                       FROM contextual_document_runs WHERE campaign_id=? ORDER BY document_version_id""",
                    (campaign_id,),
                )
            ]
            manifest_hash = _hash(manifest)
            generation_key = _hash({
                "inputManifestSha256": manifest_hash,
                "taxonomyVersion": taxonomy,
                "ruleVersion": rules,
                "modelVersion": model,
                "pipelineVersion": pipeline,
            })
            generation_by_campaign[campaign_id] = (manifest_hash, generation_key)
            updated = _merge(metadata, {
                "inputManifestSha256": manifest_hash,
                "generationKey": generation_key,
            })
            if updated != metadata:
                report["campaignsUpdated"] = int(report["campaignsUpdated"]) + conn.execute(
                    "UPDATE contextual_processing_campaigns SET metadata_json=? WHERE campaign_id=?",
                    (updated, campaign_id),
                ).rowcount
            for run_id, run_metadata in conn.execute(
                "SELECT contextual_run_id,metadata_json FROM contextual_document_runs WHERE campaign_id=?",
                (campaign_id,),
            ):
                run_updated = _merge(run_metadata, {
                    "inputManifestSha256": manifest_hash,
                    "generationKey": generation_key,
                })
                if run_updated != run_metadata:
                    report["runsUpdated"] = int(report["runsUpdated"]) + conn.execute(
                        "UPDATE contextual_document_runs SET metadata_json=? WHERE contextual_run_id=?",
                        (run_updated, run_id),
                    ).rowcount

        frame_rows = conn.execute(
            """SELECT f.frame_id,r.campaign_id,f.event_domain,f.event_type,f.stage_code,
                      f.process_type,f.action_code,f.title,f.evidence_text,f.modality_code,
                      f.polarity_code,f.metadata_json,f.document_version_id,dv.title,
                      dv.snippet_text,dv.stored_text
               FROM contextual_event_frames f
               JOIN contextual_document_runs r ON r.contextual_run_id=f.contextual_run_id
               JOIN document_versions dv ON dv.document_version_id=f.document_version_id
               ORDER BY f.frame_id"""
        ).fetchall()
        output_by_frame: dict[str, str] = {}
        for row in frame_rows:
            (frame_id, campaign_id, domain, event_type, stage, process, action, title,
             evidence, modality, polarity, metadata, version_id, doc_title, snippet, stored) = row
            manifest_hash, generation_key = generation_by_campaign[campaign_id]
            current_metadata = json.loads(metadata or "{}")
            output_hash = _hash({
                "eventDomain": domain,
                "eventType": event_type,
                "stageCode": stage,
                "processType": process,
                "actionCode": action,
                "title": title,
                "evidenceText": evidence,
                "modalityCode": modality,
                "polarityCode": polarity,
                "matchedFeatures": current_metadata.get("matchedFeatures", []),
            })
            output_by_frame[frame_id] = output_hash
            text = "\n".join(str(item) for item in (doc_title, snippet, stored) if item)
            start = text.find(evidence)
            start_value = start if start >= 0 else None
            end_value = start + len(evidence) if start >= 0 else None
            locator = f"document_version:{version_id}#chars={start_value}:{end_value}"
            updated_metadata = _merge(metadata, {
                "inputManifestSha256": manifest_hash,
                "generationKey": generation_key,
                "outputSha256": output_hash,
            })
            existing = conn.execute(
                "SELECT evidence_start,evidence_end,evidence_locator,metadata_json FROM contextual_event_frames WHERE frame_id=?",
                (frame_id,),
            ).fetchone()
            desired = (start_value, end_value, locator, updated_metadata)
            if existing != desired:
                report["framesUpdated"] = int(report["framesUpdated"]) + conn.execute(
                    """UPDATE contextual_event_frames
                       SET evidence_start=?,evidence_end=?,evidence_locator=?,metadata_json=?
                       WHERE frame_id=?""",
                    (*desired, frame_id),
                ).rowcount

        for search_id, campaign_id, frame_id, mode, metadata, locator, assets in conn.execute(
            """SELECT search_record_id,campaign_id,frame_id,record_mode,metadata_json,
                      evidence_locator,asset_ids_json
               FROM contextual_search_records ORDER BY search_record_id"""
        ):
            manifest_hash, generation_key = generation_by_campaign[campaign_id]
            additions: dict[str, object] = {
                "inputManifestSha256": manifest_hash,
                "generationKey": generation_key,
            }
            if frame_id and frame_id in output_by_frame:
                additions["outputSha256"] = output_by_frame[frame_id]
            updated_metadata = _merge(metadata, additions)
            new_locator = locator
            if frame_id:
                new_locator = conn.execute(
                    "SELECT evidence_locator FROM contextual_event_frames WHERE frame_id=?",
                    (frame_id,),
                ).fetchone()[0]
            new_assets = assets
            if mode == "CANDIDATE" and frame_id:
                canonical_assets = [
                    row[0] for row in conn.execute(
                        """SELECT target_id FROM contextual_frame_targets
                           WHERE frame_id=? AND target_kind='ASSET' AND target_id IS NOT NULL
                           ORDER BY target_id""",
                        (frame_id,),
                    )
                ]
                new_assets = _stable_json(canonical_assets)
            desired = (new_locator, new_assets, updated_metadata)
            if (locator, assets, metadata) != desired:
                report["searchRecordsUpdated"] = int(report["searchRecordsUpdated"]) + conn.execute(
                    """UPDATE contextual_search_records
                       SET evidence_locator=?,asset_ids_json=?,metadata_json=? WHERE search_record_id=?""",
                    (*desired, search_id),
                ).rowcount

        if _source_guard(conn) != guard_before:
            raise RuntimeError("source/document guard changed during contextual provenance enrichment")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("foreign-key violation after contextual provenance enrichment")
        if apply:
            conn.execute("RELEASE contextual_provenance")
            conn.commit()
        else:
            conn.execute("ROLLBACK TO contextual_provenance")
            conn.execute("RELEASE contextual_provenance")
        return report
    except Exception:
        conn.execute("ROLLBACK TO contextual_provenance")
        conn.execute("RELEASE contextual_provenance")
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()
    candidate = args.db.with_suffix(args.db.suffix + ".contextual-provenance-candidate")
    if candidate.exists():
        candidate.chmod(candidate.stat().st_mode | stat.S_IWRITE)
        candidate.unlink()
    shutil.copy2(args.db, candidate)
    candidate.chmod(candidate.stat().st_mode | stat.S_IWRITE)
    conn = sqlite3.connect(candidate)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        report = enrich(conn, apply=args.apply)
        if args.apply:
            rerun = enrich(conn, apply=True)
            changed = sum(int(value) for key, value in rerun.items() if key.endswith("Updated"))
            if changed:
                raise RuntimeError(f"contextual provenance rerun was not idempotent: {rerun}")
    finally:
        conn.close()
    if args.apply:
        if args.backup:
            backup = args.db.with_suffix(args.db.suffix + ".pre-contextual-provenance.bak")
            if backup.exists():
                backup.chmod(backup.stat().st_mode | stat.S_IWRITE)
                backup.unlink()
            shutil.copy2(args.db, backup)
        original_mode = stat.S_IMODE(args.db.stat().st_mode)
        args.db.chmod(original_mode | stat.S_IWRITE)
        try:
            os.replace(candidate, args.db)
        finally:
            args.db.chmod(original_mode)
    else:
        candidate.unlink()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
