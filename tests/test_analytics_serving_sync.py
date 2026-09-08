from pathlib import Path
import sqlite3,sys
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from scripts.sync_analytics_serving import build_payload, reconcile_sql, upsert_sql  # noqa:E402


def db():
 c=sqlite3.connect(':memory:');c.executescript("""
 CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT);INSERT INTO schema_meta VALUES('schema_version','3.5.0');
 CREATE TABLE analytics_refresh_runs(analytics_refresh_run_id TEXT PRIMARY KEY,pipeline_code TEXT,status_code TEXT,algorithm_version TEXT,window_start TEXT,window_end TEXT,source_scope_code TEXT,input_count INTEGER,output_count INTEGER,started_at TEXT,completed_at TEXT,error_code TEXT,metadata_json TEXT);
 CREATE TABLE keyword_dictionary(keyword_id TEXT PRIMARY KEY,normalized_term TEXT,display_term TEXT,term_kind TEXT,status_code TEXT,is_collection_bias INTEGER,algorithm_version TEXT,metadata_json TEXT,created_at TEXT,updated_at TEXT);
 CREATE TABLE keyword_observations_daily(keyword_observation_id TEXT PRIMARY KEY,bucket_date TEXT,keyword_id TEXT,source_scope_code TEXT,document_frequency INTEGER,mention_count INTEGER,baseline_document_frequency REAL,burst_score REAL,computed_at TEXT,window_start TEXT,window_end TEXT,algorithm_version TEXT,source_scope_json TEXT,metadata_json TEXT);
 CREATE TABLE keyword_cooccurrences_daily(keyword_cooccurrence_id TEXT PRIMARY KEY,bucket_date TEXT,keyword_left_id TEXT,keyword_right_id TEXT,source_scope_code TEXT,document_frequency INTEGER,computed_at TEXT,window_start TEXT,window_end TEXT,algorithm_version TEXT,metadata_json TEXT);
 CREATE TABLE insight_signals(insight_signal_id TEXT PRIMARY KEY,signal_type TEXT,signal_date TEXT,title TEXT,summary_text TEXT,review_status TEXT,severity_code TEXT,keyword_id TEXT,strength_score REAL,evidence_score REAL,source_diversity_score REAL,confidence_score REAL,algorithm_version TEXT,computed_at TEXT,window_start TEXT,window_end TEXT,metadata_json TEXT);
 CREATE TABLE insight_signal_evidence(insight_signal_evidence_id TEXT PRIMARY KEY,insight_signal_id TEXT,target_kind TEXT,target_id TEXT,evidence_role TEXT,source_document_version_id TEXT,evidence_rank INTEGER,evidence_locator TEXT,metadata_json TEXT,created_at TEXT);
 CREATE TABLE analytics_model_registry(model_registry_id TEXT PRIMARY KEY,task_code TEXT,provider_code TEXT,model_name TEXT,model_version TEXT,embedding_version TEXT,prompt_version TEXT,prompt_hash TEXT,status_code TEXT,config_json TEXT,created_at TEXT,retired_at TEXT);
 CREATE TABLE analytics_model_runs(model_run_id TEXT PRIMARY KEY,model_registry_id TEXT,status_code TEXT,input_count INTEGER,output_count INTEGER,input_token_count INTEGER,output_token_count INTEGER,started_at TEXT,completed_at TEXT,error_code TEXT,metadata_json TEXT);
 CREATE TABLE insight_interpretations(interpretation_id TEXT PRIMARY KEY,insight_signal_id TEXT,model_registry_id TEXT,model_run_id TEXT,interpretation_status TEXT CHECK(interpretation_status IN ('DRAFT','IN_REVIEW','APPROVED','REJECTED','SUPERSEDED')),headline TEXT,narrative_text TEXT,topic_labels_json TEXT,input_hash TEXT,output_hash TEXT,generated_at TEXT,reviewed_at TEXT,reviewed_by TEXT,metadata_json TEXT);
 CREATE TABLE insight_interpretation_evidence(interpretation_evidence_id TEXT PRIMARY KEY,interpretation_id TEXT,insight_signal_evidence_id TEXT,evidence_role TEXT,created_at TEXT);
 """)
 for k in ('k1','k2'): c.execute("insert into keyword_dictionary values(?,?,?,'TOKEN','ACTIVE',0,'A','{}','t','t')",(k,k,k))
 c.execute("insert into analytics_refresh_runs values('run-1','KEYWORD_DAILY','COMPLETED','A','2026-05-01','2026-08-21','ALL',2,1,'2026-08-21T00:00:00Z','2026-08-21T00:00:01Z',NULL,'{}')")
 c.execute("insert into keyword_observations_daily values('new','2026-08-20','k1','ALL',3,3,1,2,'t','a','b','A','{}','{}')")
 c.execute("insert into keyword_observations_daily values('old','2025-01-01','k2','ALL',3,3,1,2,'t','a','b','A','{}','{}')")
 return c

