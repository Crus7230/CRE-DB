"""Provider-neutral, versioned export/import boundary for model-derived signal interpretations."""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import Iterable

JOB_VERSION="MODEL_TOPIC_JOB_V1"

def now() -> str: return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
def digest(value: object) -> str: return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def stable_id(prefix: str,*parts: str) -> str: return f"{prefix}-{hashlib.sha256('|'.join(parts).encode()).hexdigest()[:32]}"

def _model(conn: sqlite3.Connection, registry_id: str) -> sqlite3.Row:
    row=conn.execute("select * from analytics_model_registry where model_registry_id=? and status_code='ENABLED' and task_code='TOPIC_INTERPRETATION'",(registry_id,)).fetchone()
    if not row: raise ValueError("enabled TOPIC_INTERPRETATION model registry entry not found")
    return row

def export_jobs(conn: sqlite3.Connection, registry_id: str, limit: int=50) -> list[dict]:
    previous=conn.row_factory; conn.row_factory=sqlite3.Row
    try:
        model=_model(conn,registry_id); signals=conn.execute("""select insight_signal_id,signal_type,signal_date,title,summary_text,review_status,severity_code,confidence_score,algorithm_version
          from insight_signals where review_status in ('UNREVIEWED','PENDING','APPROVED') order by signal_date desc,confidence_score desc,insight_signal_id limit ?""",(max(1,min(200,int(limit))),)).fetchall()
        jobs=[]
        for signal in signals:
            evidence=[]
            for item in conn.execute("select * from insight_signal_evidence where insight_signal_id=? order by evidence_rank,insight_signal_evidence_id",(signal['insight_signal_id'],)):
                meta=json.loads(item['metadata_json'] or '{}')
                evidence.append({'signalEvidenceId':item['insight_signal_evidence_id'],'documentId':item['target_id'],'role':item['evidence_role'],'rank':item['evidence_rank'],'title':item['evidence_locator'] or '', 'sourceName':meta.get('source_name',''),'publishedAt':meta.get('published_at'),'canonicalUrl':meta.get('canonical_url')})
            payload={'jobVersion':JOB_VERSION,'signal':{'signalId':signal['insight_signal_id'],'type':signal['signal_type'],'date':signal['signal_date'],'title':signal['title'],'summary':signal['summary_text'],'reviewStatus':signal['review_status'],'severity':signal['severity_code'],'confidence':signal['confidence_score'],'algorithmVersion':signal['algorithm_version']},'evidence':evidence,'modelProvenance':{'modelVersion':model['model_version'],'embeddingVersion':model['embedding_version'],'promptVersion':model['prompt_version'],'promptHash':model['prompt_hash']}}
            jobs.append({**payload,'inputHash':digest(payload)})
        return jobs
    finally: conn.row_factory=previous

def import_outputs(conn: sqlite3.Connection, registry_id: str, outputs: Iterable[dict], *, apply: bool=False, commit: bool=True) -> dict:
    previous=conn.row_factory; conn.row_factory=sqlite3.Row
    try:
        _model(conn,registry_id); jobs={job['signal']['signalId']:job for job in export_jobs(conn,registry_id,200)}; validated=[]
        for output in outputs:
            signal_id=str(output.get('signalId','')); job=jobs.get(signal_id)
            if not job or output.get('inputHash') != job['inputHash']: raise ValueError("model output input hash does not match current grounded job")
            headline=str(output.get('headline','')).strip(); narrative=str(output.get('narrative','')).strip(); labels=output.get('topicLabels',[])
            if not headline or not narrative or not isinstance(labels,list) or not all(isinstance(x,str) for x in labels): raise ValueError("invalid model output contract")
            content={'headline':headline,'narrative':narrative,'topicLabels':labels}; output_hash=digest(content)
            validated.append((job,content,output_hash))
        evidence_count=sum(len(job['evidence']) for job,_,_ in validated)
        if not apply: return {'applied':False,'interpretationsPlanned':len(validated),'evidencePlanned':evidence_count}
        run_id=f"model-run-{uuid.uuid4().hex}"; timestamp=now(); conn.execute("SAVEPOINT model_import")
        try:
            conn.execute("insert into analytics_model_runs(model_run_id,model_registry_id,status_code,input_count,output_count,started_at,completed_at,metadata_json) values(?,?,?,?,?,?,?,?)",(run_id,registry_id,'COMPLETED',len(validated),0,timestamp,timestamp,json.dumps({'jobVersion':JOB_VERSION})))
            written=0; linked=0
            for job,content,output_hash in validated:
                signal_id=job['signal']['signalId']; interpretation_id=stable_id('interpretation',signal_id,registry_id,job['inputHash'],output_hash)
                cursor=conn.execute("""insert or ignore into insight_interpretations(
                  interpretation_id,insight_signal_id,model_registry_id,model_run_id,headline,narrative_text,topic_labels_json,input_hash,output_hash,generated_at,metadata_json
                  ) values(?,?,?,?,?,?,?,?,?,?,?)""",(interpretation_id,signal_id,registry_id,run_id,content['headline'],content['narrative'],json.dumps(content['topicLabels'],ensure_ascii=False),job['inputHash'],output_hash,timestamp,json.dumps({'jobVersion':JOB_VERSION})))
                written+=max(cursor.rowcount,0)
                for item in job['evidence']:
                    evidence_id=stable_id('interpretation-evidence',interpretation_id,item['signalEvidenceId'],'GROUNDING')
                    linked+=max(conn.execute("insert or ignore into insight_interpretation_evidence values(?,?,?,?,?)",(evidence_id,interpretation_id,item['signalEvidenceId'],'GROUNDING',timestamp)).rowcount,0)
            conn.execute("update analytics_model_runs set output_count=? where model_run_id=?",(written,run_id)); conn.execute("RELEASE model_import")
            if commit: conn.commit()
        except Exception:
            conn.execute("ROLLBACK TO model_import"); conn.execute("RELEASE model_import"); raise
        return {'applied':True,'modelRunId':run_id,'interpretationsWritten':written,'evidenceWritten':linked}
    finally: conn.row_factory=previous

def main() -> None:
    root=Path(__file__).parents[1]; parser=argparse.ArgumentParser(); parser.add_argument('action',choices=('export','import')); parser.add_argument('--db',type=Path,default=root/'data/market.db'); parser.add_argument('--registry-id',required=True); parser.add_argument('--file',type=Path); parser.add_argument('--apply',action='store_true'); args=parser.parse_args()
    conn=sqlite3.connect(args.db); conn.row_factory=sqlite3.Row; conn.execute('pragma foreign_keys=on')
    try:
        version=conn.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()
        if not version or version[0]!='3.5.0': raise SystemExit("model boundary requires schema 3.5.0")
        if args.action=='export':
            jobs=export_jobs(conn,args.registry_id); text='\n'.join(json.dumps(x,ensure_ascii=False) for x in jobs)
            if args.file: args.file.write_text(text+('\n' if text else ''),encoding='utf-8')
            else: print(text)
        else:
            if not args.file: raise SystemExit('--file is required for import')
            outputs=[json.loads(line) for line in args.file.read_text(encoding='utf-8').splitlines() if line.strip()]
            print(json.dumps(import_outputs(conn,args.registry_id,outputs,apply=args.apply),ensure_ascii=False,indent=2))
    finally: conn.close()

if __name__=='__main__': main()
