from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).parents[1]; sys.path.insert(0, str(ROOT))
from scripts.refresh_insight_signals import refresh_insight_signals  # noqa: E402
import pytest

MIGRATION = ROOT / "db/v2/migrations/3.4.1_insight_signals.sqlite.sql"


def database() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:"); c.execute("pragma foreign_keys=on")
    c.executescript("""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL);
      INSERT INTO schema_meta VALUES('schema_version','3.4.0');
      CREATE TABLE keyword_dictionary(keyword_id TEXT PRIMARY KEY,normalized_term TEXT,display_term TEXT,is_collection_bias INTEGER,algorithm_version TEXT,status_code TEXT);
      CREATE TABLE keyword_observations_daily(keyword_observation_id TEXT PRIMARY KEY,bucket_date TEXT,keyword_id TEXT,document_frequency INTEGER,baseline_document_frequency REAL,burst_score REAL,algorithm_version TEXT);
      CREATE TABLE analytics_refresh_runs(analytics_refresh_run_id TEXT PRIMARY KEY,pipeline_code TEXT,status_code TEXT,algorithm_version TEXT,completed_at TEXT);
      CREATE TABLE collection_sources(source_id TEXT PRIMARY KEY,source_name TEXT,authority_tier INTEGER);
      CREATE TABLE source_documents(document_id TEXT PRIMARY KEY,source_id TEXT,canonical_url TEXT);
      CREATE TABLE document_versions(document_version_id TEXT PRIMARY KEY,document_id TEXT,version_no INTEGER,title TEXT,published_at TEXT,snippet_text TEXT);
    """)
    c.executescript(MIGRATION.read_text(encoding="utf-8"))
    c.execute("insert into keyword_dictionary values('kw1','데이터센터','데이터센터',0,'ALG1','ACTIVE')")
    c.execute("insert into analytics_refresh_runs values('r1','KEYWORD_DAILY','COMPLETED','ALG1','2026-08-23T01:00:00Z')")
    c.execute("insert into keyword_observations_daily values('o1','2026-08-22','kw1',8,2,3.46,'ALG1')")
    c.execute("insert into keyword_observations_daily values('o2','2026-08-23','kw1',1,2,0.5,'ALG1')")
    for i, source in enumerate(('s1','s2'), 1):
        c.execute("insert into collection_sources values(?,?,?)", (source,f'출처 {i}',i))
        c.execute("insert into source_documents values(?,?,?)", (f'd{i}',source,f'https://example.com/{i}'))
        c.execute("insert into document_versions values(?,?,?,?,?,?)", (f'v{i}',f'd{i}',1,f'데이터센터 전력 수요 {i}','2026-08-22T00:00:00Z','데이터센터 투자'))
    c.commit(); return c


def test_refresh_is_dry_run_safe_idempotent_and_never_auto_approves() -> None:
    c = database()
    dry = refresh_insight_signals(c, apply=False)
    assert dry["signals_planned"] == 1
    assert c.execute("select count(*) from insight_signals").fetchone()[0] == 0
    first = refresh_insight_signals(c, apply=True)
    second = refresh_insight_signals(c, apply=True)
    assert first["evidence_written"] == 2 and second["signals_planned"] == 1
    signal = c.execute("select review_status,strength_score,evidence_score,source_diversity_score,confidence_score from insight_signals").fetchone()
    assert signal[0] == "UNREVIEWED"
    assert all(0 <= value <= 1 for value in signal[1:])
    evidence = c.execute("select count(*),count(distinct target_id) from insight_signal_evidence").fetchone()
    assert tuple(evidence) == (2,2)
    c.close()

def test_requires_two_sources_and_never_rewrites_grounded_evidence() -> None:
    c=database(); c.execute("delete from document_versions where document_id='d2'"); c.execute("delete from source_documents where document_id='d2'"); c.commit()
    result=refresh_insight_signals(c,apply=True)
    assert result["signals_planned"] == 0 and c.execute("select count(*) from insight_signals").fetchone()[0] == 0
    c.close()

    c=database(); refresh_insight_signals(c,apply=True)
    c.executescript((ROOT/"db/v2/migrations/3.5.0_model_interpretations.sqlite.sql").read_text(encoding="utf-8"))
    c.execute("insert into analytics_model_registry values('m','TOPIC_INTERPRETATION','P','M','1','E1','P1',?,'ENABLED','{}','t',null)",('a'*64,))
    c.execute("insert into analytics_model_runs values('r','m','COMPLETED',1,1,null,null,'t','t',null,'{}')")
    c.execute("insert into insight_interpretations values('i',(select insight_signal_id from insight_signals),'m','r','DRAFT','h','n','[]',?,?,'t',null,null,'{}')",('b'*64,'c'*64))
    c.execute("insert into insight_interpretation_evidence values('ie','i',(select insight_signal_evidence_id from insight_signal_evidence limit 1),'GROUNDING','t')")
    before=c.execute("select insight_signal_evidence_id,source_document_version_id from insight_signal_evidence order by 1").fetchall(); c.commit()
    signal_before=c.execute("select title,summary_text,strength_score,evidence_score,source_diversity_score,confidence_score,computed_at,metadata_json from insight_signals").fetchone()
    c.execute("update keyword_observations_daily set burst_score=9,document_frequency=99 where keyword_observation_id='o1'")
    refresh_insight_signals(c,apply=True)
    assert c.execute("select insight_signal_evidence_id,source_document_version_id from insight_signal_evidence order by 1").fetchall()==before
    assert c.execute("select title,summary_text,strength_score,evidence_score,source_diversity_score,confidence_score,computed_at,metadata_json from insight_signals").fetchone()==signal_before
    c.close()


def test_signal_publication_date_is_utc_and_window_is_half_open() -> None:
    c=database()
    c.execute("update document_versions set published_at='2026-08-23T00:30:00+09:00'")
    utc_result=refresh_insight_signals(c,apply=False,window_start='2026-08-22',window_end='2026-08-23')
    assert utc_result['signals_planned'] == 1
    excluded=refresh_insight_signals(c,apply=False,window_start='2026-08-21',window_end='2026-08-22')
    assert excluded['signals_planned'] == 0
    c.close()
