from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from collector.post_collection_relationships import reconcile_relationships
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE_DB_PATHS = {
    (ROOT / "data" / "market.db").resolve(),
    (ROOT / "db" / "market.db").resolve(),
}


class CandidateValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportResult:
    inserted_rows: int
    candidate_id: str


def _id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:24]}"


def _iso_date(value: str | None, fallback: str) -> str:
    return value or fallback


def _amount_surface_variants(decimal_text: str) -> list[str]:
    amount = int(decimal_text)
    variants = [decimal_text, f"{amount:,}"]
    if amount % 100_000_000 == 0:
        eok = amount // 100_000_000
        variants.extend([f"{eok}억원", f"{eok:,}억원", f"{eok}억 원", f"{eok:,}억 원"])
    return list(dict.fromkeys(variants))


def _validate(candidate: dict[str, Any]) -> None:
    required = {
        "candidate_id", "verification_layer", "resolution_status", "claim_type",
        "claim_subject", "claim_payload", "sources", "verification_needed",
        "first_seen_at", "last_checked_at",
    }
    missing = sorted(required - candidate.keys())
    if missing:
        raise CandidateValidationError(f"missing candidate fields: {missing}")
    if candidate["verification_layer"] != "VERIFICATION_CANDIDATE":
        raise CandidateValidationError("only VERIFICATION_CANDIDATE is supported")
    if candidate["claim_type"] != "SELECTED_MANAGER":
        raise CandidateValidationError("only SELECTED_MANAGER is supported")
    if candidate["resolution_status"] not in {
        "NEWS_ONLY_PENDING_PRIMARY", "LIKELY_REPORTED_PENDING_PRIMARY",
        "HIGHLY_LIKELY_REPORTED_PENDING_PRIMARY",
        "MULTISOURCE_CORROBORATED_PENDING_PRIMARY", "CONFLICT_REVIEW_REQUIRED",
    }:
        raise CandidateValidationError("candidate is not in an importable pending status")
    managers = candidate["claim_payload"].get("reported_selected_managers")
    if not isinstance(managers, list) or not managers or not all(isinstance(x, str) and x.strip() for x in managers):
        raise CandidateValidationError("reported_selected_managers must be a non-empty string list")
    if not candidate["sources"]:
        raise CandidateValidationError("at least one full-text source is required")
    for source in candidate["sources"]:
        if not source.get("url") or not source.get("exact_text"):
            raise CandidateValidationError("every source requires url and exact_text")
        if source.get("document_type") not in {"ARTICLE", "REPORT", "RSS_ITEM", "OTHER"}:
            raise CandidateValidationError("candidate sources must remain non-canonical secondary documents")


def _insert_dictionary_rows(con: sqlite3.Connection) -> None:
    con.executemany(
        "INSERT OR IGNORE INTO predicate_definitions(predicate_code,name_ko,subject_scope,value_kind,default_unit_code,is_multivalued,description) VALUES(?,?,?,?,?,?,?)",
        [
            ("LP_MANDATE_REPORTED_SELECTED_MANAGER", "보도된 유력 위탁운용사", "EVENT", "ORGANIZATION_REF", None, 1, "공식 결과 미확인 상태에서 구체적 보도로 알려진 유력 운용사"),
            ("LP_MANDATE_REPORTED_MANAGER_ALLOCATION", "보도된 선정사 배정금액", "EVENT", "MONEY", "KRW", 1, "공식 결과 미확인 상태에서 기사·리서치가 선정사별로 보도한 배정금액"),
        ],
    )
    rows = [
        ("MANDATE_TRACK", "위탁운용 트랙", "TEXT", "유력 선정사 claim이 속한 mandate track code"),
        ("RESOLUTION_STATUS", "검증 판정상태", "TEXT", "LIKELY·HIGHLY_LIKELY·CONTRADICTED 등 검증대기 상태"),
        ("INDEPENDENT_FAMILY_COUNT", "독립 출처계열 수", "NUMBER", "전재 중복 제거 후 독립 source family 수"),
        ("OCCURRENCE_COUNT", "원문·전재 발견 수", "NUMBER", "동일 source family를 포함한 전체 발견 문서 수"),
        ("VERIFICATION_NEEDED", "추가 검증 필요사항", "TEXT", "공식 결과·공시·당사자 확인 등 필요한 후속 근거"),
    ]
    con.executemany("INSERT OR IGNORE INTO claim_role_definitions(role_code,name_ko,allowed_kind,description) VALUES(?,?,?,?)", rows)


