"""Import reviewable institutional-manager bid/deployment action evidence.

This importer is deliberately limited to SQLite fixture databases.  It writes
only the source -> mention -> claim evidence layer.  In particular it never
writes canonical manager selections, selection vehicles, deployments, or the
bid_* transaction tables.

Manifest shape (version 1.0) is intentionally explicit: normalized identities
and action fields live at the top level, source documents contain full
``exact_text``, and each evidence row identifies the exact substrings that
support the LP, manager, mandate, track, action, date, funding basis, and linked
    vehicle or canonical asset/project deal.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
LIVE_DB_PATHS = {
    (ROOT / "data" / "market.db").resolve(),
    (ROOT / "db" / "market.db").resolve(),
}

PREDICATE_BY_ACTION = {
    "BID": "LP_MANDATE_MANAGER_BID_PARTICIPANT",
    "DEPLOYMENT": "LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT",
}
BID_ACTIONS = {
    "APPLIED",
    "BID_SUBMITTED",
    "PRELIMINARY_BID_SUBMITTED",
    "FINAL_BID_SUBMITTED",
    "SHORTLISTED",
    "PREFERRED_BIDDER",
}
DEPLOYMENT_ACTIONS = {"COMMITTED", "EXECUTED", "REALISED"}
BID_FUNDING_BASES = {"LP_EQUITY"}
# A generic fund-equity or co-investment deployment does not prove that this
# mandate's LP capital funded the action.  Those records must remain outside the
# manager-from-deployment predicate until an LP-source bridge is evidenced.
DEPLOYMENT_FUNDING_BASES = {"LP_SOURCE_DEPLOYMENT"}
DOCUMENT_TYPES = {
    "ARTICLE",
    "PRESS_RELEASE",
    "DISCLOSURE",
    "NOTICE",
    "BID_NOTICE",
    "REPORT",
    "RSS_ITEM",
    "API_RECORD",
    "LEGAL_DOCUMENT",
    "OTHER",
}
PRIMARY_DOCUMENT_TYPES = {
    "PRESS_RELEASE",
    "DISCLOSURE",
    "NOTICE",
    "BID_NOTICE",
    "REPORT",
    "API_RECORD",
    "LEGAL_DOCUMENT",
}
PRIMARY_SOURCE_KINDS = {
    "OFFICIAL",
    "OFFICIAL_SITE",
    "PARTY_PRIMARY",
    "PARTY_SITE",
    "REGULATOR_PRIMARY",
}
RIGHTS_STATUSES = {
    "FULL_STORAGE_ALLOWED",
    "EXCERPT_ALLOWED",
    "METADATA_ONLY",
    "MANUAL_ACCESS",
    "UNKNOWN",
}
CONTENT_SCOPES = {"FULL_TEXT", "EXCERPT", "SNIPPET"}
FAMILY_RELATIONS = {"ORIGINAL", "SYNDICATED", "PRESS_RELEASE_COPY"}
DEAL_TABLES = {
    "ASSET": ("assets", "asset_id", "ASSET", "canonical_name"),
    "PROJECT": ("projects", "project_id", "PROJECT", "canonical_name"),
}
EVIDENCE_FIELDS = (
    "direct_action_text",
    "lp_text",
    "manager_text",
    "mandate_text",
    "track_text",
    "vehicle_or_deal_text",
    "date_text",
    "funding_basis_text",
)
SUPPORTED_SCHEMA_VERSIONS = {
    "2.5.0",
    "2.6.0",
    "2.7.0",
    "2.8.0",
    "2.9.0",
    "3.0.0",
    "3.1.0",
    "3.2.0",
    "3.3.0",
    "3.4.0",
    "3.4.1",
    "3.5.0",
}


class ManifestValidationError(ValueError):
    """Raised for invalid evidence or a stable-ID content conflict."""


@dataclass(frozen=True)
class ImportResult:
    manifest_id: str
    claim_id: str
    inserted_rows: int


@dataclass(frozen=True)
class _CanonicalContext:
    event_id: str
    lp_surfaces: tuple[str, ...]
    manager_name: str
    manager_surfaces: tuple[str, ...]
    mandate_name: str
    track_name: str
    vehicle_id: str | None
    vehicle_surfaces: tuple[str, ...]
    deal_ref: str | None
    deal_name: str | None


def _required(obj: Mapping[str, Any], key: str, path: str) -> Any:
    value = obj.get(key)
    if value is None or value == "":
        raise ManifestValidationError(f"{path}.{key} is required")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, *parts: str) -> str:
    value = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(value).hexdigest()[:24]}"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso_date(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ManifestValidationError(f"{path} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ManifestValidationError(f"{path} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ManifestValidationError(f"{path} must use YYYY-MM-DD")
    return value


def _iso_datetime(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ManifestValidationError(f"{path} must be an ISO datetime")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestValidationError(f"{path} must be an ISO datetime") from exc
    return value


def _load_manifest(value: Path | str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return json.loads(Path(value).read_text(encoding="utf-8"))


def _insert(con: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> None:
    """Insert an immutable stable-ID row, or prove the existing row is equal."""
    columns = list(values)
    cur = con.execute(
        f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) "
        f"VALUES ({','.join('?' for _ in columns)})",
        tuple(values[column] for column in columns),
    )
    if cur.rowcount:
        return

    table_info = con.execute(f"PRAGMA table_info({table})").fetchall()
    pk_columns = [
        row[1]
        for row in sorted(table_info, key=lambda row: row[5] or 999)
        if row[5]
    ]
    if not pk_columns or any(column not in values for column in pk_columns):
        pk_columns = [columns[0]]
    row = con.execute(
        f"SELECT {','.join(columns)} FROM {table} WHERE "
        + " AND ".join(f"{column}=?" for column in pk_columns),
        tuple(values[column] for column in pk_columns),
    ).fetchone()
    if row is None or tuple(row) != tuple(values[column] for column in columns):
        identity = ",".join(f"{column}={values[column]}" for column in pk_columns)
        raise ManifestValidationError(f"conflicting existing row in {table} for {identity}")


def _source_is_primary(source: Mapping[str, Any]) -> bool:
    return (
        source.get("source_kind") in PRIMARY_SOURCE_KINDS
        and source.get("document_type") in PRIMARY_DOCUMENT_TYPES
    )


def _eligible_for_verified_review(manifest: Mapping[str, Any]) -> bool:
    """Return whether cited full text clears the human-review evidence gate.

    Official/party-primary full text qualifies directly.  An original full-text
    article/report also qualifies, as do two independent full-text media source
    families.  RSS, snippets, excerpts, and a lone syndicated family never do.
    """
    sources = {source["id"]: source for source in manifest["sources"]}
    cited_ids = {
        evidence["source_id"]
        for evidence in manifest["evidence"]
        if all(evidence.get(field) for field in EVIDENCE_FIELDS)
    }
    if not cited_ids:
        return False
    cited = [sources[source_id] for source_id in cited_ids]
    full_text = [source for source in cited if source["content_scope"] == "FULL_TEXT"]
    if any(_source_is_primary(source) for source in full_text):
        return True
    media_full_text = [
        source
        for source in full_text
        if source["document_type"] in {"ARTICLE", "REPORT"}
    ]
    if any(source["family_relation"] == "ORIGINAL" for source in media_full_text):
        return True
    independent_families = {source["source_family"] for source in media_full_text}
    return len(independent_families) >= 2


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("manifest_version") != "1.0":
        raise ManifestValidationError("manifest_version must be 1.0")
    for key in (
        "manifest_id",
        "action_type",
        "mandate_code",
        "track_code",
        "lp_organization_id",
        "manager_organization_id",
        "follow_up_action",
        "funding_basis",
        "action_date",
        "inference_rule_version",
        "observed_at",
    ):
        _required(manifest, key, "manifest")

    action_type = manifest["action_type"]
    if action_type not in PREDICATE_BY_ACTION:
        raise ManifestValidationError("action_type must be BID or DEPLOYMENT")
    allowed_actions = BID_ACTIONS if action_type == "BID" else DEPLOYMENT_ACTIONS
    if manifest["follow_up_action"] not in allowed_actions:
        raise ManifestValidationError(
            f"follow_up_action is invalid for action_type={action_type}"
        )
    allowed_bases = BID_FUNDING_BASES if action_type == "BID" else DEPLOYMENT_FUNDING_BASES
    if manifest["funding_basis"] not in allowed_bases:
        raise ManifestValidationError(
            f"funding_basis is invalid for action_type={action_type}"
        )
    _iso_date(manifest["action_date"], "manifest.action_date")
    _iso_datetime(manifest["observed_at"], "manifest.observed_at")
    confidence = manifest.get("confidence", 0.6)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ManifestValidationError("confidence must be a number between 0 and 1")
    if not 0 <= float(confidence) <= 1:
        raise ManifestValidationError("confidence must be a number between 0 and 1")

    linked_vehicle = manifest.get("linked_vehicle_organization_id")
    linked_deal = manifest.get("linked_deal")
    if not linked_vehicle and not linked_deal:
        raise ManifestValidationError(
            "linked_vehicle_organization_id or linked_deal is required"
        )
    if linked_deal:
        if not isinstance(linked_deal, Mapping):
            raise ManifestValidationError("linked_deal must be an object")
        if _required(linked_deal, "kind", "linked_deal") not in DEAL_TABLES:
            raise ManifestValidationError("linked_deal.kind is invalid")
        _required(linked_deal, "id", "linked_deal")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ManifestValidationError("sources must be a non-empty array")
    source_by_id: dict[str, Mapping[str, Any]] = {}
    for index, source in enumerate(sources):
        path = f"sources[{index}]"
        if not isinstance(source, Mapping):
            raise ManifestValidationError(f"{path} must be an object")
        source_id = _required(source, "id", path)
        if source_id in source_by_id:
            raise ManifestValidationError(f"duplicate source id: {source_id}")
        for key in (
            "url",
            "publisher",
            "document_type",
            "source_kind",
            "published_at",
            "accessed_at",
            "rights_status",
            "content_scope",
            "source_family",
            "family_relation",
            "exact_text",
        ):
            _required(source, key, path)
        if source["document_type"] not in DOCUMENT_TYPES:
            raise ManifestValidationError(f"{path}.document_type is invalid")
        if source["rights_status"] not in RIGHTS_STATUSES:
            raise ManifestValidationError(f"{path}.rights_status is invalid")
        if source["content_scope"] not in CONTENT_SCOPES:
            raise ManifestValidationError(f"{path}.content_scope is invalid")
        if source["family_relation"] not in FAMILY_RELATIONS:
            raise ManifestValidationError(f"{path}.family_relation is invalid")
        _iso_datetime(source["accessed_at"], f"{path}.accessed_at")
        source_by_id[source_id] = source

    evidence_rows = manifest.get("evidence")
    if not isinstance(evidence_rows, list) or not evidence_rows:
        raise ManifestValidationError("evidence must be a non-empty array")
    for index, evidence in enumerate(evidence_rows):
        path = f"evidence[{index}]"
        if not isinstance(evidence, Mapping):
            raise ManifestValidationError(f"{path} must be an object")
        source_id = _required(evidence, "source_id", path)
        source = source_by_id.get(source_id)
        if source is None:
            raise ManifestValidationError(f"{path} references unknown source: {source_id}")
        exact_text = source["exact_text"]
        for key in EVIDENCE_FIELDS:
            surface = evidence.get(key)
            if surface is None or surface == "":
                continue
            if not isinstance(surface, str) or surface not in exact_text:
                raise ManifestValidationError(
                    f"{path}.{key} is not an exact source substring"
                )

    review = manifest.get("review")
    if review is not None:
        if not isinstance(review, Mapping):
            raise ManifestValidationError("review must be an object")
        decision = _required(review, "review_decision", "review")
        if decision not in {"PENDING", "ACCEPTED", "REJECTED"}:
            raise ManifestValidationError("review.review_decision is invalid")
        if decision == "ACCEPTED":
            _required(review, "reviewer", "review")
            _iso_datetime(_required(review, "approved_at", "review"), "review.approved_at")


def _organization_surfaces(con: sqlite3.Connection, organization_id: str) -> tuple[str, ...]:
    row = con.execute(
        "SELECT canonical_name FROM organizations WHERE organization_id=?",
        (organization_id,),
    ).fetchone()
    aliases = con.execute(
        "SELECT alias_text FROM organization_aliases WHERE organization_id=?",
        (organization_id,),
    ).fetchall()
    return tuple(dict.fromkeys([row[0], *(alias[0] for alias in aliases)])) if row else ()


def _normalized_surface(value: str) -> str:
    """Normalize presentation-only differences without weakening identity."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _surface_matches(surface: str, canonical_surfaces: tuple[str, ...]) -> bool:
    normalized = _normalized_surface(surface)
    return any(normalized == _normalized_surface(candidate) for candidate in canonical_surfaces)


