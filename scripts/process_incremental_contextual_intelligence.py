"""Incremental contextual-event projection for SQLite and PostgreSQL.

The writer is additive, deterministic, candidate-only, and transaction-neutral:
the caller owns commit/rollback so it can run inside the daily RSS savepoint.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from typing import Any, Iterable

from scripts.backfill_contextual_intelligence import (
    MODEL_VERSION,
    PIPELINE_VERSION,
    RULE_VERSION,
    TAXONOMY_VERSION,
    FrameCandidate,
    _source_grade,
    _stable_id,
    classify_contextual_frames,
)

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_sqlite(conn: Any) -> bool:
    return isinstance(conn, sqlite3.Connection)


def _table(schema: str | None, name: str) -> str:
    if not IDENTIFIER.fullmatch(name) or (schema and not IDENTIFIER.fullmatch(schema)):
        raise ValueError("invalid SQL identifier")
    return f'"{schema}"."{name}"' if schema else f'"{name}"'


def _placeholder(conn: Any) -> str:
    return "?" if _is_sqlite(conn) else "%s"


def _json_value(conn: Any, value: object) -> object:
    if _is_sqlite(conn):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    from psycopg.types.json import Jsonb
    return Jsonb(value)


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _insert(conn: Any, schema: str | None, table: str, values: dict[str, object]) -> int:
    ph = _placeholder(conn)
    columns = list(values)
    sql = (
        f"INSERT INTO {_table(schema, table)}({','.join(columns)}) "
        f"VALUES({','.join([ph] * len(columns))}) ON CONFLICT DO NOTHING"
    )
    cursor = conn.execute(sql, tuple(values[column] for column in columns))
    return max(0, int(cursor.rowcount or 0))


def _fetch_documents(conn: Any, schema: str | None, version_ids: list[str]) -> list[dict[str, Any]]:
    if not version_ids:
        return []
    ph = _placeholder(conn)
    cursor = conn.execute(
        f"""SELECT dv.document_version_id,dv.document_id,dv.content_sha256,dv.title,
                   dv.snippet_text,dv.stored_text,dv.published_at,dv.collected_at,
                   sd.document_type,sd.publisher_name,cs.source_code
            FROM {_table(schema,'document_versions')} dv
            JOIN {_table(schema,'source_documents')} sd ON sd.document_id=dv.document_id
            LEFT JOIN {_table(schema,'collection_sources')} cs ON cs.source_id=sd.source_id
            WHERE dv.document_version_id IN ({','.join([ph] * len(version_ids))})
            ORDER BY dv.document_version_id""",
        tuple(version_ids),
    )
    names = [column.name if hasattr(column, "name") else column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _already_processed_versions(conn: Any, schema: str | None, version_ids: list[str]) -> set[str]:
    if not version_ids:
        return set()
    ph = _placeholder(conn)
    cursor = conn.execute(
        f"""SELECT DISTINCT run.document_version_id
            FROM {_table(schema,'contextual_document_runs')} run
            JOIN {_table(schema,'contextual_processing_campaigns')} campaign
              ON campaign.campaign_id=run.campaign_id
            WHERE run.document_version_id IN ({','.join([ph] * len(version_ids))})
              AND campaign.rule_set_version={ph}
              AND campaign.model_version={ph}
              AND campaign.pipeline_version={ph}
              AND run.status_code IN (
                'COMPLETED','NO_CONTEXTUAL_EVENT','INSUFFICIENT_CONTENT','ENTITY_UNRESOLVED'
              )""",
        (*version_ids, RULE_VERSION, MODEL_VERSION, PIPELINE_VERSION),
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _source_grade_for(row: dict[str, Any]) -> str:
    # _source_grade only relies on mapping access, despite its SQLite Row annotation.
    return _source_grade(row)  # type: ignore[arg-type]


def _frame_payload(frame: FrameCandidate) -> dict[str, object]:
    return {
        "eventDomain": frame.event_domain,
        "eventType": frame.event_type,
        "stageCode": frame.stage_code,
        "processType": frame.process_type,
        "actionCode": frame.action_code,
        "title": frame.title,
        "evidenceText": frame.evidence_text,
        "modalityCode": frame.modality_code,
        "polarityCode": frame.polarity_code,
        "matchedFeatures": list(frame.matched_features),
    }


def process_contextual_document_versions(
    conn: Any,
    *,
    document_version_ids: Iterable[str],
    schema: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    requested = sorted(set(str(item) for item in document_version_ids))
    rows = _fetch_documents(conn, schema, requested)
    if len(rows) != len(requested):
        found = {str(row["document_version_id"]) for row in rows}
        raise RuntimeError(f"contextual input versions missing: {sorted(set(requested) - found)[:5]}")
    already_processed = _already_processed_versions(conn, schema, requested)
    rows = [row for row in rows if str(row["document_version_id"]) not in already_processed]

    manifest = [
        {"documentVersionId": row["document_version_id"], "contentSha256": row["content_sha256"]}
        for row in rows
    ]
    input_manifest_sha256 = hashlib.sha256(_stable_json(manifest).encode("utf-8")).hexdigest()
    generation_key = hashlib.sha256(
        _stable_json({
            "inputManifestSha256": input_manifest_sha256,
            "taxonomyVersion": TAXONOMY_VERSION,
            "ruleVersion": RULE_VERSION,
            "modelVersion": MODEL_VERSION,
            "pipelineVersion": PIPELINE_VERSION,
        }).encode("utf-8")
    ).hexdigest()
    campaign_code = f"CONTEXTUAL_DAILY_{generation_key[:24]}"
    campaign_id = _stable_id("ctxcamp", campaign_code)
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    cutoff = max((str(row.get("collected_at") or now) for row in rows), default=now)

    planned_frames: list[tuple[dict[str, Any], str, list[FrameCandidate]]] = []
    for row in rows:
        parts = [row.get("title"), row.get("snippet_text"), row.get("stored_text")]
        text = "\n".join(str(item) for item in parts if item)
        planned_frames.append((row, text, classify_contextual_frames(text)))

    result: dict[str, Any] = {
        "campaignCode": campaign_code,
        "inputManifestSha256": input_manifest_sha256,
        "generationKey": generation_key,
        "documentsRequested": len(requested),
        "documentsAlreadyProcessed": len(already_processed),
        "documents": len(rows),
        "framesPlanned": sum(len(frames) for _, _, frames in planned_frames),
        "campaignsInserted": 0,
        "runsInserted": 0,
        "framesInserted": 0,
        "participantsInserted": 0,
        "targetsInserted": 0,
        "impactsInserted": 0,
        "searchRecordsInserted": 0,
    }
    if not apply or not rows:
        return result

    result["campaignsInserted"] = _insert(conn, schema, "contextual_processing_campaigns", {
        "campaign_id": campaign_id,
        "campaign_code": campaign_code,
        "corpus_cutoff_at": cutoff,
        "taxonomy_version": TAXONOMY_VERSION,
        "rule_set_version": RULE_VERSION,
        "model_version": MODEL_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "status_code": "RUNNING",
        "started_at": now,
        "metadata_json": _json_value(conn, {
            "mode": "INCREMENTAL",
            "inputManifestSha256": input_manifest_sha256,
            "generationKey": generation_key,
        }),
    })

    for row, text, frames in planned_frames:
        run_id = _stable_id("ctxrun", campaign_id, row["document_version_id"])
        status = "COMPLETED" if frames else ("INSUFFICIENT_CONTENT" if not text.strip() else "NO_CONTEXTUAL_EVENT")
        run_inserted = _insert(conn, schema, "contextual_document_runs", {
            "contextual_run_id": run_id,
            "campaign_id": campaign_id,
            "document_version_id": row["document_version_id"],
            "input_sha256": row["content_sha256"],
            "status_code": status,
            "candidate_count": len(frames),
            "approved_count": 0,
            "started_at": now,
            "completed_at": now,
            "metadata_json": _json_value(conn, {
                "textBasis": "TITLE_SNIPPET_STORED_TEXT",
                "evidenceScope": "TITLE_SNIPPET_ONLY" if not row.get("stored_text") else "STORED_TEXT_AVAILABLE",
                "inputManifestSha256": input_manifest_sha256,
                "generationKey": generation_key,
            }),
        })
        result["runsInserted"] += run_inserted
        if not run_inserted:
            continue

        event_date = str(row.get("published_at") or row.get("collected_at") or "")[:10] or None
        source_grade = _source_grade_for(row)
        for ordinal, frame in enumerate(frames):
            extraction_key = _stable_id(
                "key", RULE_VERSION, frame.event_domain, frame.event_type, ordinal, frame.evidence_text
            )
            frame_id = _stable_id("ctxframe", generation_key, row["document_version_id"], extraction_key)
            evidence_start = text.find(frame.evidence_text)
            evidence_end = evidence_start + len(frame.evidence_text) if evidence_start >= 0 else None
            evidence_start_value = evidence_start if evidence_start >= 0 else None
            frame_payload = _frame_payload(frame)
            output_sha256 = hashlib.sha256(_stable_json(frame_payload).encode("utf-8")).hexdigest()
            frame_inserted = _insert(conn, schema, "contextual_event_frames", {
                "frame_id": frame_id,
                "contextual_run_id": run_id,
                "document_version_id": row["document_version_id"],
                "extraction_key": extraction_key,
                "event_domain": frame.event_domain,
                "event_type": frame.event_type,
                "stage_code": frame.stage_code,
                "process_type": frame.process_type,
                "action_code": frame.action_code,
                "title": frame.title,
                "summary": frame.evidence_text,
                "temporal_basis": frame.temporal_basis,
                "event_date_start": event_date,
                "modality_code": frame.modality_code,
                "polarity_code": frame.polarity_code,
                "source_grade": source_grade,
                "confidence": frame.confidence,
                "review_status": "CANDIDATE",
                "extraction_method": "HYBRID",
                "rule_version": RULE_VERSION,
                "model_version": MODEL_VERSION,
                "evidence_text": frame.evidence_text,
                "evidence_start": evidence_start_value,
                "evidence_end": evidence_end,
                "evidence_locator": f"document_version:{row['document_version_id']}#chars={evidence_start_value}:{evidence_end}",
                "created_at": now,
                "updated_at": now,
                "metadata_json": _json_value(conn, {
                    "matchedFeatures": list(frame.matched_features),
                    "generationKey": generation_key,
                    "outputSha256": output_sha256,
                }),
            })
            result["framesInserted"] += frame_inserted
            if not frame_inserted:
                continue

            for index, participant in enumerate(frame.participants):
                result["participantsInserted"] += _insert(conn, schema, "contextual_frame_participants", {
                    "frame_participant_id": _stable_id("ctxpart", frame_id, participant.role_code, index),
                    "frame_id": frame_id,
                    "role_code": participant.role_code,
                    "ordinal": index,
                    "entity_kind": participant.entity_kind,
                    "surface_text": participant.surface_text,
                    "resolution_status": "UNRESOLVED",
                    "confidence": frame.confidence,
                    "evidence_text": frame.evidence_text,
                })
            for target in frame.targets:
                result["targetsInserted"] += _insert(conn, schema, "contextual_frame_targets", {
                    "frame_target_id": _stable_id("ctxtarget", frame_id, target.target_kind, target.target_code),
                    "frame_id": frame_id,
                    "target_kind": target.target_kind,
                    "target_code": target.target_code,
                    "surface_text": target.surface_text,
                    "role_code": target.role_code,
                    "resolution_status": "CANDIDATE",
                    "confidence": frame.confidence,
                })
            for impact in frame.impacts:
                result["impactsInserted"] += _insert(conn, schema, "contextual_impact_assertions", {
                    "impact_assertion_id": _stable_id("ctximpact", frame_id, impact.target_kind, impact.target_code, impact.direction_code),
                    "cause_frame_id": frame_id,
                    "target_kind": impact.target_kind,
                    "target_code": impact.target_code,
                    "target_text": impact.target_text,
                    "mechanism_code": impact.mechanism_code,
                    "direction_code": impact.direction_code,
                    "horizon_code": impact.horizon_code,
                    "assertion_basis": impact.assertion_basis,
                    "confidence": frame.confidence,
                    "review_status": "CANDIDATE",
                    "evidence_text": frame.evidence_text,
                })

            roles = [participant.role_code for participant in frame.participants]
            region_codes = [target.target_code for target in frame.targets if target.target_kind == "REGION"]
            industry_codes = [target.target_code for target in frame.targets if target.target_kind == "INDUSTRY"]
            impact_directions = [impact.direction_code for impact in frame.impacts]
            search_text = " ".join(filter(None, [
                frame.title, frame.evidence_text, frame.event_domain, frame.event_type,
                frame.stage_code, frame.process_type,
                *[participant.surface_text for participant in frame.participants],
                *[target.surface_text for target in frame.targets],
            ]))
            result["searchRecordsInserted"] += _insert(conn, schema, "contextual_search_records", {
                "search_record_id": _stable_id("ctxsearch", frame_id),
                "campaign_id": campaign_id,
                "frame_id": frame_id,
                "record_mode": "CANDIDATE",
                "source_record_kind": "CONTEXTUAL_FRAME",
                "source_record_id": frame_id,
                "title": frame.title,
                "summary": frame.evidence_text,
                "event_domain": frame.event_domain,
                "event_type": frame.event_type,
                "stage_code": frame.stage_code,
                "process_type": frame.process_type,
                "action_code": frame.action_code,
                "event_date": event_date,
                "temporal_basis": frame.temporal_basis,
                "participant_roles_json": _json_value(conn, sorted(set(roles))),
                "participant_entity_ids_json": _json_value(conn, []),
                "asset_ids_json": _json_value(conn, []),
                "region_ids_json": _json_value(conn, sorted(set(region_codes))),
                "industry_codes_json": _json_value(conn, sorted(set(industry_codes))),
                "impact_directions_json": _json_value(conn, sorted(set(impact_directions))),
                "source_grade": source_grade,
                "confidence": frame.confidence,
                "review_status": "CANDIDATE",
                "evidence_text": frame.evidence_text,
                "evidence_locator": f"document_version:{row['document_version_id']}#chars={evidence_start_value}:{evidence_end}",
                "rule_version": RULE_VERSION,
                "model_version": MODEL_VERSION,
                "search_text": search_text,
                "metadata_json": _json_value(conn, {
                    "documentId": row["document_id"],
                    "documentVersionId": row["document_version_id"],
                    "publisher": row.get("publisher_name"),
                    "evidenceScope": "TITLE_SNIPPET_ONLY" if not row.get("stored_text") else "STORED_TEXT_AVAILABLE",
                    "generationKey": generation_key,
                    "outputSha256": output_sha256,
                }),
            })

    ph = _placeholder(conn)
    conn.execute(
        f"UPDATE {_table(schema,'contextual_processing_campaigns')} "
        f"SET status_code='COMPLETED',completed_at={ph} WHERE campaign_id={ph}",
        (now, campaign_id),
    )
    return result