def _ensure_view(con: sqlite3.Connection) -> None:
    con.execute("DROP VIEW IF EXISTS v_lp_manager_best_available")
    con.execute("""
    CREATE VIEW v_lp_manager_best_available AS
    SELECT m.mandate_code, t.track_code,
           manager.organization_id AS manager_organization_id,
           manager.canonical_name AS manager_name,
           s.selection_status, s.selected_at,
           'VERIFIED_OFFICIAL' AS value_status, 1 AS canonical_eligible,
           coalesce(s.confidence,1.0) AS confidence,
           1 AS independent_family_count, 1 AS occurrence_count,
           NULL AS reported_allocation_decimal, NULL AS allocation_currency_code,
           s.source_claim_id
      FROM lp_mandate_selections s
      JOIN lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id
      JOIN lp_mandates m ON m.mandate_id=t.mandate_id
      JOIN organizations manager ON manager.organization_id=s.manager_organization_id
     WHERE s.review_status='APPROVED'
    UNION ALL
    SELECT m.mandate_code, t.track_code,
           manager.organization_id AS manager_organization_id,
           manager.canonical_name AS manager_name,
           'REPORTED_SELECTED' AS selection_status, c.date_start AS selected_at,
           coalesce((SELECT a.text_value FROM claim_arguments a WHERE a.claim_id=c.claim_id AND a.role_code='RESOLUTION_STATUS' LIMIT 1),'NEWS_ONLY_PENDING_PRIMARY') AS value_status,
           0 AS canonical_eligible, c.confidence,
           coalesce(CAST((SELECT a.value_decimal_text FROM claim_arguments a WHERE a.claim_id=c.claim_id AND a.role_code='INDEPENDENT_FAMILY_COUNT' LIMIT 1) AS INTEGER),1) AS independent_family_count,
           coalesce(CAST((SELECT a.value_decimal_text FROM claim_arguments a WHERE a.claim_id=c.claim_id AND a.role_code='OCCURRENCE_COUNT' LIMIT 1) AS INTEGER),1) AS occurrence_count,
           (SELECT ac.value_decimal_text FROM claims ac WHERE ac.event_mention_id=c.event_mention_id AND ac.predicate_code='LP_MANDATE_REPORTED_MANAGER_ALLOCATION' AND ac.object_organization_id=c.object_organization_id LIMIT 1) AS reported_allocation_decimal,
           (SELECT ac.currency_code FROM claims ac WHERE ac.event_mention_id=c.event_mention_id AND ac.predicate_code='LP_MANDATE_REPORTED_MANAGER_ALLOCATION' AND ac.object_organization_id=c.object_organization_id LIMIT 1) AS allocation_currency_code,
           c.claim_id AS source_claim_id
      FROM claims c
      JOIN event_mention_links eml ON eml.event_mention_id=c.event_mention_id AND eml.relation_code='SUPPORTING'
      JOIN lp_mandates m ON m.event_id=eml.event_id
      JOIN lp_mandate_tracks t ON t.mandate_id=m.mandate_id
      JOIN organizations manager ON manager.organization_id=c.object_organization_id
     WHERE c.predicate_code='LP_MANDATE_REPORTED_SELECTED_MANAGER'
       AND c.verification_status IN ('UNVERIFIED','PENDING','INCONCLUSIVE')
       AND c.review_status='ACCEPTED'
       AND t.track_code=coalesce((SELECT a.text_value FROM claim_arguments a WHERE a.claim_id=c.claim_id AND a.role_code='MANDATE_TRACK' LIMIT 1),t.track_code);
    """)


