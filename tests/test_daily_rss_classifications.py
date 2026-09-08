from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sqlite3

from scripts.process_daily_rss_classifications import (
    PIPELINE_VERSION,
    PROJECTION_CLASSIFIER_VERSION,
    parse_collection_slot,
    process_daily_rss_classifications,
    publication_day_kst,
)


RUNNER = Path(__file__).parents[1] / "operations" / "hermes" / "daily_cre_articles.py"
SCHEMA = Path(__file__).parents[1] / "db" / "v2" / "schema.sql"
SEED = Path(__file__).parents[1] / "db" / "v2" / "seed.sql"


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES('schema_version','3.5.0');
        CREATE TABLE events(event_id TEXT PRIMARY KEY);
        INSERT INTO events VALUES('existing-canonical-event');
        CREATE TABLE event_categories(event_category_id TEXT PRIMARY KEY,code TEXT NOT NULL UNIQUE);
        CREATE TABLE collection_sources(source_id TEXT PRIMARY KEY,source_code TEXT NOT NULL UNIQUE);
        CREATE TABLE collection_jobs(job_id TEXT PRIMARY KEY,source_id TEXT,job_code TEXT);
        CREATE TABLE collection_job_categories(
          job_id TEXT,event_category_id TEXT,is_primary INTEGER,
          PRIMARY KEY(job_id,event_category_id)
        );
        CREATE TABLE collection_runs(
          run_id TEXT PRIMARY KEY,job_id TEXT,scheduled_for TEXT,status_code TEXT,cursor_in TEXT
        );
        CREATE TABLE source_documents(document_id TEXT PRIMARY KEY,source_id TEXT);
        CREATE TABLE document_versions(
          document_version_id TEXT PRIMARY KEY,document_id TEXT,title TEXT,snippet_text TEXT,
          published_at TEXT,collected_at TEXT
        );
        CREATE TABLE run_documents(
          run_id TEXT,document_version_id TEXT,PRIMARY KEY(run_id,document_version_id)
        );
        CREATE TABLE document_scope_assessments(
          document_scope_assessment_id TEXT PRIMARY KEY,document_version_id TEXT,scope_code TEXT,
          classifier_version TEXT,status_code TEXT,reason_codes_json TEXT,evidence_json TEXT,
          assessed_at TEXT,UNIQUE(document_version_id,scope_code,classifier_version)
        );
        CREATE TABLE extraction_runs(
          extraction_run_id TEXT PRIMARY KEY,document_version_id TEXT,pipeline_version TEXT,
          model_name TEXT,model_version TEXT,prompt_or_rule_hash TEXT,started_at TEXT,completed_at TEXT,
          status_code TEXT,error_message TEXT,UNIQUE(document_version_id,pipeline_version)
        );
        CREATE TABLE event_mentions(
          event_mention_id TEXT PRIMARY KEY,extraction_run_id TEXT,extraction_key TEXT,
          event_category_id TEXT,title_raw TEXT,summary_raw TEXT,event_date_start TEXT,
          event_date_end TEXT,date_precision TEXT,confidence REAL,status_code TEXT,
          UNIQUE(extraction_run_id,extraction_key)
        );
        INSERT INTO collection_sources VALUES('source-news','GOOGLE_NEWS_RSS');
        """
    )
    return conn


def add_candidate(
    conn: sqlite3.Connection,
    key: str,
    *,
    title: str | None,
    snippet: str | None,
    published_at: str | None,
    category: str = "SALE",
    slot: str = "2026-08-25T09:15+09:00",
) -> None:
    category_id = f"category-{category.lower()}"
    job_id = f"job-{category.lower()}"
    run_id = f"run-{key}-{category.lower()}"
    conn.execute("INSERT OR IGNORE INTO event_categories VALUES(?,?)", (category_id, category))
    conn.execute("INSERT OR IGNORE INTO collection_jobs VALUES(?,?,?)", (job_id, "source-news", job_id))
    conn.execute(
        "INSERT OR IGNORE INTO collection_job_categories VALUES(?,?,1)",
        (job_id, category_id),
    )
    conn.execute(
        "INSERT INTO collection_runs VALUES(?,?,?,?,?)",
        (
            run_id,
            job_id,
            "2026-08-24T15:00:00Z",
            "COMPLETED",
            json.dumps({"collection_slot": slot}, sort_keys=True),
        ),
    )
    conn.execute("INSERT OR IGNORE INTO source_documents VALUES(?,?)", (f"doc-{key}", "source-news"))
    conn.execute(
        "INSERT OR IGNORE INTO document_versions VALUES(?,?,?,?,?,?)",
        (f"version-{key}", f"doc-{key}", title, snippet, published_at, "2026-08-24T15:20:00Z"),
    )
    conn.execute("INSERT INTO run_documents VALUES(?,?)", (run_id, f"version-{key}"))
    conn.commit()


def projector_spy(calls: list[dict]):
    def project(conn, **kwargs):
        calls.append(kwargs)
        return {
            "classifier_version": PROJECTION_CLASSIFIER_VERSION,
            "document_version_ids": list(kwargs["document_version_ids"]),
            "applied": kwargs["apply"],
        }

    return project


def test_kst_boundary_creates_review_only_mention_and_never_mutates_events() -> None:
    conn = database()
    add_candidate(
        conn,
        "confirmed",
        title="파크원 타워 매각 우선협상대상자 선정",
        snippet="업무용 빌딩 매각 절차가 진행 중이다.",
        published_at="2026-08-24T15:30:00Z",
    )
    calls: list[dict] = []

    report = process_daily_rss_classifications(
        conn,
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 26),
        apply=True,
        projector=projector_spy(calls),
    )

    assert publication_day_kst("2026-08-24T15:30:00Z") == date(2026, 8, 25)
    assert report["scopeStatusCounts"] == {"CRE_CONFIRMED": 1}
    assert report["mentions_inserted"] == 1
    assert report["canonicalEventsBefore"] == report["canonicalEventsAfter"] == 1
    mention = conn.execute(
        "SELECT event_date_start,status_code FROM event_mentions"
    ).fetchone()
    assert mention == (None, "REVIEW_READY")
    assert calls[0]["document_version_ids"] == ["version-confirmed"]
    assert calls[0]["apply"] is True


def test_scope_persists_out_of_scope_and_missing_but_does_not_create_mentions() -> None:
    conn = database()
    add_candidate(
        conn,
        "residential",
        title="아파트 공동주택 매각",
        snippet="주택분양 사업이다.",
        published_at="2026-08-25T01:00:00Z",
    )
    add_candidate(
        conn,
        "empty",
        title=None,
        snippet=None,
        published_at="2026-08-25T02:00:00Z",
    )
    add_candidate(
        conn,
        "no-publication",
        title="센터 오피스 매각 우선협상대상자 선정",
        snippet="업무시설 거래 절차다.",
        published_at=None,
    )

    report = process_daily_rss_classifications(
        conn,
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 26),
        apply=True,
        projector=projector_spy([]),
    )

    statuses = dict(
        conn.execute(
            "SELECT document_version_id,status_code FROM document_scope_assessments"
        ).fetchall()
    )
    assert statuses == {
        "version-empty": "CRE_REVIEW_PARSE_FAILED",
        "version-no-publication": "CRE_CONFIRMED",
        "version-residential": "OUT_OF_SCOPE_RESIDENTIAL",
    }
    assert report["confirmed_without_publication"] == 1
    assert conn.execute("SELECT count(*) FROM event_mentions").fetchone()[0] == 0


def test_apply_is_idempotent_and_dry_run_rolls_back() -> None:
    conn = database()
    add_candidate(
        conn,
        "repeat",
        title="강남 오피스 매각 우협 선정",
        snippet="업무용 빌딩 거래다.",
        published_at="2026-08-25T03:00:00Z",
    )
    calls: list[dict] = []
    kwargs = dict(
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 26),
        projector=projector_spy(calls),
    )

    rehearsal = process_daily_rss_classifications(conn, apply=False, **kwargs)
    assert rehearsal["status"] == "rollback_rehearsal"
    assert rehearsal["mentions_inserted"] == 1
    assert conn.execute("SELECT count(*) FROM document_scope_assessments").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM event_mentions").fetchone()[0] == 0

    first = process_daily_rss_classifications(conn, apply=True, **kwargs)
    second = process_daily_rss_classifications(conn, apply=True, **kwargs)
    assert first["scope_inserted"] == first["mentions_inserted"] == 1
    assert second["scope_inserted"] == second["scope_updated"] == 0
    assert second["scope_unchanged"] == 1
    assert second["mentions_inserted"] == second["mentions_updated"] == 0
    assert second["mentions_unchanged"] == 1
    assert conn.execute("SELECT count(*) FROM extraction_runs").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM event_mentions").fetchone()[0] == 1
    assert conn.execute(
        "SELECT count(*) FROM event_mentions WHERE status_code='APPROVED'"
    ).fetchone()[0] == 0


def test_rerun_protects_a_manually_approved_mention() -> None:
    conn = database()
    add_candidate(
        conn,
        "approved",
        title="강남 오피스 매각 우협 선정",
        snippet="업무시설 매각 거래다.",
        published_at="2026-08-25T03:00:00Z",
    )
    kwargs = dict(
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 26),
        projector=projector_spy([]),
    )
    process_daily_rss_classifications(conn, apply=True, **kwargs)
    conn.execute("UPDATE event_mentions SET status_code='APPROVED'")
    conn.commit()

    report = process_daily_rss_classifications(conn, apply=True, **kwargs)

    assert report["mentions_protected"] == 1
    assert report["approvedMentionsBefore"] == report["approvedMentionsAfter"] == 1
    assert conn.execute("SELECT status_code FROM event_mentions").fetchone() == ("APPROVED",)


def test_collection_slot_limits_the_incremental_input() -> None:
    conn = database()
    add_candidate(
        conn,
        "morning",
        title="여의도 타워 매각",
        snippet="오피스 매각 거래다.",
        published_at="2026-08-25T00:10:00Z",
        slot="2026-08-25T09:00+09:00",
    )
    add_candidate(
        conn,
        "afternoon",
        title="강남 센터 매각",
        snippet="업무시설 매각 거래다.",
        published_at="2026-08-25T05:00:00Z",
        slot="2026-08-25T15:00+09:00",
    )

    report = process_daily_rss_classifications(
        conn,
        collection_slot=parse_collection_slot("2026-08-25T09:00:00+09:00"),
        apply=True,
        projector=projector_spy([]),
    )

    assert report["candidates"] == 1
    assert conn.execute("SELECT count(*) FROM event_mentions").fetchone()[0] == 1


def test_headline_fallback_catches_up_the_bounded_window_not_only_current_ids() -> None:
    conn = database()
    add_candidate(
        conn,
        "current-without-publication",
        title="여의도 오피스 매각",
        snippet="업무시설 매각 절차가 진행 중이다.",
        published_at=None,
        slot="2026-08-25T09:00+09:00",
    )
    headline_calls: list[dict] = []

    def headline_spy(conn, **kwargs):
        headline_calls.append(kwargs)
        return {"classifier_version": "DOCUMENT_HEADLINE_MARKET_CATEGORY_V1"}

    report = process_daily_rss_classifications(
        conn,
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 26),
        collection_slot=parse_collection_slot("2026-08-25T09:00:00+09:00"),
        apply=True,
        projector=projector_spy([]),
        headline_projector=headline_spy,
    )

    assert report["confirmedDocumentVersions"] == 0
    assert len(headline_calls) == 1
    assert headline_calls[0]["start_date"] == "2026-08-25"
    assert headline_calls[0]["end_date"] == "2026-08-26"
    assert headline_calls[0]["document_version_ids"] is None


def test_real_projector_creates_pending_document_assignment_without_events(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "daily-classification.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    conn.execute(
        """INSERT INTO collection_jobs(
             job_id,job_code,job_version,job_kind,source_id,valid_from
           ) VALUES('daily-sale','daily-sale',1,'CATEGORY_SEARCH','src_google_news','2026-01-01')"""
    )
    conn.execute("INSERT INTO collection_job_categories VALUES('daily-sale','cat_sale',1)")
    conn.execute(
        """INSERT INTO collection_runs(
             run_id,job_id,scheduled_for,started_at,completed_at,status_code,cursor_in
           ) VALUES('daily-run','daily-sale','2026-08-25T00:15:00Z','2026-08-25T00:15:00Z',
                    '2026-08-25T00:20:00Z','COMPLETED',?)""",
        (json.dumps({"collection_slot": "2026-08-25T09:15+09:00"}),),
    )
    conn.execute(
        """INSERT INTO source_documents(
             document_id,source_id,canonical_url,publisher_name,document_type,first_seen_at,last_seen_at
           ) VALUES('daily-doc','src_google_news','https://example.test/daily-doc','테스트 언론',
                    'RSS_ITEM','2026-08-24T15:30:00Z','2026-08-24T15:30:00Z')"""
    )
    conn.execute(
        """INSERT INTO document_versions(
             document_version_id,document_id,version_no,title,published_at,collected_at,
             content_sha256,snippet_text,rights_status
           ) VALUES('daily-version','daily-doc',1,'파크원 오피스 매각 우선협상대상자 선정',
                    '2026-08-24T15:30:00Z','2026-08-25T00:20:00Z',?,
                    '업무용 빌딩 매각 절차가 진행 중이다.','EXCERPT_ALLOWED')""",
        ("a" * 64,),
    )
    conn.execute(
        """INSERT INTO run_documents(run_id,document_version_id,discovered_at)
           VALUES('daily-run','daily-version','2026-08-25T00:16:00Z')"""
    )
    conn.execute(
        """INSERT INTO events(
             event_id,canonical_title,primary_category_id,lifecycle_status,verification_level
           ) VALUES('sentinel-event','변경 금지 이벤트','cat_sale','ACTIVE','V2')"""
    )
    conn.commit()
    events_before = conn.execute("SELECT * FROM events ORDER BY event_id").fetchall()

    rehearsal = process_daily_rss_classifications(
        conn,
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 26),
    )
    assert rehearsal["status"] == "rollback_rehearsal"
    assert rehearsal["projection"]["assignments_inserted"] == 1
    assert conn.execute("SELECT count(*) FROM document_scope_assessments").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM event_mentions").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM record_classifications").fetchone()[0] == 0
    assert rehearsal["contextualProjection"]["framesPlanned"] == 1
    assert conn.execute("SELECT count(*) FROM contextual_event_frames").fetchone()[0] == 0

    first = process_daily_rss_classifications(
        conn,
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 26),
        apply=True,
    )
    second = process_daily_rss_classifications(
        conn,
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 26),
        apply=True,
    )

    assignment = conn.execute(
        """SELECT r.target_kind,r.target_id,t.term_code,r.assignment_role,
                  r.classifier_version,r.evidence_status,r.review_status
           FROM record_classifications r
           JOIN classification_terms t
             USING(classification_scheme_id,classification_term_id)"""
    ).fetchone()
    assert assignment == (
        "DOCUMENT",
        "daily-doc",
        "SALE",
        "DERIVED",
        PROJECTION_CLASSIFIER_VERSION,
        "INFERRED",
        "PENDING",
    )
    assert first["projection"]["assignments_inserted"] == 1
    assert second["projection"]["assignments_inserted"] == 0
    assert second["projection"]["assignments_existing_current"] == 1
    assert first["contextualProjection"]["framesInserted"] == 1
    assert first["contextualProjection"]["searchRecordsInserted"] == 1
    assert len(first["contextualProjection"]["inputManifestSha256"]) == 64
    assert len(first["contextualProjection"]["generationKey"]) == 64
    assert second["contextualProjection"]["campaignsInserted"] == 0
    assert second["contextualProjection"]["runsInserted"] == 0
    assert second["contextualProjection"]["framesInserted"] == 0
    frame = conn.execute(
        """SELECT review_status,evidence_start,evidence_end,metadata_json
           FROM contextual_event_frames"""
    ).fetchone()
    assert frame[0] == "CANDIDATE"
    assert frame[1] is not None and frame[2] > frame[1]
    frame_metadata = json.loads(frame[3])
    assert len(frame_metadata["generationKey"]) == 64
    assert len(frame_metadata["outputSha256"]) == 64
    assert conn.execute(
        "SELECT count(*) FROM contextual_event_frames WHERE review_status='APPROVED'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT * FROM events ORDER BY event_id").fetchall() == events_before
    assert conn.execute(
        "SELECT status_code FROM event_mentions WHERE extraction_key='market-category:SALE'"
    ).fetchone() == ("REVIEW_READY",)
    conn.close()


def test_hermes_runner_wires_apply_after_enrichment_without_duplicating_identity() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "scripts/process_daily_rss_classifications.py" in source
    assert source.index("scripts/enrich_document_content.py") < source.index(
        "scripts/process_daily_rss_classifications.py"
    )
    # Keep this wiring check independent of orchestration helper names. Actual
    # execution order, date bounds, and failure handling have behavioral tests
    # in test_daily_cre_articles_orchestrator.py.
    classification_block = source[source.index('"python", "scripts/process_daily_rss_classifications.py"') :]
    assert '"--from-date"' in classification_block
    assert '"--to-date"' in classification_block
    assert '"--apply"' in classification_block
    assert PROJECTION_CLASSIFIER_VERSION not in source
    assert PIPELINE_VERSION not in source