def test_payload_is_recent_and_reference_closed():
 p=build_payload(db(),window_days=90)
 assert [r[0] for r in p['keyword_observations_daily']]==['new']
 assert [r[0] for r in p['keyword_dictionary']]==['k1']
 assert [r[0] for r in p['analytics_refresh_runs']]==['run-1']
 assert p['_sync_scope']=={'keyword_start':'2026-05-23','keyword_end':'2026-08-21','superseded_signal_ids':[],'superseded_interpretation_ids':[]}

def test_upsert_preserves_terminal_human_review():
 s=upsert_sql('insight_signals')
 assert "APPROVED" in s and "REJECTED" in s and "review_status" in s
 i=upsert_sql('insight_interpretations')
 assert "interpretation_status" in i and "SUPERSEDED" in i


def test_payload_excludes_interpretation_when_parent_signal_is_superseded():
 c=db()
 c.execute("insert into insight_signals values('signal-1','KEYWORD_BURST','2026-08-20','t','s','SUPERSEDED','MEDIUM','k1',1,1,1,1,'A','t','a','b','{}')")
 c.execute("insert into analytics_model_registry values('model-1','INTERPRET','LOCAL','m','1',NULL,'p','h','ACTIVE','{}','t',NULL)")
 c.execute("insert into analytics_model_runs values('model-run-1','model-1','COMPLETED',1,1,1,1,'t','t',NULL,'{}')")
 c.execute("insert into insight_interpretations values('interpretation-1','signal-1','model-1','model-run-1','DRAFT','h','n','[]','i','o','t',NULL,NULL,'{}')")
 p=build_payload(c,window_days=90)
 assert p['insight_signals']==[]
 assert p['insight_interpretations']==[]
 assert p['analytics_model_runs']==[]
 assert p['_sync_scope']['superseded_signal_ids']==['signal-1']
 assert p['_sync_scope']['superseded_interpretation_ids']==[]


def test_reconcile_sql_removes_stale_keyword_rows_with_half_open_window():
 sql=reconcile_sql('keyword_observations_daily')
 assert 'bucket_date >= %s' in sql
 assert 'bucket_date < %s' in sql
 assert 'NOT EXISTS' in sql
 assert 'keyword_observation_id' in sql


def test_reconcile_sql_only_supersedes_unreviewed_human_review_entities():
 signal_sql=reconcile_sql('insight_signals')
 assert "review_status='UNREVIEWED'" in signal_sql
 assert "review_status='SUPERSEDED'" in signal_sql
 assert '= ANY(%s)' in signal_sql
 assert 'NOT EXISTS' not in signal_sql
 interpretation_sql=reconcile_sql('insight_interpretations')
 assert "interpretation_status IN ('DRAFT','IN_REVIEW')" in interpretation_sql
 assert "interpretation_status='SUPERSEDED'" in interpretation_sql
 assert '= ANY(%s)' in interpretation_sql
