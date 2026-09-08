"""Deterministic contextual-event backfill with reference-only legacy isolation.

The module deliberately creates candidates, never approved facts. Raw/source and
pre-existing derived tables are read-only inputs; legacy isolation is a separate
ledger keyed by a versioned processing campaign.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable

ROOT = Path(__file__).parents[1]
DEFAULT_DB = ROOT / "data/market.db"
CAMPAIGN_CODE = "CONTEXTUAL_EVENT_V1"
TAXONOMY_VERSION = "cre-contextual-taxonomy-1.0.0"
RULE_VERSION = "cre-contextual-rules-1.0.0"
MODEL_VERSION = "weighted-context-model-1.0.0"
PIPELINE_VERSION = "contextual-event-frame-1.0.0"


@dataclass(frozen=True)
class ParticipantCandidate:
    role_code: str
    surface_text: str
    entity_kind: str = "ORGANIZATION"


@dataclass(frozen=True)
class TargetCandidate:
    target_kind: str
    target_code: str
    surface_text: str
    role_code: str = "AFFECTED_TARGET"


@dataclass(frozen=True)
class ImpactCandidate:
    target_kind: str
    target_code: str
    target_text: str
    mechanism_code: str
    direction_code: str
    assertion_basis: str = "INDUSTRY_ASSESSMENT"
    horizon_code: str = "UNKNOWN"


@dataclass(frozen=True)
class FrameCandidate:
    event_domain: str
    event_type: str
    title: str
    evidence_text: str
    confidence: float
    stage_code: str | None = None
    process_type: str | None = None
    action_code: str | None = None
    modality_code: str = "REPORTED"
    polarity_code: str = "AFFIRMED"
    temporal_basis: str = "PUBLICATION_DATE"
    participants: tuple[ParticipantCandidate, ...] = field(default_factory=tuple)
    targets: tuple[TargetCandidate, ...] = field(default_factory=tuple)
    impacts: tuple[ImpactCandidate, ...] = field(default_factory=tuple)
    matched_features: tuple[str, ...] = field(default_factory=tuple)


_AUTHORITIES = (
    "국토교통부", "금융위원회", "기획재정부", "한국은행", "국민연금",
    "행정안전부", "서울시", "정부", "미국", "중국", "EU", "유럽연합",
)
_TARGETS = (
    ("ASSET_CLASS", "DATA_CENTER", "데이터센터"),
    ("ASSET_CLASS", "LOGISTICS", "물류센터"),
    ("ASSET_CLASS", "OFFICE", "오피스"),
    ("ASSET_CLASS", "HOTEL", "호텔"),
    ("ASSET_CLASS", "RETAIL", "리테일"),
    ("REGION", "SEOUL_CBD", "CBD"),
    ("REGION", "SEOUL_GBD", "GBD"),
    ("REGION", "SEOUL_YBD", "YBD"),
    ("REGION", "CAPITAL_AREA", "수도권"),
    ("INDUSTRY", "AI_CLOUD", "AI"),
    ("INDUSTRY", "SEMICONDUCTOR", "반도체"),
    ("INDUSTRY", "ECOMMERCE", "이커머스"),
    ("INDUSTRY", "TOURISM", "관광"),
    ("INDUSTRY", "AVIATION", "항공"),
)


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join("" if part is None else str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def _sentences(text: str) -> Iterable[str]:
    for sentence in re.split(r"(?<=[.!?。]|다)\s+|[\r\n]+", text):
        sentence = re.sub(r"\s+", " ", sentence).strip()
        if sentence:
            yield sentence


def _modality(sentence: str) -> tuple[str, str]:
    if re.search(r"않기로|않았다|아니라고|계획이 없다|추진하지", sentence):
        return "FACTUAL", "NEGATED"
    if re.search(r"전망|예상|가능성|관측|것으로 보", sentence):
        return "FORECAST", "UNCERTAIN"
    if re.search(r"검토|추진|계획|예정|목표", sentence):
        return "PLANNED", "AFFIRMED"
    if re.search(r"조건|경우|한다면|할 경우", sentence):
        return "CONDITIONAL", "UNCERTAIN"
    if re.search(r"선정|결정|발표|시행|체결|완료|인하|인상|동결|증가|감소|상승|하락", sentence):
        return "FACTUAL", "AFFIRMED"
    return "REPORTED", "AFFIRMED"


def _participants(sentence: str, domain: str) -> tuple[ParticipantCandidate, ...]:
    found: list[ParticipantCandidate] = []
    role = {
        "MANAGER_SELECTION": "APPOINTING_ENTITY",
        "POLICY_REGULATION": "ISSUING_AUTHORITY",
        "MONETARY_POLICY": "DECISION_AUTHORITY",
        "GEOPOLITICS_TRADE": "ACTOR",
    }.get(domain, "ACTOR")
    for name in _AUTHORITIES:
        if name in sentence:
            found.append(ParticipantCandidate(role, name, "COUNTRY" if name in {"미국", "중국"} else "AUTHORITY"))
    return tuple(found)


def _targets(sentence: str) -> tuple[TargetCandidate, ...]:
    return tuple(TargetCandidate(kind, code, surface) for kind, code, surface in _TARGETS if surface in sentence)


def _impact(sentence: str) -> tuple[ImpactCandidate, ...]:
    direction = None
    if re.search(r"상승|증가|인상|확대|강화|커졌다|높아", sentence):
        direction = "INCREASE"
    elif re.search(r"하락|감소|인하|축소|완화|낮아", sentence):
        direction = "DECREASE"
    if direction is None:
        return ()
    if re.search(r"건축비|공사비|비용|원가|조달비", sentence):
        return (ImpactCandidate("COST", "COST", "비용", "COST_CHANNEL", direction),)
    if "수요" in sentence:
        return (ImpactCandidate("DEMAND", "DEMAND", "수요", "DEMAND_CHANNEL", direction),)
    if "공급" in sentence:
        return (ImpactCandidate("SUPPLY", "SUPPLY", "공급", "SUPPLY_CHANNEL", direction),)
    if re.search(r"유동성|거래량", sentence):
        return (ImpactCandidate("LIQUIDITY", "LIQUIDITY", "유동성", "LIQUIDITY_CHANNEL", direction),)
    if re.search(r"가격|가치|임대료|지가", sentence):
        return (ImpactCandidate("VALUE", "VALUE", "가격·가치", "VALUE_CHANNEL", direction),)
    return ()


def _frame_for_sentence(sentence: str) -> FrameCandidate | None:
    modality, polarity = _modality(sentence)
    targets = _targets(sentence)
    impacts = _impact(sentence)

    # Manager selection precedes generic transaction terms such as 우선협상.
    if re.search(r"위탁운용사|운용사", sentence) and re.search(r"선정|공모|접수|숏리스트|제안서|우선협상", sentence):
        stage = "SELECTED" if re.search(r"최종\s*선정|선정했다|선정됐|선정되", sentence) else (
            "SHORTLIST" if "숏리스트" in sentence else "ANNOUNCED" if "공모" in sentence else "REVIEW"
        )
        return FrameCandidate("MANAGER_SELECTION", "MANAGER_SELECTION", sentence[:180], sentence, 0.88,
                              stage, "COMPETITIVE_SELECTION" if re.search(r"공모|제안서|숏리스트", sentence) else "UNKNOWN",
                              "SELECT_MANAGER", modality, polarity,
                              participants=_participants(sentence, "MANAGER_SELECTION"), targets=targets,
                              impacts=impacts, matched_features=("manager_role", "selection_action"))

    if re.search(r"기준금리|정책금리", sentence) and re.search(r"인하|인상|동결|결정", sentence):
        event_type = "RATE_CUT" if "인하" in sentence else "RATE_HIKE" if "인상" in sentence else "RATE_HOLD"
        return FrameCandidate("MONETARY_POLICY", event_type, sentence[:180], sentence, 0.92,
                              "DECIDED" if modality == "FACTUAL" else "EXPECTED", None, event_type,
                              modality, polarity, participants=_participants(sentence, "MONETARY_POLICY"),
                              targets=targets, impacts=impacts, matched_features=("rate_subject", "rate_action"))

    if any(name in sentence for name in ("국토교통부", "금융위원회", "기획재정부", "정부", "서울시")) and re.search(
        r"정책|대책|규제|법안|법령|세제|공급계획", sentence
    ) and re.search(r"발표|시행|의결|공포|개정|완화|강화|추진|검토", sentence):
        stage = "EFFECTIVE" if "시행" in sentence else "ENACTED" if re.search(r"의결|공포", sentence) else "ANNOUNCED" if "발표" in sentence else "PROPOSED"
        return FrameCandidate("POLICY_REGULATION", "POLICY_ACTION", sentence[:180], sentence, 0.9,
                              stage, None, "POLICY_CHANGE", modality, polarity,
                              participants=_participants(sentence, "POLICY_REGULATION"), targets=targets,
                              impacts=impacts, matched_features=("policy_actor", "policy_action"))

    geopolitical_trigger = re.search(r"전쟁|침공|휴전|제재|관세|무역분쟁", sentence) or (
        "공급망" in sentence and re.search(r"차질|중단|재편|봉쇄|위기|충격", sentence)
    )
    if geopolitical_trigger and (
        any(name in sentence for name in ("미국", "중국", "EU", "유럽연합", "러시아", "우크라이나", "정부"))
        or re.search(r"부과|인상|인하|발발|확전|중단|합의", sentence)
    ):
        event_type = "TARIFF_CHANGE" if "관세" in sentence else "SANCTION" if "제재" in sentence else "GEOPOLITICAL_ACTION"
        return FrameCandidate("GEOPOLITICS_TRADE", event_type, sentence[:180], sentence, 0.86,
                              "EFFECTIVE" if re.search(r"부과|발발|시행", sentence) else "ANNOUNCED",
                              None, event_type, modality, polarity,
                              participants=_participants(sentence, "GEOPOLITICS_TRADE"), targets=targets,
                              impacts=impacts, matched_features=("geopolitical_action", "actor_or_geography"))

    if re.search(r"PF|프로젝트금융|리파이낸싱|대출|브릿지론|채무|대주단", sentence) and re.search(
        r"약정|실행|전환|연장|상환|조달|차입|부도|기한이익|재구조", sentence
    ):
        return FrameCandidate("FINANCING_RESTRUCTURING", "FINANCING_ACTION", sentence[:180], sentence, 0.85,
                              "COMPLETED" if re.search(r"실행|약정|상환", sentence) else "IN_PROGRESS",
                              None, "FINANCING_CHANGE", modality, polarity, targets=targets, impacts=impacts,
                              matched_features=("financing_subject", "financing_action"))

    if re.search(r"매각|매입|인수|양도|양수", sentence) and re.search(
        r"추진|검토|결정|체결|완료|철회|선정|입찰|매각하지|양도했다|인수했다|매입했다", sentence
    ):
        event_type = "ACQUISITION" if re.search(r"매입|인수|양수", sentence) and "매각" not in sentence else "SALE"
        stage = "CLOSED" if re.search(r"완료|종결|잔금", sentence) else "SPA" if re.search(r"SPA|계약\s*체결", sentence) else "PREFERRED_BIDDER" if re.search(r"우협|우선협상", sentence) else "BIDDING" if "입찰" in sentence else "UNDER_REVIEW" if re.search(r"검토|추진", sentence) else "DECIDED"
        process = "PRIVATE_NEGOTIATION" if re.search(r"수의계약|단독협상|경쟁입찰\s*없이|직거래", sentence) else "COMPETITIVE_BID" if re.search(r"공개입찰|경쟁입찰|예비입찰|본입찰", sentence) else "UNKNOWN"
        return FrameCandidate("TRANSACTION", event_type, sentence[:180], sentence, 0.86, stage, process,
                              "DISPOSE" if event_type == "SALE" else "ACQUIRE", modality, polarity,
                              targets=targets, impacts=impacts,
                              matched_features=("transaction_action", "status_or_process"))

    if re.search(r"AI|반도체|이커머스|관광|항공|배터리|클라우드", sentence) and re.search(
        r"성장|축소|증가|감소|확대|투자|이전|재편", sentence
    ) and re.search(r"데이터센터|물류센터|오피스|호텔|리테일|공장|산업시설|부동산|수요|공급", sentence):
        return FrameCandidate("INDUSTRY_DEMAND", "INDUSTRY_SHIFT", sentence[:180], sentence, 0.84,
                              "OBSERVED" if modality == "FACTUAL" else "EXPECTED", None, "INDUSTRY_CHANGE",
                              modality, polarity, targets=targets, impacts=impacts,
                              matched_features=("industry", "change_action", "cre_target"))

    if re.search(r"공실률|임대료|거래량|캡레이트|수익률|지가", sentence) and re.search(
        r"상승|하락|증가|감소|확대|축소|전년|전월|분기|추세", sentence
    ):
        event_type = "VACANCY_TREND" if "공실" in sentence else "RENT_TREND" if "임대료" in sentence else "MARKET_METRIC_TREND"
        return FrameCandidate("MARKET_TREND", event_type, sentence[:180], sentence, 0.83,
                              "OBSERVED", None, "TREND_CHANGE", modality, polarity, targets=targets,
                              impacts=impacts, matched_features=("market_metric", "direction", "comparison"))

    if targets and re.search(r"입주|퇴거|이전|재개발|재건축|용도변경|개통|착공|준공|공급", sentence) and re.search(
        r"결정|발표|시작|완료|예정|추진|증가|감소", sentence
    ):
        return FrameCandidate("ASSET_REGIONAL_CHANGE", "ASSET_REGIONAL_CHANGE", sentence[:180], sentence, 0.8,
                              "OBSERVED" if modality == "FACTUAL" else "PLANNED", None, "PLACE_CHANGE",
                              modality, polarity, targets=targets, impacts=impacts,
                              matched_features=("asset_or_region", "change_action"))
    return None


def classify_contextual_frames(text: str) -> list[FrameCandidate]:
    frames: list[FrameCandidate] = []
    seen_evidence: set[str] = set()
    for sentence in _sentences(text):
        evidence_key = re.sub(r"\s+", " ", sentence).strip().casefold()
        if evidence_key in seen_evidence:
            continue
        seen_evidence.add(evidence_key)
        frame = _frame_for_sentence(sentence)
        if frame is not None:
            frames.append(frame)
    return frames


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _legacy_sources(conn: sqlite3.Connection, cutoff: str) -> list[tuple[str, str, str, str | None, str | None]]:
    specs = [
        ("extraction_runs", "EXTRACTION_RUN", "extraction_run_id", "pipeline_version", "status_code", "created_at"),
        ("record_classifications", "RECORD_CLASSIFICATION", "record_classification_id", "classifier_version", "review_status", "assigned_at"),
        ("analytics_refresh_runs", "ANALYTICS_REFRESH_RUN", "analytics_refresh_run_id", "pipeline_code", "status_code", "started_at"),
        ("insight_signals", "INSIGHT_SIGNAL", "insight_signal_id", "analytics_refresh_run_id", "review_status", "created_at"),
        ("insight_interpretations", "MODEL_INTERPRETATION", "interpretation_id", "model_version", "review_status", "created_at"),
    ]
    rows: list[tuple[str, str, str, str | None, str | None]] = []
    for table, kind, pk, producer, status, time_col in specs:
        if not _table_exists(conn, table):
            continue
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        producer_expr = producer if producer in columns else "NULL"
        status_expr = status if status in columns else "NULL"
        where = f" WHERE {time_col}<=?" if time_col in columns else ""
        args = (cutoff,) if where else ()
        for row in conn.execute(
            f"SELECT {pk},{producer_expr},{status_expr} FROM {table}{where} ORDER BY {pk}", args
        ):
            rows.append((kind, str(row[0]), table, row[1], row[2]))
    return rows


def _eligible_documents(conn: sqlite3.Connection, cutoff: str) -> list[sqlite3.Row]:
    original_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """WITH ranked AS (
                 SELECT dv.*,sd.document_type,sd.publisher_name,cs.source_code,
                        row_number() OVER(PARTITION BY dv.document_id ORDER BY dv.version_no DESC,dv.collected_at DESC) AS rn
                 FROM document_versions dv
                 JOIN source_documents sd ON sd.document_id=dv.document_id
                 LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
                 WHERE dv.collected_at<=?
               )
               SELECT * FROM ranked WHERE rn=1 ORDER BY document_version_id""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.row_factory = original_factory


