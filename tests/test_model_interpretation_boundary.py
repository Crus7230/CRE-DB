from pathlib import Path
import sqlite3,sys

ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT))
from scripts.model_interpretation_boundary import export_jobs, import_outputs  # noqa: E402


def seeded() -> sqlite3.Connection:
    c=sqlite3.connect(":memory:"); c.row_factory=sqlite3.Row; c.execute("pragma foreign_keys=on")
    c.executescript("""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT); INSERT INTO schema_meta VALUES('schema_version','3.4.1');
      CREATE TABLE insight_signals(insight_signal_id TEXT PRIMARY KEY,signal_type TEXT,signal_date TEXT,title TEXT,summary_text TEXT,review_status TEXT,severity_code TEXT,confidence_score REAL,algorithm_version TEXT);
      CREATE TABLE insight_signal_evidence(insight_signal_evidence_id TEXT PRIMARY KEY,insight_signal_id TEXT REFERENCES insight_signals(insight_signal_id),target_id TEXT,evidence_role TEXT,evidence_rank INTEGER,evidence_locator TEXT,metadata_json TEXT);
      INSERT INTO insight_signals VALUES('s1','KEYWORD_BURST','2026-08-20','PF 언급 급상승','문서 8건','UNREVIEWED','HIGH',0.82,'KEYWORD_BURST_SIGNAL_V1');
      INSERT INTO insight_signal_evidence VALUES('e1','s1','d1','TRIGGER',1,'기사 A','{"source_name":"Source A","canonical_url":"https://example.com/a","published_at":"2026-08-20"}');
    """)
    c.executescript((ROOT/'db/v2/migrations/3.5.0_model_interpretations.sqlite.sql').read_text(encoding='utf-8'))
    c.execute("insert into analytics_model_registry(model_registry_id,task_code,provider_code,model_name,model_version,embedding_version,prompt_version,prompt_hash,status_code,created_at) values('m1','TOPIC_INTERPRETATION','TEST','MODEL','M1','EMB1','PROMPT1',?,'ENABLED','2026')",('a'*64,)); c.commit(); return c


def test_export_is_deterministic_source_grounded_and_versioned() -> None:
    c=seeded(); first=export_jobs(c,'m1'); second=export_jobs(c,'m1')
    assert first==second and len(first)==1
    job=first[0]
    assert len(job['inputHash'])==64 and job['modelProvenance']=={'modelVersion':'M1','embeddingVersion':'EMB1','promptVersion':'PROMPT1','promptHash':'a'*64}
    assert job['evidence'][0]['documentId']=='d1' and job['evidence'][0]['canonicalUrl']=='https://example.com/a'
    c.close()


def test_import_is_dry_run_safe_draft_only_idempotent_and_evidence_linked() -> None:
    c=seeded(); job=export_jobs(c,'m1')[0]
    output={'signalId':'s1','inputHash':job['inputHash'],'headline':'PF 확산 해석','narrative':'근거 문서에 기반한 초안','topicLabels':['PF']}
    dry=import_outputs(c,'m1',[output],apply=False)
    assert dry['applied'] is False and c.execute('select count(*) from insight_interpretations').fetchone()[0]==0
    applied=import_outputs(c,'m1',[output],apply=True)
    assert applied['interpretationsWritten']==1 and applied['evidenceWritten']==1
    assert c.execute('select interpretation_status from insight_interpretations').fetchone()[0]=='DRAFT'
    import_outputs(c,'m1',[output],apply=True)
    assert c.execute('select count(*) from insight_interpretations').fetchone()[0]==1
    assert c.execute('select count(*) from insight_interpretation_evidence').fetchone()[0]==1
    c.close()
