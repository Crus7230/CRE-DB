from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_headline_market_categories import (  # noqa: E402
    CLASSIFIER_VERSION,
    backfill_headline_market_categories,
    infer_headline_market_category,
)


SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"


def database(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "headline-market-category.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    return conn


def add_document(
    conn: sqlite3.Connection,
    key: str,
    *,
    title: str | None,
    snippet: str | None = None,
    published_at: str | None = "2026-09-07T01:00:00Z",
    scope: str = "CRE_CONFIRMED",
    version_no: int = 1,
) -> str:
    document_id = f"doc-{key}"
    version_id = f"version-{key}-{version_no}"
    conn.execute(
        """INSERT OR IGNORE INTO source_documents(
             document_id,source_id,canonical_url,publisher_name,document_type,
             first_seen_at,last_seen_at
           ) VALUES(?,'src_google_news',?,'테스트 언론','RSS_ITEM',
                    '2026-09-07T01:00:00Z','2026-09-07T01:00:00Z')""",
        (document_id, f"https://example.test/{key}"),
    )
    conn.execute(
        """INSERT INTO document_versions(
             document_version_id,document_id,version_no,title,published_at,collected_at,
             content_sha256,snippet_text,rights_status
           ) VALUES(?,?,?,?,?,'2026-09-07T02:00:00Z',?,?,'EXCERPT_ALLOWED')""",
        (version_id, document_id, version_no, title, published_at, f"{version_no:064x}", snippet),
    )
    conn.execute(
        """INSERT INTO document_scope_assessments(
             document_scope_assessment_id,document_version_id,scope_code,
             classifier_version,status_code,assessed_at
           ) VALUES(?,?,'CRE','TEST_SCOPE',?,'2026-09-07T02:00:00Z')""",
        (f"scope-{key}-{version_no}", version_id, scope),
    )
    return version_id


def test_rule_requires_explicit_asset_and_action_evidence() -> None:
    golf = infer_headline_market_category(
        "[단독] 군인공제회 27홀 록인김해 골프장 매각 유찰",
        None,
    )
    hotel = infer_headline_market_category(
        "워싱턴DC 트럼프 호텔 매각",
        "부동산 거래 절차가 시작됐다.",
    )
    assert golf and golf["term_code"] == "SALE" and golf["confidence"] == 0.9
    assert hotel and hotel["term_code"] == "SALE"
    assert infer_headline_market_category("기업 지분 매각", "주식 거래") is None
    assert infer_headline_market_category("서울 오피스 시장 전망", "가격이 보합세다") is None


def test_fallback_is_unclassified_latest_pending_and_idempotent(tmp_path: Path) -> None:
    conn = database(tmp_path)
    golf_version = add_document(
        conn,
        "golf",
        title="[단독] 군인공제회 27홀 록인김해 골프장 매각 유찰",
    )
    add_document(conn, "hotel", title="워싱턴DC 트럼프 호텔 매각")
    add_document(conn, "corporate", title="기업 지분 매각", snippet="주식 거래")
    add_document(conn, "review", title="서울 오피스 매각", scope="CRE_REVIEW")
    # The old version is explicit but the latest version is not; latest wins.
    add_document(conn, "latest", title="서울 오피스 매각", version_no=1)
    add_document(conn, "latest", title="서울 오피스 시장 전망", version_no=2)
    conn.execute(
        """INSERT INTO events(
             event_id,canonical_title,primary_category_id,lifecycle_status,verification_level
           ) VALUES('sentinel','변경 금지','cat_sale','ACTIVE','V2')"""
    )
    events_before = conn.execute("SELECT * FROM events").fetchall()
    conn.commit()

    dry_run = backfill_headline_market_categories(conn, apply=False)
    assert dry_run["eligible_unclassified_documents"] == 4
    assert dry_run["projected_documents"] == 2
    assert conn.execute("SELECT count(*) FROM record_classifications").fetchone()[0] == 0

    first = backfill_headline_market_categories(conn, apply=True)
    second = backfill_headline_market_categories(conn, apply=True)
    assert first["assignments_inserted"] == 2
    assert second["eligible_unclassified_documents"] == 2
    assert second["assignments_inserted"] == 0
    rows = conn.execute(
        """SELECT r.target_id,t.term_code,r.is_primary,r.classifier_version,
                  r.evidence_status,r.review_status,r.source_document_version_id,
                  r.evidence_locator,r.lineage_json,r.metadata_json
           FROM record_classifications r
           JOIN classification_terms t USING(classification_scheme_id,classification_term_id)
           ORDER BY r.target_id"""
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [("doc-golf", "SALE"), ("doc-hotel", "SALE")]
    for row in rows:
        assert row[2:6] == (1, CLASSIFIER_VERSION, "INFERRED", "PENDING")
        assert row[7].endswith("#title+snippet")
        lineage = json.loads(row[8])
        assert lineage["collection_query_used"] is False
        assert lineage["projection_method"] == "DETERMINISTIC_HEADLINE_FALLBACK"
        metadata = json.loads(row[9])
        assert metadata["rule_version"] == CLASSIFIER_VERSION
    assert rows[0][6] == golf_version
    assert conn.execute("SELECT * FROM events").fetchall() == events_before
    conn.close()


def test_existing_governed_category_blocks_fallback(tmp_path: Path) -> None:
    conn = database(tmp_path)
    add_document(conn, "manual", title="서울 오피스 매각")
    conn.execute(
        """INSERT INTO record_classifications(
             record_classification_id,target_kind,target_id,classification_scheme_id,
             classification_term_id,assignment_role,is_primary,confidence,
             classifier_version,evidence_status,review_status
           ) VALUES('manual','DOCUMENT','doc-manual','scheme-market-category',
                    'term-market-sale','MANUAL',1,1,'MANUAL_V1','MANUAL_REVIEWED','APPROVED')"""
    )
    conn.commit()
    report = backfill_headline_market_categories(conn, apply=True)
    assert report["eligible_unclassified_documents"] == 0
    assert conn.execute("SELECT count(*) FROM record_classifications").fetchone()[0] == 1
    conn.close()