def _source_grade(row: sqlite3.Row) -> str:
    source = (row["source_code"] or "").upper()
    if source in {"OPENDART", "MOLIT_REAL_TRANSACTION", "SEOUL_OPEN_DATA", "ECOS"}:
        return "OFFICIAL_DIRECT"
    if source in {"KRX", "KRX_DATA"}:
        return "STRUCTURED_DIRECT"
    if row["document_type"] == "RSS_ITEM":
        return "MEDIA_DIRECT"
    return "UNVERIFIED"


def _json(values: Iterable[str]) -> str:
    return json.dumps(sorted(set(values)), ensure_ascii=False)


def _insert_frame(conn: sqlite3.Connection, campaign_id: str, run_id: str, row: sqlite3.Row,
                  frame: FrameCandidate, ordinal: int, now: str) -> tuple[int, int, int, int]:
    frame_id = _stable_id("ctxframe", campaign_id, row["document_version_id"], ordinal, frame.evidence_text)
    extraction_key = _stable_id("key", frame.event_domain, frame.event_type, ordinal, frame.evidence_text)
    event_date = (row["published_at"] or row["collected_at"] or "")[:10] or None
    inserted = conn.execute(
        """INSERT OR IGNORE INTO contextual_event_frames(
             frame_id,contextual_run_id,document_version_id,extraction_key,event_domain,event_type,
             stage_code,process_type,action_code,title,summary,temporal_basis,event_date_start,
             modality_code,polarity_code,source_grade,confidence,review_status,extraction_method,
             rule_version,model_version,evidence_text,created_at,updated_at,metadata_json
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'CANDIDATE','HYBRID',?,?,?,?,?,?)""",
        (frame_id, run_id, row["document_version_id"], extraction_key, frame.event_domain,
         frame.event_type, frame.stage_code, frame.process_type, frame.action_code, frame.title,
         frame.evidence_text, frame.temporal_basis, event_date, frame.modality_code,
         frame.polarity_code, _source_grade(row), frame.confidence, RULE_VERSION, MODEL_VERSION,
         frame.evidence_text, now, now, json.dumps({"matchedFeatures": frame.matched_features}, ensure_ascii=False)),
    ).rowcount
    if not inserted:
        return 0, 0, 0, 0
    participant_count = target_count = impact_count = 0
    for index, participant in enumerate(frame.participants):
        participant_count += conn.execute(
            """INSERT OR IGNORE INTO contextual_frame_participants(
                 frame_participant_id,frame_id,role_code,ordinal,entity_kind,surface_text,
                 resolution_status,confidence,evidence_text
               ) VALUES(?,?,?,?,?,?,'UNRESOLVED',?,?)""",
            (_stable_id("ctxpart", frame_id, participant.role_code, index), frame_id,
             participant.role_code, index, participant.entity_kind, participant.surface_text,
             frame.confidence, frame.evidence_text),
        ).rowcount
    for target in frame.targets:
        target_count += conn.execute(
            """INSERT OR IGNORE INTO contextual_frame_targets(
                 frame_target_id,frame_id,target_kind,target_code,surface_text,role_code,
                 resolution_status,confidence
               ) VALUES(?,?,?,?,?,?,'CANDIDATE',?)""",
            (_stable_id("ctxtarget", frame_id, target.target_kind, target.target_code), frame_id,
             target.target_kind, target.target_code, target.surface_text, target.role_code,
             frame.confidence),
        ).rowcount
    for impact in frame.impacts:
        impact_count += conn.execute(
            """INSERT OR IGNORE INTO contextual_impact_assertions(
                 impact_assertion_id,cause_frame_id,target_kind,target_code,target_text,
                 mechanism_code,direction_code,horizon_code,assertion_basis,confidence,
                 review_status,evidence_text
               ) VALUES(?,?,?,?,?,?,?,?,?,?,'CANDIDATE',?)""",
            (_stable_id("ctximpact", frame_id, impact.target_kind, impact.target_code,
                        impact.direction_code), frame_id, impact.target_kind, impact.target_code,
             impact.target_text, impact.mechanism_code, impact.direction_code,
             impact.horizon_code, impact.assertion_basis, frame.confidence, frame.evidence_text),
        ).rowcount
    roles = [p.role_code for p in frame.participants]
    asset_codes = [t.target_code for t in frame.targets if t.target_kind == "ASSET"]
    region_codes = [t.target_code for t in frame.targets if t.target_kind == "REGION"]
    industry_codes = [t.target_code for t in frame.targets if t.target_kind == "INDUSTRY"]
    impact_directions = [i.direction_code for i in frame.impacts]
    search_text = " ".join(filter(None, [frame.title, frame.evidence_text, frame.event_domain,
                                          frame.event_type, frame.stage_code, frame.process_type,
                                          *[p.surface_text for p in frame.participants],
                                          *[t.surface_text for t in frame.targets]]))
    search_inserted = conn.execute(
        """INSERT OR IGNORE INTO contextual_search_records(
             search_record_id,campaign_id,frame_id,record_mode,source_record_kind,
             source_record_id,title,summary,event_domain,event_type,stage_code,process_type,
             action_code,event_date,temporal_basis,participant_roles_json,
             participant_entity_ids_json,asset_ids_json,region_ids_json,industry_codes_json,
             impact_directions_json,source_grade,confidence,review_status,evidence_text,
             rule_version,model_version,search_text,metadata_json
           ) VALUES(?,?,?,'CANDIDATE','CONTEXTUAL_FRAME',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    'CANDIDATE',?,?,?,?,?)""",
        (_stable_id("ctxsearch", frame_id), campaign_id, frame_id, frame_id,
         frame.title, frame.evidence_text, frame.event_domain, frame.event_type, frame.stage_code,
         frame.process_type, frame.action_code, event_date, frame.temporal_basis, _json(roles), "[]",
         _json(asset_codes), _json(region_codes), _json(industry_codes), _json(impact_directions),
         _source_grade(row), frame.confidence, frame.evidence_text, RULE_VERSION, MODEL_VERSION,
         search_text, json.dumps({"documentId": row["document_id"], "publisher": row["publisher_name"]}, ensure_ascii=False)),
    ).rowcount
    return inserted, participant_count, target_count, impact_count + search_inserted


