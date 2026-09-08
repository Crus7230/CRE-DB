from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_document_market_categories import (  # noqa: E402
    CLASSIFIER_VERSION,
    backfill_document_market_categories,
    infer_market_terms,
    stable_assignment_id,
)


SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"


def make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "document-market-category.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    return conn


def add_document(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    version_no: int = 1,
    published_at: str = "2026-03-01T00:00:00Z",
    title: str = "테스트 기사",
    snippet: str = "테스트 요약",
    scope_status: str = "CRE_CONFIRMED",
    category_id: str = "cat_sale",
    mention_status: str = "REVIEW_READY",
) -> tuple[str, str]:
    document_version_id = f"{document_id}-v{version_no}"
    extraction_run_id = f"{document_id}-run{version_no}"
    conn.execute(
        """INSERT OR IGNORE INTO source_documents(
             document_id,source_id,canonical_url,publisher_name,document_type,
             first_seen_at,last_seen_at
           ) VALUES(?, 'src_google_news', ?, '테스트 언론', 'RSS_ITEM', ?, ?)""",
        (
            document_id,
            f"https://example.test/{document_id}",
            published_at,
            published_at,
        ),
    )
    conn.execute(
        """INSERT INTO document_versions(
             document_version_id,document_id,version_no,title,published_at,collected_at,
             content_sha256,snippet_text,rights_status
           ) VALUES(?,?,?,?,?,?,?,?,'EXCERPT_ALLOWED')""",
        (
            document_version_id,
            document_id,
            version_no,
            title,
            published_at,
            published_at,
            f"{version_no:064x}",
            snippet,
        ),
    )
    conn.execute(
        """INSERT INTO document_scope_assessments(
             document_scope_assessment_id,document_version_id,scope_code,
             classifier_version,status_code,assessed_at
           ) VALUES(?,?,'CRE','NEWS_CRE_SCOPE_RULE_V1',?,?)""",
        (f"{document_id}-scope{version_no}", document_version_id, scope_status, published_at),
    )
    conn.execute(
        """INSERT INTO extraction_runs(
             extraction_run_id,document_version_id,pipeline_version,status_code
           ) VALUES(?,?,?,'COMPLETED')""",
        (extraction_run_id, document_version_id, f"test-pipeline-{version_no}"),
    )
    conn.execute(
        """INSERT INTO event_mentions(
             event_mention_id,extraction_run_id,extraction_key,event_category_id,
             confidence,status_code
           ) VALUES(?,?,?,?,0.91,?)""",
        (
            f"{document_id}-mention{version_no}",
            extraction_run_id,
            f"event-{version_no}",
            category_id,
            mention_status,
        ),
    )
    return document_version_id, extraction_run_id


def test_explicit_subtyping_is_deterministic_and_conservative() -> None:
    assert infer_market_terms("SALE", "오피스 경매 매입", None) == {
        "ACQUISITION": "explicit_keyword:ACQUISITION",
        "AUCTION": "explicit_keyword:AUCTION",
    }
    assert infer_market_terms("LEASE", "본사 이전 계획", "공실이 증가") == {
        "RELOCATION": "explicit_keyword:RELOCATION",
        "VACANCY": "explicit_keyword:VACANCY",
    }
    assert infer_market_terms("NEW_SUPPLY", "도심 오피스 준공 완료", None) == {
        "COMPLETION": "explicit_keyword:COMPLETION",
        "SUPPLY": "explicit_keyword:SUPPLY",
    }
    assert infer_market_terms("NEW_SUPPLY", "도심 오피스 2027년 준공 목표", None) == {
        "SUPPLY": "explicit_keyword:SUPPLY",
    }
    assert infer_market_terms("INVESTMENT", "블라인드펀드 조성", None) == {
        "FUNDRAISING": "explicit_keyword:FUNDRAISING",
    }
    # Bare '이전' is ambiguous in Korean and must not subtype a lease article.
    assert infer_market_terms("LEASE", "이전 분기 임대료", None) == {}

    # Collection query provenance alone must never become a managed category.
    assert infer_market_terms("INVESTMENT", "운용사가 오피스 매각 우협을 선정", None) == {}
    assert infer_market_terms("LEASE", "상가임대차보호법 해설", None) == {}