def _date_surface_matches(action_date: str, surface: str) -> bool:
    parsed = date.fromisoformat(action_date)
    variants = {
        action_date,
        action_date.replace("-", "."),
        action_date.replace("-", "/"),
        f"{parsed.year}.{parsed.month}.{parsed.day}",
        f"{parsed.year}/{parsed.month}/{parsed.day}",
        f"{parsed.year}년 {parsed.month}월 {parsed.day}일",
        f"{parsed.year}년{parsed.month}월{parsed.day}일",
    }
    return any(value in surface for value in variants)


def _canonical_context(
    con: sqlite3.Connection, manifest: Mapping[str, Any]
) -> _CanonicalContext:
    mandate = con.execute(
        """SELECT m.mandate_id,m.event_id,m.lp_organization_id,m.announced_at,
                  m.mandate_name
             FROM lp_mandates m
            WHERE m.mandate_code=?""",
        (manifest["mandate_code"],),
    ).fetchone()
    if mandate is None:
        raise ManifestValidationError(
            f"canonical mandate not found: {manifest['mandate_code']}"
        )
    mandate_id, event_id, lp_id, announced_at, mandate_name = mandate
    if event_id is None:
        raise ManifestValidationError("canonical mandate must be linked to an event")
    if lp_id != manifest["lp_organization_id"]:
        raise ManifestValidationError("lp_organization_id does not match canonical mandate")
    track = con.execute(
        """SELECT mandate_track_id,track_name FROM lp_mandate_tracks
            WHERE mandate_id=? AND track_code=?""",
        (mandate_id, manifest["track_code"]),
    ).fetchone()
    if track is None:
        raise ManifestValidationError("track_code does not belong to canonical mandate")
    manager = con.execute(
        "SELECT canonical_name FROM organizations WHERE organization_id=? AND status_code='ACTIVE'",
        (manifest["manager_organization_id"],),
    ).fetchone()
    if manager is None:
        raise ManifestValidationError("manager_organization_id is not an active canonical identity")
    if announced_at and manifest["action_date"] < announced_at[:10]:
        raise ManifestValidationError("action_date cannot precede mandate.announced_at")

    lp_surfaces = _organization_surfaces(con, lp_id)
    manager_surfaces = _organization_surfaces(con, manifest["manager_organization_id"])
    vehicle_id = manifest.get("linked_vehicle_organization_id")
    vehicle_surfaces: tuple[str, ...] = ()
    if vehicle_id:
        vehicle = con.execute(
            """SELECT canonical_name FROM organizations
                WHERE organization_id=? AND status_code='ACTIVE'
                  AND organization_type IN ('FUND','REIT','SPC')""",
            (vehicle_id,),
        ).fetchone()
        if vehicle is None:
            raise ManifestValidationError(
                "linked_vehicle_organization_id must be an active FUND, REIT, or SPC"
            )
        vehicle_surfaces = _organization_surfaces(con, vehicle_id)

    deal_ref: str | None = None
    deal_name: str | None = None
    linked_deal = manifest.get("linked_deal")
    if linked_deal:
        kind = linked_deal["kind"]
        table, key_column, _, name_column = DEAL_TABLES[kind]
        deal = con.execute(
            f"SELECT {name_column} FROM {table} WHERE {key_column}=?",
            (linked_deal["id"],),
        ).fetchone()
        if deal is None:
            raise ManifestValidationError(
                f"linked_deal does not resolve to canonical {kind}: {linked_deal['id']}"
            )
        deal_ref = f"{kind}:{linked_deal['id']}"
        deal_name = deal[0]

    for index, evidence in enumerate(manifest["evidence"]):
        path = f"evidence[{index}]"
        if evidence.get("lp_text") and not _surface_matches(evidence["lp_text"], lp_surfaces):
            raise ManifestValidationError(f"{path}.lp_text does not identify the canonical LP")
        if evidence.get("manager_text") and not _surface_matches(
            evidence["manager_text"], manager_surfaces
        ):
            raise ManifestValidationError(
                f"{path}.manager_text does not identify the canonical manager"
            )
        if evidence.get("mandate_text") and not _surface_matches(
            evidence["mandate_text"], (mandate_name,)
        ):
            raise ManifestValidationError(
                f"{path}.mandate_text does not identify the canonical mandate"
            )
        if evidence.get("track_text") and not _surface_matches(
            evidence["track_text"], (track[1],)
        ):
            raise ManifestValidationError(
                f"{path}.track_text does not identify the canonical track"
            )
        linked_surfaces = (*vehicle_surfaces, *((deal_name,) if deal_name else ()))
        if evidence.get("vehicle_or_deal_text") and not _surface_matches(
            evidence["vehicle_or_deal_text"], linked_surfaces
        ):
            raise ManifestValidationError(
                f"{path}.vehicle_or_deal_text does not identify the linked vehicle or deal"
            )
        if evidence.get("date_text") and not _date_surface_matches(
            manifest["action_date"], evidence["date_text"]
        ):
            raise ManifestValidationError(
                f"{path}.date_text does not identify action_date"
            )

    return _CanonicalContext(
        event_id=event_id,
        lp_surfaces=lp_surfaces,
        manager_name=manager[0],
        manager_surfaces=manager_surfaces,
        mandate_name=mandate_name,
        track_name=track[1],
        vehicle_id=vehicle_id,
        vehicle_surfaces=vehicle_surfaces,
        deal_ref=deal_ref,
        deal_name=deal_name,
    )


