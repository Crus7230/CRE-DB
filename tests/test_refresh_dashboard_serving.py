from __future__ import annotations

from pathlib import Path
import json
import re
import sqlite3
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.refresh_dashboard_serving import (  # noqa: E402
    refresh_dashboard_serving,
)


SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"
PERMIT_MIGRATIONS = [
    ROOT / "db" / "v2" / "migrations" / name
    for name in (
        "3.6.0_building_permits.sqlite.sql",
        "3.6.1_building_permit_source_dimension.sqlite.sql",
        "3.6.2_building_permit_event_date_quality.sqlite.sql",
        "3.6.3_building_permit_area_quality.sqlite.sql",
        "3.6.4_building_permit_compact_serving.sqlite.sql",
        "3.6.5_building_permit_current_serving.sqlite.sql",
    )
]


def base_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    return conn


def add_article(
    conn: sqlite3.Connection,
    key: str,
    *,
    published_at: str | None,
    version_no: int = 1,
    scope: str = "CRE_CONFIRMED",
    title: str | None = None,
) -> tuple[str, str]:
    document_id = f"doc-{key}"
    version_id = f"version-{key}-{version_no}"
    conn.execute(
        """INSERT OR IGNORE INTO source_documents(
             document_id,source_id,canonical_url,publisher_name,document_type,
             first_seen_at,last_seen_at
           ) VALUES(?,'src_google_news',?,'테스트 언론','RSS_ITEM',
                    '2026-09-06T00:00:00Z','2026-09-07T03:00:00Z')""",
        (document_id, f"https://example.test/{key}"),
    )
    conn.execute(
        """INSERT INTO document_versions(
             document_version_id,document_id,version_no,title,published_at,collected_at,
             content_sha256,snippet_text,rights_status
           ) VALUES(?,?,?,?,?,'2026-09-07T03:00:00Z',?,?,'EXCERPT_ALLOWED')""",
        (
            version_id,
            document_id,
            version_no,
            title or f"서울 오피스 매각 {key}",
            published_at,
            f"{key}-{version_no}".encode().hex().ljust(64, "0")[:64],
            f"업무용 빌딩 매각 {key}",
        ),
    )
    conn.execute(
        """INSERT INTO document_scope_assessments(
             document_scope_assessment_id,document_version_id,scope_code,
             classifier_version,status_code,assessed_at
           ) VALUES(?,?,'CRE','TEST_SCOPE',?,'2026-09-07T03:00:00Z')""",
        (f"scope-{key}-{version_no}", version_id, scope),
    )
    return document_id, version_id


def add_category(
    conn: sqlite3.Connection,
    document_id: str,
    version_id: str,
    *,
    key: str,
    term_id: str,
    review_status: str,
    is_primary: int,
    confidence: float,
    assigned_at: str,
) -> None:
    conn.execute(
        """INSERT INTO record_classifications(
             record_classification_id,target_kind,target_id,classification_scheme_id,
             classification_term_id,assignment_role,is_primary,confidence,classifier_version,
             evidence_status,source_document_version_id,review_status,assigned_at
           ) VALUES(?,'DOCUMENT',?,'scheme-market-category',?,'DERIVED',?,?,?,
                    'INFERRED',?,?,?)""",
        (
            f"class-{key}", document_id, term_id, is_primary, confidence,
            f"TEST-{key}", version_id, review_status, assigned_at,
        ),
    )


def legacy_daily_rows(conn: sqlite3.Connection, article_date: str) -> list[tuple[str, str]]:
    return conn.execute(
        """WITH latest_versions AS (
             SELECT dv.*,row_number() OVER (
               PARTITION BY document_id ORDER BY version_no DESC,document_version_id DESC
             ) AS rn FROM document_versions dv
           ), latest_scope AS (
             SELECT dsa.*,row_number() OVER (
               PARTITION BY document_version_id,scope_code
               ORDER BY assessed_at DESC,classifier_version DESC,
                        document_scope_assessment_id DESC
             ) AS rn FROM document_scope_assessments dsa WHERE scope_code='CRE'
           ), eligible AS (
             SELECT dv.document_id,dv.document_version_id,dv.published_at
             FROM latest_versions dv
             JOIN source_documents sd ON sd.document_id=dv.document_id
             JOIN latest_scope scope ON scope.document_version_id=dv.document_version_id
                                    AND scope.rn=1
             WHERE dv.rn=1 AND sd.document_type IN ('RSS_ITEM','ARTICLE')
               AND scope.status_code='CRE_CONFIRMED'
               AND date(dv.published_at,'+9 hours')=?
           ), ranked_topics AS (
             SELECT e.document_id,t.term_code,rc.review_status,rc.is_primary,rc.confidence,
                    row_number() OVER (
                      PARTITION BY e.document_id,t.term_code
                      ORDER BY CASE rc.review_status WHEN 'APPROVED' THEN 0 WHEN 'PENDING' THEN 1 ELSE 2 END,
                               rc.is_primary DESC,rc.confidence IS NULL,rc.confidence DESC,
                               rc.assigned_at DESC,rc.record_classification_id DESC
                    ) AS rn
             FROM eligible e
             JOIN record_classifications rc
               ON rc.target_kind='DOCUMENT' AND rc.target_id=e.document_id
             JOIN classification_schemes s USING(classification_scheme_id)
             JOIN classification_terms t USING(classification_scheme_id,classification_term_id)
             WHERE s.scheme_code='MARKET_CATEGORY'
               AND rc.review_status NOT IN ('REJECTED','SUPERSEDED')
               AND rc.valid_to IS NULL
           )
           SELECT e.document_id,coalesce((
             SELECT group_concat(term_code||':'||review_status,',') FROM (
               SELECT term_code,review_status FROM ranked_topics topic
               WHERE topic.document_id=e.document_id AND topic.rn=1
               ORDER BY CASE review_status WHEN 'APPROVED' THEN 0 ELSE 1 END,
                        is_primary DESC,confidence DESC,term_code
             )
           ),'')
           FROM eligible e ORDER BY e.published_at DESC,e.document_id""",
        (article_date,),
    ).fetchall()


