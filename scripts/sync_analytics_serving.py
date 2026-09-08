"""Stage recent Local SQLite analytics into the Supabase active serving tier."""
from __future__ import annotations
import sqlite3
from collections import OrderedDict

TABLE_COLUMNS=OrderedDict([
('analytics_refresh_runs',('analytics_refresh_run_id','pipeline_code','status_code','algorithm_version','window_start','window_end','source_scope_code','input_count','output_count','started_at','completed_at','error_code','metadata_json')),
('keyword_dictionary',('keyword_id','normalized_term','display_term','term_kind','status_code','is_collection_bias','algorithm_version','metadata_json','created_at','updated_at')),
('keyword_observations_daily',('keyword_observation_id','bucket_date','keyword_id','source_scope_code','document_frequency','mention_count','baseline_document_frequency','burst_score','computed_at','window_start','window_end','algorithm_version','source_scope_json','metadata_json')),
('keyword_cooccurrences_daily',('keyword_cooccurrence_id','bucket_date','keyword_left_id','keyword_right_id','source_scope_code','document_frequency','computed_at','window_start','window_end','algorithm_version','metadata_json')),
('insight_signals',('insight_signal_id','signal_type','signal_date','title','summary_text','review_status','severity_code','keyword_id','strength_score','evidence_score','source_diversity_score','confidence_score','algorithm_version','computed_at','window_start','window_end','metadata_json')),
('insight_signal_evidence',('insight_signal_evidence_id','insight_signal_id','target_kind','target_id','evidence_role','source_document_version_id','evidence_rank','evidence_locator','metadata_json','created_at')),
('analytics_model_registry',('model_registry_id','task_code','provider_code','model_name','model_version','embedding_version','prompt_version','prompt_hash','status_code','config_json','created_at','retired_at')),
('analytics_model_runs',('model_run_id','model_registry_id','status_code','input_count','output_count','input_token_count','output_token_count','started_at','completed_at','error_code','metadata_json')),
('insight_interpretations',('interpretation_id','insight_signal_id','model_registry_id','model_run_id','interpretation_status','headline','narrative_text','topic_labels_json','input_hash','output_hash','generated_at','reviewed_at','reviewed_by','metadata_json')),
('insight_interpretation_evidence',('interpretation_evidence_id','interpretation_id','insight_signal_evidence_id','evidence_role','created_at')),
])
PK={name:cols[0] for name,cols in TABLE_COLUMNS.items()}


def _rows(c,sql,args=()): return [tuple(r) for r in c.execute(sql,args).fetchall()]
def _keyword_scope(c:sqlite3.Connection,window_days:int)->tuple[str,str]|None:
 run=c.execute("select window_start,window_end from analytics_refresh_runs where pipeline_code='KEYWORD_DAILY' and status_code='COMPLETED' and window_start is not null and window_end is not null order by completed_at desc,started_at desc limit 1").fetchone()
 if run:
  start=c.execute("select max(date(?),date(?,'-'||?||' days'))",(run[0],run[1],max(1,window_days))).fetchone()[0]
  return start,run[1]
 latest=c.execute("select max(bucket_date) from (select bucket_date from keyword_observations_daily union all select bucket_date from keyword_cooccurrences_daily)").fetchone()[0]
 if not latest:return None
 start,end=c.execute("select date(?,'-'||?||' days'),date(?,'+1 day')",(latest,max(1,window_days)-1,latest)).fetchone()
 return start,end


def build_payload(c:sqlite3.Connection,window_days:int=90)->dict[str,list[tuple]]:
 version=c.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()
 if not version or version[0]!='3.5.0': raise RuntimeError(f"analytics serving sync requires schema 3.5.0, found {version[0] if version else 'missing'}")
 p={};scope=_keyword_scope(c,window_days)
 p['analytics_refresh_runs']=_rows(c,"select "+','.join(TABLE_COLUMNS['analytics_refresh_runs'])+" from analytics_refresh_runs order by started_at,analytics_refresh_run_id")
 p['keyword_observations_daily']=_rows(c,"select "+','.join(TABLE_COLUMNS['keyword_observations_daily'])+" from keyword_observations_daily where bucket_date>=? and bucket_date<? order by bucket_date,keyword_observation_id",scope) if scope else []
 p['keyword_cooccurrences_daily']=_rows(c,"select "+','.join(TABLE_COLUMNS['keyword_cooccurrences_daily'])+" from keyword_cooccurrences_daily where bucket_date>=? and bucket_date<? order by bucket_date,keyword_cooccurrence_id",scope) if scope else []
 p['insight_signals']=_rows(c,"select "+','.join(TABLE_COLUMNS['insight_signals'])+" from insight_signals where review_status<>'SUPERSEDED' order by insight_signal_id")
 superseded_signal_ids=[r[0] for r in c.execute("select insight_signal_id from insight_signals where review_status='SUPERSEDED' order by insight_signal_id")]
 signal_ids={r[0] for r in p['insight_signals']}
 p['insight_signal_evidence']=_rows(c,"select "+','.join(TABLE_COLUMNS['insight_signal_evidence'])+" from insight_signal_evidence order by insight_signal_evidence_id") if signal_ids else []
 if signal_ids: p['insight_signal_evidence']=[r for r in p['insight_signal_evidence'] if r[1] in signal_ids]
 p['analytics_model_registry']=_rows(c,"select "+','.join(TABLE_COLUMNS['analytics_model_registry'])+" from analytics_model_registry order by model_registry_id")
 p['insight_interpretations']=_rows(c,"select "+','.join(TABLE_COLUMNS['insight_interpretations'])+" from insight_interpretations where interpretation_status<>'SUPERSEDED' order by interpretation_id")
 superseded_interpretation_ids=[r[0] for r in c.execute("select interpretation_id from insight_interpretations where interpretation_status='SUPERSEDED' order by interpretation_id")]
 p['insight_interpretations']=[r for r in p['insight_interpretations'] if r[1] in signal_ids]
 interpretation_ids={r[0] for r in p['insight_interpretations']}; run_ids={r[3] for r in p['insight_interpretations'] if r[3]}
 p['analytics_model_runs']=_rows(c,"select "+','.join(TABLE_COLUMNS['analytics_model_runs'])+" from analytics_model_runs order by model_run_id")
 if run_ids:p['analytics_model_runs']=[r for r in p['analytics_model_runs'] if r[0] in run_ids]
 else:p['analytics_model_runs']=[]
 p['insight_interpretation_evidence']=_rows(c,"select "+','.join(TABLE_COLUMNS['insight_interpretation_evidence'])+" from insight_interpretation_evidence order by interpretation_evidence_id")
 signal_evidence_ids={r[0] for r in p['insight_signal_evidence']}
 if interpretation_ids:p['insight_interpretation_evidence']=[r for r in p['insight_interpretation_evidence'] if r[1] in interpretation_ids and r[2] in signal_evidence_ids]
 else:p['insight_interpretation_evidence']=[]
 keyword_ids={r[2] for r in p['keyword_observations_daily']}|{x for r in p['keyword_cooccurrences_daily'] for x in (r[2],r[3])}|{r[7] for r in p['insight_signals'] if r[7]}
 all_dictionary=_rows(c,"select "+','.join(TABLE_COLUMNS['keyword_dictionary'])+" from keyword_dictionary order by keyword_id")
 p['keyword_dictionary']=[r for r in all_dictionary if r[0] in keyword_ids]
 result={name:p.get(name,[]) for name in TABLE_COLUMNS}
 result['_sync_scope']={'superseded_signal_ids':superseded_signal_ids,'superseded_interpretation_ids':superseded_interpretation_ids}
 if scope:result['_sync_scope'].update({'keyword_start':scope[0],'keyword_end':scope[1]})
 return result