def _put_mention(
    con: sqlite3.Connection,
    extraction_id: str,
    mention_type: str,
    exact_text: str,
    surface: str,
    confidence: float,
    review_status: str,
) -> str:
    start = exact_text.find(surface)
    if start < 0:
        raise ManifestValidationError("validated exact substring disappeared during import")
    end = start + len(surface)
    existing = con.execute(
        """SELECT mention_id FROM mentions
             WHERE extraction_run_id=? AND char_start=? AND char_end=? AND mention_type=?""",
        (extraction_id, start, end, mention_type),
    ).fetchone()
    if existing:
        return existing[0]
    mention_id = _stable_id(
        "ima_m", extraction_id, mention_type, str(start), str(end), surface
    )
    _insert(
        con,
        "mentions",
        {
            "mention_id": mention_id,
            "extraction_run_id": extraction_id,
            "mention_type": mention_type,
            "char_start": start,
            "char_end": end,
            "surface_text": surface,
            "surface_sha256": _sha(surface),
            "normalized_text": surface,
            "confidence": confidence,
            "review_status": review_status,
        },
    )
    return mention_id


def _claim_status(manifest: Mapping[str, Any]) -> tuple[str, str]:
    review = manifest.get("review") or {}
    if (
        review.get("review_decision") == "ACCEPTED"
        and review.get("reviewer")
        and review.get("approved_at")
        and _eligible_for_verified_review(manifest)
    ):
        return "ACCEPTED", "VERIFIED"
    return "UNREVIEWED", "PENDING"