def test_backfill_is_scoped_latest_idempotent_and_does_not_mutate_events(
    tmp_path: Path,
) -> None:
    conn = make_db(tmp_path)
    add_document(
        conn,
        document_id="eligible-sale",
        title="서울 오피스 경매 매입",
        category_id="cat_sale",
    )
    # Only the latest version can project.  The old PF mention must disappear.
    add_document(
        conn,
        document_id="latest-only",
        version_no=1,
        title="과거 PF 기사",
        category_id="cat_pf",
    )
    add_document(
        conn,
        document_id="latest-only",
        version_no=2,
        title="최신 담보대출 실행 기사",
        category_id="cat_loan",
    )
    add_document(
        conn,
        document_id="scope-excluded",
        scope_status="CRE_REVIEW",
        category_id="cat_pf",
    )
    add_document(
        conn,
        document_id="rejected",
        mention_status="REJECTED",
        category_id="cat_pf",
    )
    add_document(
        conn,
        document_id="outside-year",
        published_at="2025-12-31T23:59:59Z",
        category_id="cat_pf",
    )
    conn.execute(
        """INSERT INTO events(
             event_id,canonical_title,primary_category_id,lifecycle_status,verification_level
           ) VALUES('sentinel-event','변경 금지 이벤트','cat_sale','ACTIVE','V2')"""
    )
    conn.commit()
    events_before = conn.execute("SELECT * FROM events ORDER BY event_id").fetchall()
    mentions_before = conn.execute(
        "SELECT * FROM event_mentions ORDER BY event_mention_id"
    ).fetchall()

    rehearsal = backfill_document_market_categories(conn, apply=False)
    assert rehearsal["eligible_documents"] == 2
    assert rehearsal["eligible_mentions"] == 2
    assert rehearsal["assignments_planned"] == 3
    assert rehearsal["assignments_would_insert"] == 3
    assert rehearsal["assignments_inserted"] == 0
    assert conn.execute("SELECT count(*) FROM record_classifications").fetchone()[0] == 0

    first = backfill_document_market_categories(conn, apply=True)
    second = backfill_document_market_categories(conn, apply=True)
    assert first["assignments_inserted"] == 3
    assert second["assignments_inserted"] == 0
    assert second["assignments_existing_current"] == 3

    projected = conn.execute(
        """SELECT r.target_id,t.term_code,r.assignment_role,r.is_primary,
                  r.classifier_version,r.evidence_status,r.review_status,
                  r.source_document_version_id,r.lineage_json,r.record_classification_id,
                  r.classification_scheme_id,r.classification_term_id
           FROM record_classifications r
           JOIN classification_terms t
             USING(classification_scheme_id,classification_term_id)
           ORDER BY r.target_id,t.term_code"""
    ).fetchall()
    assert [(row[0], row[1]) for row in projected] == [
        ("eligible-sale", "ACQUISITION"),
        ("eligible-sale", "AUCTION"),
        ("latest-only", "LOAN"),
    ]
    for row in projected:
        assert row[2:7] == (
            "DERIVED",
            0,
            CLASSIFIER_VERSION,
            "INFERRED",
            "PENDING",
        )
        assert row[9] == stable_assignment_id(row[0], row[10], row[11])
        lineage = json.loads(row[8])
        assert lineage["source_document_version_id"] == row[7]
        assert lineage["source_event_mention_ids"]

    assert conn.execute("SELECT * FROM events ORDER BY event_id").fetchall() == events_before
    assert conn.execute(
        "SELECT * FROM event_mentions ORDER BY event_mention_id"
    ).fetchall() == mentions_before
    conn.close()


def test_existing_current_assignment_is_not_duplicated(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    add_document(conn, document_id="manual-sale", title="오피스 매각 추진", category_id="cat_sale")
    conn.execute(
        """INSERT INTO record_classifications(
             record_classification_id,target_kind,target_id,classification_scheme_id,
             classification_term_id,assignment_role,is_primary,confidence,
             classifier_version,evidence_status,review_status
           ) VALUES(
             'manual-sale-class','DOCUMENT','manual-sale','scheme-market-category',
             'term-market-sale','MANUAL',1,1.0,'MANUAL_V1','MANUAL_REVIEWED','APPROVED'
           )"""
    )
    conn.commit()

    result = backfill_document_market_categories(conn, apply=True)
    assert result["assignments_planned"] == 1
    assert result["assignments_existing_current"] == 1
    assert result["assignments_inserted"] == 0
    rows = conn.execute(
        """SELECT assignment_role,review_status,is_primary
           FROM record_classifications WHERE target_id='manual-sale'"""
    ).fetchall()
    assert rows == [("MANUAL", "APPROVED", 1)]
    conn.close()


def test_explicit_version_handoff_is_authoritative_over_date_window(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    version_id, _ = add_document(
        conn,
        document_id="kst-boundary",
        published_at="2026-08-24T15:30:00Z",
        title="복합개발 사업장 본PF 전환",
        category_id="cat_pf",
    )
    conn.commit()

    # The daily stage selected this as 2026-08-25 KST.  Its explicit hand-off
    # must not be rejected by a same-label UTC date window.
    result = backfill_document_market_categories(
        conn,
        start_date="2026-08-25",
        end_date="2026-08-26",
        document_version_ids=[version_id],
        apply=False,
    )
    assert result["eligible_documents"] == 1
    assert result["assignments_would_insert"] == 1
    assert result["counts_by_term"] == [
        {"key": "PF", "documents": 1, "mentions": 1, "assignments_planned": 1}
    ]
    conn.close()
