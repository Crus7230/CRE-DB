from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_contextual_intelligence import (  # noqa: E402
    CAMPAIGN_CODE,
    classify_contextual_frames,
    run_backfill,
)

SCHEMA = ROOT / "db/v2/schema.sql"
SEED = ROOT / "db/v2/seed.sql"



def make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "contextual.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    return conn


def add_document(conn: sqlite3.Connection, document_id: str, title: str, snippet: str = "") -> str:
    version_id = f"{document_id}-v1"
    conn.execute(
        """INSERT INTO source_documents(
             document_id,canonical_url,publisher_name,document_type,first_seen_at,last_seen_at
           ) VALUES(?,?,?,'RSS_ITEM','2026-09-01T00:00:00Z','2026-09-01T00:00:00Z')""",
        (document_id, f"https://example.test/{document_id}", "테스트언론"),
    )
    conn.execute(
        """INSERT INTO document_versions(
             document_version_id,document_id,version_no,title,published_at,collected_at,
             content_sha256,snippet_text,rights_status
           ) VALUES(?,?,1,?,'2026-09-01T00:00:00Z','2026-09-01T00:00:00Z',?,?,
                    'EXCERPT_ALLOWED')""",
        (version_id, document_id, title, f"{len(document_id):064x}", snippet),
    )
    return version_id


def test_contextual_classifier_requires_combinations_and_preserves_uncertainty() -> None:
    assert classify_contextual_frames("매각 시장 동향") == []

    sale = classify_contextual_frames("A사는 B빌딩 매각을 추진한다")
    assert [(item.event_domain, item.event_type) for item in sale] == [("TRANSACTION", "SALE")]
    assert sale[0].process_type == "UNKNOWN"
    assert sale[0].modality_code == "PLANNED"

    negated = classify_contextual_frames("A사는 B빌딩을 매각하지 않기로 결정했다")
    assert negated[0].polarity_code == "NEGATED"

    manager = classify_contextual_frames("국민연금은 국내 부동산 위탁운용사 3곳을 최종 선정했다")
    assert manager[0].event_domain == "MANAGER_SELECTION"
    assert manager[0].stage_code == "SELECTED"
    assert any(p.role_code == "APPOINTING_ENTITY" and p.surface_text == "국민연금" for p in manager[0].participants)

    policy = classify_contextual_frames("국토교통부는 수도권 주택 공급대책을 발표했다")
    assert policy[0].event_domain == "POLICY_REGULATION"
    assert policy[0].stage_code == "ANNOUNCED"

    monetary = classify_contextual_frames("한국은행이 기준금리를 0.25%포인트 인하했다")
    assert monetary[0].event_domain == "MONETARY_POLICY"
    assert monetary[0].event_type == "RATE_CUT"

    duplicate = classify_contextual_frames(
        "국토교통부는 공급대책을 발표했다\n국토교통부는 공급대책을 발표했다"
    )
    assert len(duplicate) == 1


def test_classifier_emits_industry_and_geopolitical_impact_candidates() -> None:
    assert classify_contextual_frames(
        "해진공이 글로벌 물류 공급망 투자펀드로 미국 물류센터를 매입했다"
    )[0].event_domain == "TRANSACTION"

    tariff = classify_contextual_frames("미국이 철강 관세를 인상해 건축비 상승 압력이 커졌다")
    assert tariff[0].event_domain == "GEOPOLITICS_TRADE"
    assert tariff[0].impacts[0].target_kind == "COST"
    assert tariff[0].impacts[0].direction_code == "INCREASE"
    assert tariff[0].impacts[0].assertion_basis == "INDUSTRY_ASSESSMENT"

    ai = classify_contextual_frames("AI 산업 성장으로 데이터센터 수요가 증가했다")
    assert ai[0].event_domain == "INDUSTRY_DEMAND"
    assert any(target.target_code == "DATA_CENTER" for target in ai[0].targets)
    assert ai[0].impacts[0].target_kind == "DEMAND"

    trend = classify_contextual_frames("CBD 오피스 공실률이 전년 대비 상승했다")
    assert trend[0].event_domain == "MARKET_TREND"
    assert trend[0].event_type == "VACANCY_TREND"