def _evidence_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    sources = {source["id"]: source for source in manifest["sources"]}
    cited_ids = {evidence["source_id"] for evidence in manifest["evidence"]}
    cited = [sources[source_id] for source_id in cited_ids]
    return {
        "eligible_for_verified_review": _eligible_for_verified_review(manifest),
        "independent_family_count": len({source["source_family"] for source in cited}),
        "occurrence_count": len(cited),
        "content_scopes": sorted({source["content_scope"] for source in cited}),
        "family_relations": sorted({source["family_relation"] for source in cited}),
    }


def import_manifest(
    db_path: Path | str,
    manifest_value: Path | str | Mapping[str, Any],
) -> ImportResult:
    """Import one evidence claim into a fixture DB, atomically and idempotently."""
    manifest = _load_manifest(manifest_value)
    validate_manifest(manifest)
    db = Path(db_path).resolve()
    if db in LIVE_DB_PATHS:
        raise ManifestValidationError(f"fixture-only importer blocks live database: {db}")
    if not db.exists():
        raise ManifestValidationError(f"database does not exist: {db}")

    con = sqlite3.connect(db, timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    before = con.total_changes
    claim_id = ""
    try:
        con.execute("BEGIN IMMEDIATE")
        version = con.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()
        if version is None or version[0] not in SUPPORTED_SCHEMA_VERSIONS:
            raise ManifestValidationError("database schema_version is not supported")

        context = _canonical_context(con, manifest)
        predicate = PREDICATE_BY_ACTION[manifest["action_type"]]
        review_status, verification_status = _claim_status(manifest)
        evidence_summary = _evidence_summary(manifest)
        mention_review = "ACCEPTED" if review_status == "ACCEPTED" else "UNREVIEWED"
        confidence = float(manifest.get("confidence", 0.6))

        source_contexts: dict[str, tuple[str, str, str]] = {}
        for source in manifest["sources"]:
            exact_text = source["exact_text"]
            document_id = _stable_id("ima_doc", source["url"])
            version_id = _stable_id("ima_dv", source["url"], _sha(exact_text))
            extraction_id = _stable_id("ima_ext", version_id)
            event_mention_id = _stable_id(
                "ima_em", manifest["manifest_id"], source["id"]
            )
            source_contexts[source["id"]] = (
                extraction_id,
                event_mention_id,
                exact_text,
            )
            seen_at = source.get("published_at") or source["accessed_at"]
            _insert(
                con,
                "source_documents",
                {
                    "document_id": document_id,
                    "canonical_url": source["url"],
                    "publisher_name": source["publisher"],
                    "document_type": source["document_type"],
                    "first_seen_at": seen_at,
                    "last_seen_at": seen_at,
                    "access_status": "ACCESSIBLE",
                },
            )
            _insert(
                con,
                "document_versions",
                {
                    "document_version_id": version_id,
                    "document_id": document_id,
                    "version_no": 1,
                    "title": source.get("title"),
                    "published_at": source["published_at"],
                    "collected_at": source["accessed_at"],
                    "content_sha256": _sha(exact_text),
                    "snippet_text": exact_text,
                    "rights_status": source["rights_status"],
                    "metadata_json": _json(
                        {
                            "source_kind": source["source_kind"],
                            "publisher": source["publisher"],
                            "content_scope": source["content_scope"],
                            "source_family": source["source_family"],
                            "family_relation": source["family_relation"],
                        }
                    ),
                },
            )
            _insert(
                con,
                "extraction_runs",
                {
                    "extraction_run_id": extraction_id,
                    "document_version_id": version_id,
                    "pipeline_version": "institutional-manager-action-manifest-v1",
                    "offset_basis": "UNICODE_CODEPOINT",
                    "model_name": "deterministic-reviewed-manifest",
                    "started_at": manifest["observed_at"],
                    "completed_at": manifest["observed_at"],
                    "status_code": "COMPLETED",
                },
            )
            _insert(
                con,
                "event_mentions",
                {
                    "event_mention_id": event_mention_id,
                    "extraction_run_id": extraction_id,
                    "extraction_key": manifest["manifest_id"],
                    "title_raw": source.get("title") or manifest["follow_up_action"],
                    "summary_raw": exact_text,
                    "evidence_start": 0,
                    "evidence_end": len(exact_text),
                    "event_date_start": manifest["action_date"],
                    "date_precision": "DAY",
                    "confidence": confidence,
                    "status_code": "APPROVED"
                    if review_status == "ACCEPTED"
                    else "REVIEW_READY",
                },
            )
            _insert(
                con,
                "event_mention_links",
                {
                    "event_mention_id": event_mention_id,
                    "event_id": context.event_id,
                    "relation_code": "SUPPORTING",
                },
            )

        linked_identity = context.vehicle_id or ""
        if context.deal_ref:
            linked_identity += f"|{context.deal_ref}"
        claim_id = _stable_id(
            "ima_claim",
            manifest["manifest_id"],
            predicate,
            manifest["mandate_code"],
            manifest["track_code"],
            manifest["manager_organization_id"],
            linked_identity,
        )
        first_evidence = manifest["evidence"][0]
        main_evidence = next(
            (
                evidence
                for evidence in manifest["evidence"]
                if all(evidence.get(field) for field in EVIDENCE_FIELDS)
            ),
            first_evidence,
        )
        main_event_mention_id = source_contexts[main_evidence["source_id"]][1]
        _insert(
            con,
            "claims",
            {
                "claim_id": claim_id,
                "event_mention_id": main_event_mention_id,
                "predicate_code": predicate,
                "value_kind": "ORGANIZATION_REF",
                "raw_value": main_evidence.get("direct_action_text")
                or manifest["follow_up_action"],
                "text_value": context.manager_name,
                "object_organization_id": manifest["manager_organization_id"],
                "value_qualifier": _json(
                    {
                        "manifest_id": manifest["manifest_id"],
                        "action_type": manifest["action_type"],
                        "review": manifest.get("review"),
                        "evidence_gate": evidence_summary,
                    }
                ),
                "certainty_code": "REPORTED"
                if manifest["action_type"] == "BID"
                else "INFERRED",
                "date_start": manifest["action_date"],
                "date_precision": "DAY",
                "confidence": confidence,
                "verification_status": verification_status,
                "review_status": review_status,
                "extraction_method": "CALCULATED",
            },
        )

        text_arguments = {
            "MANDATE_CODE": manifest["mandate_code"],
            "MANDATE_TRACK": manifest["track_code"],
            "FOLLOW_UP_ACTION": manifest["follow_up_action"],
            "FUNDING_BASIS": manifest["funding_basis"],
            "INFERENCE_RULE_VERSION": manifest["inference_rule_version"],
        }
        for role_code, text_value in text_arguments.items():
            _insert(
                con,
                "claim_arguments",
                {
                    "claim_argument_id": _stable_id("ima_arg", claim_id, role_code),
                    "claim_id": claim_id,
                    "role_code": role_code,
                    "ordinal": 0,
                    "argument_kind": "TEXT",
                    "text_value": text_value,
                },
            )
        for role_code, value in {
            "INDEPENDENT_FAMILY_COUNT": evidence_summary["independent_family_count"],
            "OCCURRENCE_COUNT": evidence_summary["occurrence_count"],
        }.items():
            _insert(
                con,
                "claim_arguments",
                {
                    "claim_argument_id": _stable_id("ima_arg", claim_id, role_code),
                    "claim_id": claim_id,
                    "role_code": role_code,
                    "ordinal": 0,
                    "argument_kind": "NUMBER",
                    "value_decimal_text": str(value),
                },
            )
        if context.vehicle_id:
            _insert(
                con,
                "claim_arguments",
                {
                    "claim_argument_id": _stable_id(
                        "ima_arg", claim_id, "LINKED_VEHICLE"
                    ),
                    "claim_id": claim_id,
                    "role_code": "LINKED_VEHICLE",
                    "ordinal": 0,
                    "argument_kind": "ENTITY",
                    "organization_id": context.vehicle_id,
                },
            )
        if context.deal_ref:
            linked_deal = manifest["linked_deal"]
            entity_column = "asset_id" if linked_deal["kind"] == "ASSET" else "project_id"
            _insert(
                con,
                "claim_arguments",
                {
                    "claim_argument_id": _stable_id(
                        "ima_arg", claim_id, "LINKED_DEAL"
                    ),
                    "claim_id": claim_id,
                    "role_code": "LINKED_DEAL",
                    "ordinal": 0,
                    "argument_kind": "ENTITY",
                    entity_column: linked_deal["id"],
                },
            )

        linked_deal = manifest.get("linked_deal")
        for evidence in manifest["evidence"]:
            extraction_id, _, exact_text = source_contexts[evidence["source_id"]]
            target_surface = evidence.get("vehicle_or_deal_text")
            target_mention_type = "ORGANIZATION"
            if (
                target_surface
                and linked_deal
                and context.deal_name
                and _surface_matches(target_surface, (context.deal_name,))
            ):
                target_mention_type = DEAL_TABLES[linked_deal["kind"]][2]
            surfaces = (
                ("direct_action_text", "EVENT_STAGE", "DIRECT"),
                ("lp_text", "ORGANIZATION", "ATTRIBUTION"),
                ("manager_text", "ORGANIZATION", "DIRECT"),
                ("mandate_text", "EVENT_STAGE", "CONTEXT"),
                ("track_text", "EVENT_STAGE", "CONTEXT"),
                ("vehicle_or_deal_text", target_mention_type, "QUALIFIER"),
                ("date_text", "DATE", "QUALIFIER"),
                ("funding_basis_text", "EVENT_STAGE", "QUALIFIER"),
            )
            for key, mention_type, evidence_role in surfaces:
                if not evidence.get(key):
                    continue
                mention_id = _put_mention(
                    con,
                    extraction_id,
                    mention_type,
                    exact_text,
                    evidence[key],
                    confidence,
                    mention_review,
                )
                _insert(
                    con,
                    "claim_evidence",
                    {
                        "claim_id": claim_id,
                        "mention_id": mention_id,
                        "evidence_role": evidence_role,
                    },
                )

        inserted_rows = con.total_changes - before
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return ImportResult(
        manifest_id=manifest["manifest_id"],
        claim_id=claim_id,
        inserted_rows=inserted_rows,
    )


__all__ = [
    "ImportResult",
    "ManifestValidationError",
    "import_manifest",
    "validate_manifest",
]
