from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.refresh_keyword_analytics import extract_terms, refresh_keywords  # noqa: E402

MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.4.0_keyword_analytics.sqlite.sql"


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL);
      INSERT INTO schema_meta VALUES('schema_version','3.3.0');
      CREATE TABLE collection_sources(source_id TEXT PRIMARY KEY,source_code TEXT);
      CREATE TABLE collection_jobs(job_id TEXT PRIMARY KEY,query_template TEXT,is_active INTEGER);
      CREATE TABLE source_documents(document_id TEXT PRIMARY KEY,source_id TEXT,FOREIGN KEY(source_id) REFERENCES collection_sources(source_id));
      CREATE TABLE document_versions(document_version_id TEXT PRIMARY KEY,document_id TEXT,version_no INTEGER,title TEXT,published_at TEXT,collected_at TEXT,snippet_text TEXT,FOREIGN KEY(document_id) REFERENCES source_documents(document_id));
      CREATE TABLE document_scope_assessments(
        document_scope_assessment_id TEXT PRIMARY KEY,
        document_version_id TEXT NOT NULL,
        scope_code TEXT NOT NULL,
        classifier_version TEXT NOT NULL,
        status_code TEXT NOT NULL,
        assessed_at TEXT NOT NULL
      );
    """)
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    conn.execute("insert into collection_sources values('s1','NEWS')")
    conn.execute("insert into collection_jobs values('j1','(오피스 OR 매각)',1)")
    conn.execute("insert into source_documents values('d1','s1')")
    conn.execute("insert into source_documents values('d2','s1')")
    conn.execute("insert into source_documents values('d3','s1')")
    conn.execute("insert into document_versions values('v1','d1',1,'서울 오피스 매각 매각','2026-08-20T00:00:00Z','2026-08-21T00:00:00Z','오피스 거래')")
    conn.execute("insert into document_versions values('v2','d2',1,'서울 물류센터 매각','2026-08-20T00:00:00Z','2026-08-21T00:00:00Z','물류센터 거래')")
    conn.execute("insert into document_versions values('v3','d3',1,'과거 백필 문서',NULL,'2026-08-21T00:00:00Z','시장 급증 아님')")
    conn.commit()
    return conn


def test_extraction_is_deterministic_and_document_frequency_counts_once() -> None:
    first = extract_terms("서울 오피스 매각 매각", "오피스 거래")
    second = extract_terms("서울 오피스 매각 매각", "오피스 거래")
    assert first == second
    assert first.count("매각") == 1
    assert "오피스" in first


def test_refresh_dry_run_apply_bias_and_idempotency() -> None:
    conn = database()
    dry = refresh_keywords(conn, apply=False)
    assert dry["documents_in_scope"] == 2
    assert conn.execute("select count(*) from keyword_observations_daily").fetchone()[0] == 0
    first = refresh_keywords(conn, apply=True)
    rows_after_first = conn.execute("select count(*) from keyword_observations_daily").fetchone()[0]
    second = refresh_keywords(conn, apply=True)
    rows_after_second = conn.execute("select count(*) from keyword_observations_daily").fetchone()[0]
    assert first["documents_excluded_missing_publication"] == 1
    assert second["observations_written"] == first["observations_written"]
    assert rows_after_second == rows_after_first
    keyword = conn.execute("select is_collection_bias from keyword_dictionary where normalized_term='매각'").fetchone()
    assert keyword[0] == 1
    assert conn.execute("select count(*) from keyword_dictionary where normalized_term='물류센터'").fetchone()[0] == 0
    df = conn.execute("""select o.document_frequency from keyword_observations_daily o join keyword_dictionary k using(keyword_id)
      where k.normalized_term='매각' and o.bucket_date='2026-08-20'""").fetchone()[0]
    assert df == 2
    conn.close()


def test_refresh_window_is_half_open_and_excludes_old_archive_rows() -> None:
    conn=database()
    conn.execute("insert into source_documents values('d4','s1')")
    conn.execute("insert into source_documents values('d5','s1')")
    conn.execute("insert into document_versions values('v4','d4',1,'end boundary','2026-08-21T00:00:00Z','2026-08-21T00:00:00Z','시장')")
    conn.execute("insert into document_versions values('v5','d5',1,'old archive','2020-01-01T00:00:00Z','2020-01-01T00:00:00Z','시장')")
    conn.execute("insert into keyword_dictionary values('boundary-a','경계A','경계A','TOKEN','ACTIVE',0,'KO_TITLE_PHRASE_DF_V1','{}','t','t')")
    conn.execute("insert into keyword_dictionary values('boundary-b','경계B','경계B','TOKEN','ACTIVE',0,'KO_TITLE_PHRASE_DF_V1','{}','t','t')")
    conn.execute("insert into keyword_observations_daily values('boundary-o','2026-08-21','boundary-a','ALL',1,1,0,1,'t','2026-08-21','2026-08-22','KO_TITLE_PHRASE_DF_V1','{}','{}')")
    conn.execute("insert into keyword_cooccurrences_daily values('boundary-c','2026-08-21','boundary-a','boundary-b','ALL',1,'t','2026-08-21','2026-08-22','KO_TITLE_PHRASE_DF_V1','{}')")
    report=refresh_keywords(conn,apply=True,window_start='2026-08-20',window_end='2026-08-21')
    assert report['documents_in_scope'] == 2
    assert conn.execute("select count(*) from keyword_observations_daily where keyword_observation_id='boundary-o'").fetchone()[0] == 1
    assert conn.execute("select count(*) from keyword_cooccurrences_daily where keyword_cooccurrence_id='boundary-c'").fetchone()[0] == 1
    conn.close()


def test_refresh_excludes_latest_out_of_scope_assessment_without_deleting_source() -> None:
    conn = database()
    conn.execute("""insert into document_scope_assessments values(
      'a1','v1','CRE','NEWS_CRE_SCOPE_RULE_V3','OUT_OF_SCOPE_NON_CRE','2026-08-22T00:00:00Z'
    )""")
    report = refresh_keywords(conn, apply=True)
    assert report["documents_excluded_scope"] == 1
    assert report["documents_in_scope"] == 1
    assert conn.execute("select count(*) from source_documents where document_id='d1'").fetchone()[0] == 1
    assert conn.execute("""select count(*) from keyword_observations_daily o
      join keyword_dictionary k using(keyword_id) where k.normalized_term='오피스'""").fetchone()[0] == 0
    conn.close()