def upsert_sql(table:str)->str:
 cols=TABLE_COLUMNS[table];pk=PK[table];names=','.join(cols);updates=[]
 terminal="('APPROVED','REJECTED','SUPERSEDED')"
 for col in cols[1:]:
  if table=='insight_signals' and col=='review_status':
   updates.append(f"{col}=CASE WHEN target.review_status IN {terminal} THEN target.{col} ELSE EXCLUDED.{col} END")
  elif table=='insight_interpretations' and col in ('interpretation_status','reviewed_at','reviewed_by'):
   updates.append(f"{col}=CASE WHEN target.interpretation_status IN {terminal} THEN target.{col} ELSE EXCLUDED.{col} END")
  else: updates.append(f"{col}=EXCLUDED.{col}")
 temp=f'_sync_{table}'
 if table=='insight_signal_evidence':
  expressions=[f't.{c}' for c in cols];i=cols.index('source_document_version_id');expressions[i]='dv.document_version_id'
  select='SELECT '+','.join(expressions)+f' FROM {temp} t LEFT JOIN market_intelligence.document_versions dv ON dv.document_version_id=t.source_document_version_id'
 else: select=f'SELECT {names} FROM {temp}'
 return f"INSERT INTO market_intelligence.{table} AS target ({names}) {select} ON CONFLICT ({pk}) DO UPDATE SET "+','.join(updates)


def reconcile_sql(table:str)->str:
 if table in ('keyword_observations_daily','keyword_cooccurrences_daily'):
  pk=PK[table]
  return f"DELETE FROM market_intelligence.{table} AS target WHERE target.bucket_date >= %s AND target.bucket_date < %s AND NOT EXISTS (SELECT 1 FROM _sync_{table} staged WHERE staged.{pk}=target.{pk})"
 if table=='insight_signals':
  return "UPDATE market_intelligence.insight_signals AS target SET review_status='SUPERSEDED' WHERE target.review_status='UNREVIEWED' AND target.insight_signal_id = ANY(%s)"
 if table=='insight_interpretations':
  return "UPDATE market_intelligence.insight_interpretations AS target SET interpretation_status='SUPERSEDED' WHERE target.interpretation_status IN ('DRAFT','IN_REVIEW') AND target.interpretation_id = ANY(%s)"
 raise ValueError(f'no reconciliation rule for {table}')


def sync_payload(conn,payload:dict[str,list[tuple]])->dict:
 counts={};scope=payload.get('_sync_scope',{})
 with conn.cursor() as cur:
  for table,cols in TABLE_COLUMNS.items():
   rows=payload.get(table,[]);counts[table]=len(rows)
   temp=f'_sync_{table}'
   cur.execute(f"CREATE TEMP TABLE {temp} (LIKE market_intelligence.{table} INCLUDING DEFAULTS) ON COMMIT DROP")
   if rows:
    with cur.copy(f"COPY {temp} ({','.join(cols)}) FROM STDIN") as copy:
     for row in rows: copy.write_row(row)
    cur.execute(upsert_sql(table))
  if scope.get('keyword_start') and scope.get('keyword_end'):
   for table in ('keyword_cooccurrences_daily','keyword_observations_daily'):
    cur.execute(reconcile_sql(table),(scope['keyword_start'],scope['keyword_end']))
  if scope.get('superseded_interpretation_ids'):cur.execute(reconcile_sql('insight_interpretations'),(scope['superseded_interpretation_ids'],))
  if scope.get('superseded_signal_ids'):cur.execute(reconcile_sql('insight_signals'),(scope['superseded_signal_ids'],))
 return counts