def _approved_event_rows(conn: sqlite3.Connection, cutoff: str) -> list[sqlite3.Row]:
    original_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """WITH evidence_ranked AS (
                 SELECT e.event_id,e.canonical_title,e.primary_category_id,e.current_stage_code,
                        e.event_date_start,e.event_date_end,e.verification_level,e.overall_confidence,
                        e.approved_at,em.event_mention_id,em.title_raw,em.summary_raw,
                        dv.document_version_id,dv.document_id,dv.content_sha256,dv.title AS document_title,
                        dv.published_at,dv.collected_at,sd.publisher_name,sd.document_type,
                        cs.source_code,cs.authority_tier,
                        row_number() OVER(
                          PARTITION BY e.event_id
                          ORDER BY coalesce(cs.authority_tier,99),
                                   length(coalesce(em.summary_raw,em.title_raw,dv.snippet_text,dv.title,'')) DESC,
                                   dv.collected_at DESC
                        ) AS rn
                 FROM events e
                 JOIN event_mention_links link ON link.event_id=e.event_id
                 JOIN event_mentions em ON em.event_mention_id=link.event_mention_id
                 JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
                 JOIN document_versions dv ON dv.document_version_id=er.document_version_id
                 JOIN source_documents sd ON sd.document_id=dv.document_id
                 LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
                 WHERE e.approved_at IS NOT NULL AND e.approved_at<=?
               )
               SELECT * FROM evidence_ranked WHERE rn=1 ORDER BY event_id""",
            (cutoff,),
        ).fetchall()
    finally:
        conn.row_factory = original_factory