def projected_daily_rows(conn: sqlite3.Connection, article_date: str) -> list[tuple[str, str]]:
    return conn.execute(
        """SELECT article.document_id,coalesce((
             SELECT group_concat(term_code||':'||
               CASE status_code WHEN 'CONFIRMED' THEN 'APPROVED' ELSE 'PENDING' END,',')
             FROM (
               SELECT term_code,status_code FROM serving_daily_article_topics topic
               WHERE topic.document_id=article.document_id ORDER BY topic_rank,term_code
             )
           ),'')
           FROM serving_daily_articles article
           WHERE article.article_date=?
           ORDER BY article.published_at DESC,article.document_id""",
        (article_date,),
    ).fetchall()


def test_daily_projection_matches_legacy_ids_topics_and_date_boundaries(tmp_path: Path) -> None:
    conn = base_database(tmp_path / "daily-serving.db")
    old_doc, old_version = add_article(conn, "latest", published_at="2026-09-06T10:00:00Z", version_no=1)
    new_doc, new_version = add_article(conn, "latest", published_at="2026-09-07T01:00:00Z", version_no=2)
    assert old_doc == new_doc
    boundary_doc, boundary_version = add_article(conn, "boundary", published_at="2026-09-06T15:00:00Z")
    add_article(conn, "before-boundary", published_at="2026-09-06T14:59:59Z")
    add_article(conn, "malformed", published_at="not-a-date")
    add_article(conn, "null", published_at=None)
    add_article(conn, "scope", published_at="2026-09-07T02:00:00Z")
    conn.execute(
        """INSERT INTO document_scope_assessments(
             document_scope_assessment_id,document_version_id,scope_code,classifier_version,
             status_code,assessed_at
           ) VALUES('scope-newer', 'version-scope-1','CRE','ZZZ','CRE_REVIEW','2026-09-07T04:00:00Z')"""
    )
    add_category(
        conn, new_doc, new_version, key="sale-pending", term_id="term-market-sale",
        review_status="PENDING", is_primary=1, confidence=0.95,
        assigned_at="2026-09-07T02:00:00Z",
    )
    add_category(
        conn, new_doc, new_version, key="sale-approved", term_id="term-market-sale",
        review_status="APPROVED", is_primary=0, confidence=0.5,
        assigned_at="2026-09-07T01:00:00Z",
    )
    add_category(
        conn, boundary_doc, boundary_version, key="permit", term_id="term-market-permit",
        review_status="PENDING", is_primary=1, confidence=0.9,
        assigned_at="2026-09-07T02:00:00Z",
    )
    conn.commit()
    raw_counts = {
        table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        for table in ("source_documents", "document_versions", "document_scope_assessments", "record_classifications")
    }
    legacy_sep7 = legacy_daily_rows(conn, "2026-09-07")
    legacy_sep6 = legacy_daily_rows(conn, "2026-09-06")

    report = refresh_dashboard_serving(
        conn, generated_at="2026-09-08T00:00:00.000Z"
    )
    assert projected_daily_rows(conn, "2026-09-07") == legacy_sep7
    assert projected_daily_rows(conn, "2026-09-06") == legacy_sep6
    sep7_ids = [row[0] for row in projected_daily_rows(conn, "2026-09-07")]
    assert sep7_ids == [new_doc, boundary_doc]
    assert "doc-malformed" not in sep7_ids and "doc-null" not in sep7_ids
    assert projected_daily_rows(conn, "2026-09-07")[0][1] == "SALE:APPROVED"
    assert report["dailyArticles"]["latestAvailableDate"] == "2026-09-07"
    assert report["dailyArticles"]["articleRows"] == 3
    assert report["dailyArticles"]["detailRows"] == 3
    server_source = (ROOT / "web" / "src" / "lib" / "server" / "daily-articles.ts").read_text(encoding="utf-8")
    daily_sql = re.search(r"export const dailyArticlesSql = `([\s\S]*?)`;", server_source)
    assert daily_sql is not None
    plan = [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {daily_sql.group(1)}", ("2026-09-07",))]
    assert any("SEARCH article USING INDEX ix_serving_daily_articles_date_order" in step for step in plan)
    assert not any("SCAN serving_daily_articles" in step for step in plan)
    assert not any("SCAN article USING INDEX ix_serving_daily_articles_date_order" in step for step in plan)
    detail = json.loads(conn.execute(
        "SELECT payload_json FROM serving_daily_article_details WHERE document_id=?",
        (new_doc,),
    ).fetchone()[0])
    assert detail["storedText"] is None
    assert detail["classifications"][0]["termCode"] == "SALE"
    assert {
        table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        for table in raw_counts
    } == raw_counts
    conn.close()


def test_permit_projection_uses_latest_completed_full_snapshot_and_valid_events(tmp_path: Path) -> None:
    conn = base_database(tmp_path / "permit-serving.db")
    for migration in PERMIT_MIGRATIONS:
        conn.executescript(migration.read_text(encoding="utf-8"))
    conn.execute(
        """INSERT INTO collection_sources(
             source_id,source_code,source_name,source_kind,authority_tier,collection_policy
           ) VALUES('src_seoul_building_permit','SEOUL_BUILDING_PERMIT',
                    '서울 열린데이터광장','OFFICIAL_API',1,'API_ALLOWED')"""
    )
    conn.executemany(
        """INSERT INTO building_permit_snapshots(
             snapshot_id,source_id,snapshot_kind,status_code,started_at,completed_at,
             source_as_of_date,candidate_count
           ) VALUES(?,?,?,?,?,?,?,?)""",
        [
            ("old", "src_seoul_building_permit", "FULL", "COMPLETED", "2026-09-01", "2026-09-01T01:00:00Z", "2026-09-01", 1),
            ("new", "src_seoul_building_permit", "FULL", "COMPLETED", "2026-09-07", "2026-09-07T01:00:00Z", "2026-09-07", 2),
            ("partial", "src_seoul_building_permit", "FULL", "PARTIAL", "2026-09-08", None, "2026-09-08", 1),
        ],
    )
    records = [
        ("rv1", "key1", "2026-08-01", 1000.0),
        ("rv2", "key2", "1899-12-01", 3_000_000.0),
        ("rv-partial", "partial-key", "2026-09-08", 100.0),
    ]
    for index, (record_id, source_key, permit_date, area) in enumerate(records, 1):
        conn.execute(
            """INSERT INTO building_permit_record_versions(
                 record_version_id,source_id,source_record_key,revision_no,payload_sha256,raw_json,
                 district_name,total_floor_area_m2,permit_date,first_seen_at,last_seen_at,created_at
               ) VALUES(?,'src_seoul_building_permit',?,1,?,'{}','강남구',?,?,
                        '2026-09-01T00:00:00Z','2026-09-07T00:00:00Z','2026-09-01T00:00:00Z')""",
            (record_id, source_key, f"{index:064x}", area, permit_date),
        )
        conn.execute(
            """INSERT INTO building_permit_classifications(
                 classification_id,record_version_id,rule_version,scope_status,asset_type,
                 construction_action,confidence_score,is_current,classified_at
               ) VALUES(?,?,'RULE1','IN_SCOPE','OFFICE','NEW_SUPPLY',0.9,1,'2026-09-07')""",
            (f"class-{record_id}", record_id),
        )
    conn.execute("INSERT INTO building_permit_snapshot_records VALUES('old','rv1',1)")
    conn.execute("INSERT INTO building_permit_snapshot_records VALUES('new','rv1',1)")
    conn.execute("INSERT INTO building_permit_snapshot_records VALUES('new','rv2',2)")
    conn.execute("INSERT INTO building_permit_snapshot_records VALUES('partial','rv-partial',1)")
    conn.commit()
    raw_counts = {
        table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        for table in ("building_permit_snapshots", "building_permit_record_versions", "building_permit_snapshot_records")
    }

    report = refresh_dashboard_serving(
        conn, generated_at="2026-09-08T00:00:00.000Z"
    )["buildingPermits"]
    assert report["seoulSnapshotId"] == "new"
    assert report["seoulCurrentRows"] == 2
    assert report["fullSnapshotCandidateParity"]["src_seoul_building_permit"] is True
    assert conn.execute(
        "SELECT source_snapshot_id,count(*) FROM building_permit_current_serving GROUP BY source_snapshot_id"
    ).fetchall() == [("new", 2)]
    assert conn.execute(
        """SELECT event_month,permit_count,total_floor_area_m2,invalid_area_count
           FROM building_permit_monthly_serving"""
    ).fetchall() == [("2026-08", 1, 1000.0, 0)]
    assert conn.execute(
        "SELECT permit_date_quality,area_quality_status FROM building_permit_current_serving WHERE source_record_key='key2'"
    ).fetchone() == ("BEFORE_1900", "ABOVE_2M")
    assert {
        table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        for table in raw_counts
    } == raw_counts
    conn.close()