def import_candidate(db_path: str | Path, candidate: dict[str, Any], *, allow_live: bool = False) -> ImportResult:
    _validate(candidate)
    db_path = Path(db_path)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    version = con.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()
    if version is None or version[0] not in {"2.5.0", "2.6.0", "2.7.0", "2.8.0", "2.9.0", "3.0.0", "3.1.0", "3.2.0", "3.3.0", "3.4.0", "3.4.1", "3.5.0"}:
        con.close()
        raise CandidateValidationError(
            "database schema_version must be a supported version from 2.5.0 through 3.5.0"
        )
    if db_path.resolve() in LIVE_DB_PATHS and not allow_live:
        con.close()
        raise CandidateValidationError("live market.db import requires allow_live=True")

    before = con.total_changes
    payload = candidate["claim_payload"]
    mandate_code = candidate["claim_subject"]
    mandate = con.execute(
        "SELECT m.mandate_id,m.event_id FROM lp_mandates m WHERE m.mandate_code=?",
        (mandate_code,),
    ).fetchone()
    if mandate is None:
        con.close()
        raise CandidateValidationError(f"canonical mandate not found: {mandate_code}")
    tracks = con.execute("SELECT mandate_track_id,track_code FROM lp_mandate_tracks WHERE mandate_id=?", (mandate[0],)).fetchall()
    requested_track = payload.get("track_code")
    if requested_track:
        tracks = [row for row in tracks if row[1] == requested_track]
    if len(tracks) != 1:
        con.close()
        raise CandidateValidationError("candidate must resolve to exactly one mandate track")
    track_code = tracks[0][1]

    try:
        con.execute("BEGIN IMMEDIATE")
        _insert_dictionary_rows(con)
        _ensure_view(con)
        candidate_id = candidate["candidate_id"]
        source_contexts: list[tuple[dict[str, Any], str, str, str]] = []
        families: dict[str, str] = {}
        for source in candidate["sources"]:
            url = source["url"]
            text = source["exact_text"]
            doc_id = _id("doc", url)
            version_id = _id("dv", url, hashlib.sha256(text.encode("utf-8")).hexdigest())
            extraction_id = _id("ex", candidate_id, url)
            event_mention_id = _id("em", candidate_id, url)
            first_seen = _iso_date(source.get("published_at"), candidate["first_seen_at"])
            con.execute(
                "INSERT OR IGNORE INTO source_documents(document_id,source_id,canonical_url,publisher_name,document_type,first_seen_at,last_seen_at,access_status) VALUES(?,NULL,?,?,?,?,?,'ACCESSIBLE')",
                (doc_id, url, source.get("publisher"), source["document_type"], first_seen, candidate["last_checked_at"]),
            )
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            con.execute(
                "INSERT OR IGNORE INTO document_versions(document_version_id,document_id,version_no,title,published_at,collected_at,content_sha256,snippet_text,rights_status,metadata_json) VALUES(?,?,1,?,?,?,?,?,'EXCERPT_ALLOWED',?)",
                (version_id, doc_id, payload.get("mandate_name"), source.get("published_at"), candidate["last_checked_at"], digest, text, json.dumps({"candidate_id": candidate_id}, ensure_ascii=False)),
            )
            con.execute(
                "INSERT OR IGNORE INTO extraction_runs(extraction_run_id,document_version_id,pipeline_version,offset_basis,started_at,completed_at,status_code) VALUES(?,?,?,'UNICODE_CODEPOINT',?,?,'COMPLETED')",
                (extraction_id, version_id, "research-candidate-manifest-v1", candidate["last_checked_at"], candidate["last_checked_at"]),
            )
            con.execute(
                "INSERT OR IGNORE INTO event_mentions(event_mention_id,extraction_run_id,extraction_key,title_raw,summary_raw,evidence_start,evidence_end,event_date_start,date_precision,confidence,status_code) VALUES(?,?,?,?,?,0,?,?,?,?, 'REVIEW_READY')",
                (event_mention_id, extraction_id, candidate_id, payload.get("mandate_name"), text, len(text), payload.get("reported_selected_at"), "DAY" if payload.get("reported_selected_at") else "UNKNOWN", float(payload.get("assessment", {}).get("confidence", 0.6))),
            )
            con.execute("INSERT OR IGNORE INTO event_mention_links(event_mention_id,event_id,relation_code) VALUES(?,?,'SUPPORTING')", (event_mention_id, mandate[1]))
            family_key = source["source_family"]
            family_id = families.setdefault(family_key, _id("family", family_key))
            con.execute("INSERT OR IGNORE INTO document_families(family_id,family_type,representative_document_id) VALUES(?,'SYNDICATED',?)", (family_id, doc_id))
            con.execute("INSERT OR IGNORE INTO document_family_members(family_id,document_id,relation_confidence) VALUES(?,?,1.0)", (family_id, doc_id))
            source_contexts.append((source, text, extraction_id, event_mention_id))

        assessment = payload.get("assessment", {})
        independent_count = int(assessment.get("independent_family_count", len(families)))
        occurrence_count = int(assessment.get("occurrence_count", len(candidate["sources"])))
        confidence = float(assessment.get("confidence", 0.6))
        selected_at = payload.get("reported_selected_at")
        manager_ids: dict[str, str] = {}
        for manager_name in payload["reported_selected_managers"]:
            existing = con.execute(
                "SELECT organization_id FROM organizations WHERE canonical_name=? AND status_code='ACTIVE' ORDER BY CASE organization_type WHEN 'FINANCIAL_INSTITUTION' THEN 0 ELSE 1 END LIMIT 1",
                (manager_name,),
            ).fetchone()
            if existing is None:
                raise CandidateValidationError(
                    f"canonical manager identity not found; approve identity before candidate import: {manager_name}"
                )
            manager_id = existing[0]
            manager_ids[manager_name] = manager_id
            claim_id = _id("claim", candidate_id, manager_name)
            main_event_mention_id = source_contexts[0][3]
            con.execute(
                "INSERT OR IGNORE INTO claims(claim_id,event_mention_id,predicate_code,value_kind,raw_value,text_value,object_organization_id,value_qualifier,certainty_code,date_start,date_precision,confidence,verification_status,review_status,extraction_method) VALUES(?,?,'LP_MANDATE_REPORTED_SELECTED_MANAGER','ORGANIZATION_REF',?,?,?,?, 'REPORTED',?,?,?,'PENDING','ACCEPTED','MANUAL')",
                (claim_id, main_event_mention_id, manager_name, manager_name, manager_id, candidate_id, selected_at, "DAY" if selected_at else "UNKNOWN", confidence),
            )
            args = [
                (_id("arg", claim_id, "MANDATE_TRACK"), claim_id, "MANDATE_TRACK", 0, "TEXT", track_code, None),
                (_id("arg", claim_id, "RESOLUTION_STATUS"), claim_id, "RESOLUTION_STATUS", 0, "TEXT", candidate["resolution_status"], None),
                (_id("arg", claim_id, "INDEPENDENT_FAMILY_COUNT"), claim_id, "INDEPENDENT_FAMILY_COUNT", 0, "NUMBER", None, str(independent_count)),
                (_id("arg", claim_id, "OCCURRENCE_COUNT"), claim_id, "OCCURRENCE_COUNT", 0, "NUMBER", None, str(occurrence_count)),
                (_id("arg", claim_id, "VERIFICATION_NEEDED"), claim_id, "VERIFICATION_NEEDED", 0, "TEXT", json.dumps(candidate["verification_needed"], ensure_ascii=False), None),
            ]
            con.executemany("INSERT OR IGNORE INTO claim_arguments(claim_argument_id,claim_id,role_code,ordinal,argument_kind,text_value,value_decimal_text) VALUES(?,?,?,?,?,?,?)", args)
            evidence_count = 0
            for _source, text, extraction_id, _event_mention_id in source_contexts:
                for match in re.finditer(re.escape(manager_name), text):
                    mention_id = _id("mention", extraction_id, manager_name, str(match.start()))
                    con.execute(
                        "INSERT OR IGNORE INTO mentions(mention_id,extraction_run_id,mention_type,char_start,char_end,surface_text,surface_sha256,normalized_text,confidence,review_status) VALUES(?,?,'ORGANIZATION',?,?,?,?,?,?,'ACCEPTED')",
                        (mention_id, extraction_id, match.start(), match.end(), manager_name, hashlib.sha256(manager_name.encode("utf-8")).hexdigest(), manager_name, confidence),
                    )
                    con.execute("INSERT OR IGNORE INTO claim_evidence(claim_id,mention_id,evidence_role) VALUES(?,?,'DIRECT')", (claim_id, mention_id))
                    evidence_count += 1
            if evidence_count == 0:
                raise CandidateValidationError(f"manager is absent from source exact_text: {manager_name}")

        for allocation in payload.get("reported_selection_amounts", []):
            manager_name = allocation["manager"]
            if manager_name not in manager_ids:
                raise CandidateValidationError(f"allocation manager is not in reported_selected_managers: {manager_name}")
            decimal_text = str(allocation["decimal"])
            currency = allocation["currency"]
            amount_claim_id = _id("claim", candidate_id, manager_name, "allocation", decimal_text, currency)
            amount_evidence: list[tuple[str, int, int, str]] = []
            for _source, text, extraction_id, _event_mention_id in source_contexts:
                for surface in _amount_surface_variants(decimal_text):
                    match = re.search(re.escape(surface), text)
                    if match:
                        amount_evidence.append((extraction_id, match.start(), match.end(), match.group(0)))
                        break
            if not amount_evidence:
                raise CandidateValidationError(f"reported allocation is absent from source exact_text: {manager_name} {decimal_text} {currency}")
            raw_surface = amount_evidence[0][3]
            con.execute(
                "INSERT OR IGNORE INTO claims(claim_id,event_mention_id,predicate_code,value_kind,raw_value,numeric_value,value_decimal_text,currency_code,unit_code,object_organization_id,value_qualifier,certainty_code,date_start,date_precision,confidence,verification_status,review_status,extraction_method) VALUES(?,?,'LP_MANDATE_REPORTED_MANAGER_ALLOCATION','MONEY',?,?,?,?,?,?,?,'REPORTED',?,?,?,'PENDING','ACCEPTED','MANUAL')",
                (amount_claim_id, source_contexts[0][3], raw_surface, float(decimal_text), decimal_text, currency, currency, manager_ids[manager_name], candidate_id, selected_at, "DAY" if selected_at else "UNKNOWN", confidence),
            )
            con.execute(
                "INSERT OR IGNORE INTO claim_arguments(claim_argument_id,claim_id,role_code,ordinal,argument_kind,text_value) VALUES(?,?, 'MANDATE_TRACK',0,'TEXT',?)",
                (_id("arg", amount_claim_id, "MANDATE_TRACK"), amount_claim_id, track_code),
            )
            for extraction_id, start, end, surface in amount_evidence:
                mention_id = _id("mention", extraction_id, "MONEY", decimal_text, str(start))
                con.execute(
                    "INSERT OR IGNORE INTO mentions(mention_id,extraction_run_id,mention_type,char_start,char_end,surface_text,surface_sha256,normalized_text,confidence,review_status) VALUES(?,?,'MONEY',?,?,?,?,?,?,'ACCEPTED')",
                    (mention_id, extraction_id, start, end, surface, hashlib.sha256(surface.encode('utf-8')).hexdigest(), decimal_text, confidence),
                )
                con.execute("INSERT OR IGNORE INTO claim_evidence(claim_id,mention_id,evidence_role) VALUES(?,?,'DIRECT')", (amount_claim_id, mention_id))

        inserted = con.total_changes - before
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    reconcile_relationships(db_path, allow_live=True)
    return ImportResult(inserted_rows=inserted, candidate_id=candidate_id)