def _bridge_approved_events(conn: sqlite3.Connection, campaign_id: str, cutoff: str, now: str) -> tuple[int, int]:
    bridged = search_inserted = 0
    for row in _approved_event_rows(conn, cutoff):
        evidence = (row["summary_raw"] or row["title_raw"] or row["document_title"] or "").strip()
        if not evidence:
            continue
        inferred = classify_contextual_frames(f"{row['canonical_title']}\n{evidence}")
        if inferred:
            candidate = inferred[0]
            domain, event_type = candidate.event_domain, candidate.event_type
            process_type, action_code = candidate.process_type, candidate.action_code
        elif row["primary_category_id"] == "cat_sale":
            domain, event_type, process_type, action_code = "TRANSACTION", "SALE", "UNKNOWN", "DISPOSE"
        elif row["primary_category_id"] == "cat_invest":
            domain, event_type, process_type, action_code = "MANAGER_SELECTION", "MANAGER_SELECTION", "UNKNOWN", "SELECT_MANAGER"
        else:
            continue
        run_id = _stable_id("ctxrun", campaign_id, row["document_version_id"])
        run_inserted = conn.execute(
            """INSERT OR IGNORE INTO contextual_document_runs(
                 contextual_run_id,campaign_id,document_version_id,input_sha256,status_code,
                 candidate_count,approved_count,started_at,completed_at,metadata_json
               ) VALUES(?,?,?,?, 'COMPLETED',1,1,?,?,?)""",
            (run_id, campaign_id, row["document_version_id"], row["content_sha256"], now, now,
             json.dumps({"textBasis": "LEGACY_APPROVED_EVENT_EVIDENCE"})),
        ).rowcount
        frame_id = _stable_id("ctxapproved", campaign_id, row["event_id"])
        source_grade = "MULTI_SOURCE_CORROBORATED" if row["verification_level"] == "V3" else (
            "OFFICIAL_DERIVED" if (row["authority_tier"] or 99) <= 2 else "MEDIA_DIRECT"
        )
        confidence = float(row["overall_confidence"] if row["overall_confidence"] is not None else 1.0)
        inserted = conn.execute(
            """INSERT OR IGNORE INTO contextual_event_frames(
                 frame_id,contextual_run_id,document_version_id,source_event_mention_id,
                 canonical_event_id,extraction_key,event_domain,event_type,stage_code,
                 process_type,action_code,title,summary,temporal_basis,event_date_start,
                 event_date_end,modality_code,polarity_code,source_grade,confidence,
                 review_status,extraction_method,rule_version,model_version,evidence_text,
                 approved_by,approved_at,created_at,updated_at,metadata_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'EVENT_DATE',?,?,'FACTUAL','AFFIRMED',?,?,
                        'APPROVED','HUMAN',?,?,?,'LEGACY_APPROVED_EVENT_BRIDGE',?,?,?,?)""",
            (frame_id, run_id, row["document_version_id"], row["event_mention_id"], row["event_id"],
             _stable_id("approved-key", row["event_id"]), domain, event_type, row["current_stage_code"],
             process_type, action_code, row["canonical_title"], evidence, row["event_date_start"],
             row["event_date_end"], source_grade, confidence, RULE_VERSION, MODEL_VERSION, evidence,
             row["approved_at"], now, now,
             json.dumps({"bridge": "EXISTING_APPROVED_CANONICAL_EVENT", "verificationLevel": row["verification_level"]})),
        ).rowcount
        if not inserted:
            continue
        bridged += 1
        if not run_inserted:
            conn.execute(
                """UPDATE contextual_document_runs
                   SET candidate_count=candidate_count+1,approved_count=approved_count+1
                   WHERE contextual_run_id=?""",
                (run_id,),
            )
        participant_rows = conn.execute(
            """SELECT ep.organization_id,ep.role_code,o.canonical_name,ep.confidence
               FROM event_participants ep JOIN organizations o USING(organization_id)
               WHERE ep.event_id=? ORDER BY ep.role_code,ep.organization_id""",
            (row["event_id"],),
        ).fetchall()
        roles, entities = [], []
        for ordinal, participant in enumerate(participant_rows):
            roles.append(participant[1]); entities.append(participant[0])
            conn.execute(
                """INSERT OR IGNORE INTO contextual_frame_participants(
                     frame_participant_id,frame_id,role_code,ordinal,entity_kind,entity_id,
                     surface_text,resolution_status,confidence,evidence_text
                   ) VALUES(?,?,?,?, 'ORGANIZATION',?,?,'RESOLVED',?,?)""",
                (_stable_id("ctxpart", frame_id, participant[1], participant[0]), frame_id,
                 participant[1], ordinal, participant[0], participant[2], participant[3], evidence),
            )
        asset_rows = conn.execute(
            """SELECT ea.asset_id,ea.role_code,a.canonical_name,a.asset_class_id,ea.confidence
               FROM event_assets ea JOIN assets a USING(asset_id)
               WHERE ea.event_id=? ORDER BY ea.role_code,ea.asset_id""",
            (row["event_id"],),
        ).fetchall()
        asset_ids = []
        for asset in asset_rows:
            asset_ids.append(asset[0])
            conn.execute(
                """INSERT OR IGNORE INTO contextual_frame_targets(
                     frame_target_id,frame_id,target_kind,target_id,target_code,surface_text,
                     role_code,resolution_status,confidence
                   ) VALUES(?,?,'ASSET',?,?,?,?,'RESOLVED',?)""",
                (_stable_id("ctxtarget", frame_id, "ASSET", asset[0]), frame_id, asset[0],
                 asset[3], asset[2], asset[1], asset[4]),
            )
        search_text = " ".join(filter(None, [row["canonical_title"], evidence, domain, event_type,
                                              row["current_stage_code"], *roles,
                                              *[item[2] for item in participant_rows],
                                              *[item[2] for item in asset_rows]]))
        search_inserted += conn.execute(
            """INSERT OR IGNORE INTO contextual_search_records(
                 search_record_id,campaign_id,frame_id,record_mode,source_record_kind,
                 source_record_id,title,summary,event_domain,event_type,stage_code,process_type,
                 action_code,event_date,temporal_basis,participant_roles_json,
                 participant_entity_ids_json,asset_ids_json,region_ids_json,industry_codes_json,
                 impact_directions_json,source_grade,confidence,review_status,evidence_text,
                 rule_version,model_version,search_text,metadata_json
               ) VALUES(?,?,?,'APPROVED','CANONICAL_EVENT',?,?,?,?,?,?,?,?,?,'EVENT_DATE',
                        ?,?,?,'[]','[]','[]',?,?, 'APPROVED',?,?,?,?,?)""",
            (_stable_id("ctxsearch", frame_id), campaign_id, frame_id, row["event_id"],
             row["canonical_title"], evidence, domain, event_type, row["current_stage_code"],
             process_type, action_code, row["event_date_start"], _json(roles), _json(entities),
             _json(asset_ids), source_grade, confidence, evidence, RULE_VERSION, MODEL_VERSION,
             search_text, json.dumps({"canonicalEventId": row["event_id"], "documentId": row["document_id"], "documentVersionId": row["document_version_id"]})),
        ).rowcount
    return bridged, search_inserted