def test_backfill_is_dry_run_safe_complete_and_idempotent(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    policy_id = add_document(conn, "policy", "국토교통부는 수도권 물류센터 공급대책을 발표했다")
    add_document(conn, "sale", "A사는 B빌딩 매각을 추진한다")
    add_document(conn, "manager", "국민연금은 부동산 위탁운용사 3곳을 최종 선정했다")
    add_document(conn, "noise", "매각 시장 동향")
    conn.execute(
        """INSERT INTO extraction_runs(
             extraction_run_id,document_version_id,pipeline_version,status_code
           ) VALUES('old-run',?,'legacy-pipeline','COMPLETED')""",
        (policy_id,),
    )
    conn.execute(
        """INSERT INTO record_classifications(
             record_classification_id,target_kind,target_id,classification_scheme_id,
             classification_term_id,assignment_role,is_primary,classifier_version,
             evidence_status,review_status,assigned_at
           ) VALUES('old-class','DOCUMENT','policy','scheme-market-category',
                    'term-market-supply','DERIVED',1,'legacy-classifier','INFERRED','PENDING',
                    '2026-09-01T00:00:00Z')"""
    )
    conn.commit()

    protected = {}
    for table in ("source_documents", "document_versions", "extraction_runs", "record_classifications"):
        protected[table] = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()

    dry = run_backfill(conn, apply=False, cutoff="2026-09-03T00:00:00Z")
    assert dry["campaign_code"] == CAMPAIGN_CODE
    assert dry["documents_eligible"] == 4
    assert dry["legacy_records_planned"] == 2
    assert dry["frames_planned"] == 3
    assert conn.execute("SELECT count(*) FROM contextual_processing_campaigns").fetchone()[0] == 0

    first = run_backfill(conn, apply=True, cutoff="2026-09-03T00:00:00Z")
    second = run_backfill(conn, apply=True, cutoff="2026-09-03T00:00:00Z")
    assert first["legacy_records_inserted"] == 2
    assert first["document_runs_inserted"] == 4
    assert first["frames_inserted"] == 3
    assert first["search_records_inserted"] == 3
    assert second["legacy_records_inserted"] == 0
    assert second["document_runs_inserted"] == 0
    assert second["frames_inserted"] == 0
    assert second["search_records_inserted"] == 0

    assert conn.execute("SELECT count(*) FROM legacy_derived_records").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM contextual_event_frames").fetchone()[0] == 3
    assert conn.execute(
        "SELECT count(*) FROM contextual_event_frames WHERE review_status='APPROVED'"
    ).fetchone()[0] == 0
    modes = conn.execute(
        "SELECT record_mode,count(*) FROM contextual_search_records GROUP BY record_mode"
    ).fetchall()
    assert modes == [("CANDIDATE", 3)]
    candidate_asset_ids = [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT asset_ids_json FROM contextual_search_records WHERE record_mode='CANDIDATE'"
        )
    ]
    assert candidate_asset_ids == [[], [], []]

    run_statuses = dict(conn.execute(
        "SELECT document_version_id,status_code FROM contextual_document_runs"
    ).fetchall())
    assert run_statuses["noise-v1"] == "NO_CONTEXTUAL_EVENT"

    for table, rows in protected.items():
        assert conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() == rows

    lineage = json.loads(conn.execute(
        "SELECT metadata_json FROM legacy_derived_records WHERE target_id='old-run'"
    ).fetchone()[0])
    assert lineage["isolation"] == "REFERENCE_ONLY"
    conn.close()


def test_backfill_bridges_existing_approved_event_with_evidence(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    version_id = add_document(conn, "approved-sale", "B빌딩 매각 완료")
    conn.execute(
        """INSERT INTO extraction_runs(
             extraction_run_id,document_version_id,pipeline_version,status_code
           ) VALUES('approved-run',?,'approved-manifest','COMPLETED')""",
        (version_id,),
    )
    conn.execute(
        """INSERT INTO event_mentions(
             event_mention_id,extraction_run_id,extraction_key,event_category_id,
             stage_code_hint,title_raw,summary_raw,confidence,status_code
           ) VALUES('approved-em','approved-run','sale','cat_sale','CLOSED',
                    'B빌딩 매각 완료','B빌딩 매각 거래가 잔금 납부 후 완료됐다.',
                    1.0,'APPROVED')"""
    )
    conn.execute(
        """INSERT INTO events(
             event_id,canonical_title,primary_category_id,current_stage_code,
             event_date_start,lifecycle_status,verification_level,overall_confidence,
             approved_at
           ) VALUES('approved-event','B빌딩 매각','cat_sale','CLOSED','2026-09-01',
                    'COMPLETED','V3',1.0,'2026-09-02T00:00:00Z')"""
    )
    conn.execute(
        "INSERT INTO event_mention_links(event_mention_id,event_id,relation_code) VALUES('approved-em','approved-event','SUPPORTING')"
    )
    conn.commit()

    result = run_backfill(conn, apply=True, cutoff="2026-09-03T00:00:00Z")

    assert result["approved_events_bridged"] == 1
    row = conn.execute(
        """SELECT f.canonical_event_id,f.review_status,f.source_grade,f.evidence_text,
                  s.record_mode,s.source_record_kind,s.source_record_id
           FROM contextual_event_frames f
           JOIN contextual_search_records s ON s.frame_id=f.frame_id
           WHERE f.canonical_event_id='approved-event'"""
    ).fetchone()
    assert row == (
        "approved-event",
        "APPROVED",
        "MULTI_SOURCE_CORROBORATED",
        "B빌딩 매각 거래가 잔금 납부 후 완료됐다.",
        "APPROVED",
        "CANONICAL_EVENT",
        "approved-event",
    )
    conn.close()