def run_backfill(conn: sqlite3.Connection, *, apply: bool = False, cutoff: str | None = None) -> dict:
    cutoff = cutoff or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    campaign_id = _stable_id("ctxcamp", CAMPAIGN_CODE, cutoff, TAXONOMY_VERSION, RULE_VERSION, MODEL_VERSION)
    legacy = _legacy_sources(conn, cutoff)
    documents = _eligible_documents(conn, cutoff)
    planned_frames = sum(len(classify_contextual_frames("\n".join(filter(None, [row["title"], row["snippet_text"], row["stored_text"]])))) for row in documents)
    result = {
        "campaign_id": campaign_id,
        "campaign_code": CAMPAIGN_CODE,
        "cutoff": cutoff,
        "documents_eligible": len(documents),
        "legacy_records_planned": len(legacy),
        "frames_planned": planned_frames,
        "legacy_records_inserted": 0,
        "document_runs_inserted": 0,
        "frames_inserted": 0,
        "participants_inserted": 0,
        "targets_inserted": 0,
        "impacts_inserted": 0,
        "search_records_inserted": 0,
        "approved_events_bridged": 0,
    }
    if not apply:
        return result
    conn.execute("SAVEPOINT contextual_backfill")
    try:
        conn.execute(
            """INSERT OR IGNORE INTO contextual_processing_campaigns(
                 campaign_id,campaign_code,corpus_cutoff_at,taxonomy_version,rule_set_version,
                 model_version,pipeline_version,status_code,started_at,metadata_json
               ) VALUES(?,?,?,?,?,?,?,'RUNNING',?,?)""",
            (campaign_id, CAMPAIGN_CODE, cutoff, TAXONOMY_VERSION, RULE_VERSION, MODEL_VERSION,
             PIPELINE_VERSION, now, json.dumps({"legacyIsolation": "REFERENCE_ONLY"})),
        )
        # A stable campaign code cannot silently point at another cutoff/version.
        existing = conn.execute(
            """SELECT campaign_id,corpus_cutoff_at,taxonomy_version,rule_set_version,model_version
               FROM contextual_processing_campaigns WHERE campaign_code=?""", (CAMPAIGN_CODE,)
        ).fetchone()
        if existing is None or existing[0] != campaign_id:
            raise RuntimeError("campaign code already exists with a different cutoff or version")
        for kind, target_id, table, producer, status in legacy:
            result["legacy_records_inserted"] += conn.execute(
                """INSERT OR IGNORE INTO legacy_derived_records(
                     legacy_record_id,campaign_id,target_kind,target_id,source_table,
                     producer_run_id,original_status,legacy_reason,metadata_json
                   ) VALUES(?,?,?,?,?,?,?,'PRE_CONTEXTUAL_PIPELINE',?)""",
                (_stable_id("ctxlegacy", campaign_id, kind, target_id), campaign_id, kind,
                 target_id, table, producer, status,
                 json.dumps({"isolation": "REFERENCE_ONLY", "sourceTable": table})),
            ).rowcount
        for row in documents:
            text = "\n".join(filter(None, [row["title"], row["snippet_text"], row["stored_text"]]))
            frames = classify_contextual_frames(text)
            run_id = _stable_id("ctxrun", campaign_id, row["document_version_id"])
            status = "COMPLETED" if frames else ("INSUFFICIENT_CONTENT" if not text.strip() else "NO_CONTEXTUAL_EVENT")
            inserted_run = conn.execute(
                """INSERT OR IGNORE INTO contextual_document_runs(
                     contextual_run_id,campaign_id,document_version_id,input_sha256,status_code,
                     candidate_count,approved_count,started_at,completed_at,metadata_json
                   ) VALUES(?,?,?,?,?,?,0,?,?,?)""",
                (run_id, campaign_id, row["document_version_id"], row["content_sha256"], status,
                 len(frames), now, now, json.dumps({"textBasis": "TITLE_SNIPPET_STORED_TEXT"})),
            ).rowcount
            result["document_runs_inserted"] += inserted_run
            if not inserted_run:
                continue
            for ordinal, frame in enumerate(frames):
                frame_count, participants, targets, impact_plus_search = _insert_frame(
                    conn, campaign_id, run_id, row, frame, ordinal, now
                )
                result["frames_inserted"] += frame_count
                result["participants_inserted"] += participants
                result["targets_inserted"] += targets
                if frame_count:
                    # _insert_frame returns impacts + the single search row in its last slot.
                    impact_count = len(frame.impacts)
                    result["impacts_inserted"] += impact_count
                    result["search_records_inserted"] += max(0, impact_plus_search - impact_count)
        approved_bridged, approved_search = _bridge_approved_events(conn, campaign_id, cutoff, now)
        result["approved_events_bridged"] += approved_bridged
        result["search_records_inserted"] += approved_search
        conn.execute(
            """UPDATE contextual_processing_campaigns
               SET status_code='COMPLETED',completed_at=? WHERE campaign_id=?""",
            (now, campaign_id),
        )
        conn.execute("RELEASE SAVEPOINT contextual_backfill")
        conn.commit()
        return result
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT contextual_backfill")
        conn.execute("RELEASE SAVEPOINT contextual_backfill")
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cutoff")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        result = run_backfill(conn, apply=args.apply, cutoff=args.cutoff)
    finally:
        conn.close()
    report = args.report or ROOT / "artifacts/contextual-intelligence/backfill.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "report": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
