from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from collector.backfill_2025 import ingest_partition, month_windows, parse_dart_filings

KEYWORDS=(
    '유형자산양도','유형자산양수','유형자산취득',
    '유형자산 양도','유형자산 양수','유형자산 취득',
    '영업양도','영업양수',
)


def campaign_windows(start_year:int,end_year:int)->list[tuple[int,str,str]]:
    if start_year>end_year: raise ValueError('start_year must be <= end_year')
    return [(year,start,end) for year in range(start_year,end_year+1) for start,end in month_windows(year)]


def job_code(year:int)->str: return f'BACKFILL_{year}_OPENDART_SALE_V3'
def runner_version(year:int)->str: return f'backfill-{year}-dart-sale-v3'


def items_from_payload(payload:dict)->list[dict]:
    status=payload.get('status')
    if status=='013': return []
    if status!='000': raise RuntimeError(f"OpenDART status={status} message={payload.get('message')}")
    return payload.get('list',[])


def load_key(path:Path)->str:
    values={}
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line=raw.strip()
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1); values[k.strip()]=v.strip().strip('"').strip("'")
    if not values.get('DART_API_KEY'): raise SystemExit('DART_API_KEY is not configured')
    return values['DART_API_KEY']


def completed(db:Path,code:str,scheduled:str,query:str)->bool:
    con=sqlite3.connect(db,timeout=5); con.execute('PRAGMA busy_timeout=5000')
    try:
        return con.execute("""select 1 from collection_runs cr join collection_jobs j on j.job_id=cr.job_id
          where j.job_code=? and cr.scheduled_for=? and cr.query_rendered=? and cr.status_code='COMPLETED' limit 1""",
          (code,scheduled,query)).fetchone() is not None
    finally: con.close()


def fetch_month(api_key:str,start_date:str,end_date:str,sleep_seconds:float)->tuple[list[dict],int]:
    inclusive_end=date.fromisoformat(end_date)-timedelta(days=1)
    common={'crtfc_key':api_key,'bgn_de':start_date.replace('-',''),'end_de':inclusive_end.isoformat().replace('-',''),'pblntf_ty':'B','page_count':'100'}
    all_items=[]; page=1; total_pages=1; total_count=0
    while page<=total_pages:
        url='https://opendart.fss.or.kr/api/list.json?'+urllib.parse.urlencode(dict(common,page_no=str(page)))
        payload=json.loads(urllib.request.urlopen(url,timeout=45).read().decode('utf-8'))
        items=items_from_payload(payload)
        if payload.get('status')=='013': return [],0
        if page==1:
            total_count=int(payload.get('total_count',0)); total_pages=max(1,math.ceil(total_count/100))
        all_items.extend(items); page+=1
        if sleep_seconds: time.sleep(sleep_seconds)
    if len(all_items)!=total_count:
        raise RuntimeError(f'OpenDART total_count mismatch: expected={total_count} parsed={len(all_items)}')
    return all_items,total_count


def main()->None:
    p=argparse.ArgumentParser(description='Resumable historical OpenDART sale disclosure backfill')
    p.add_argument('--db',default='data/market.db'); p.add_argument('--env',default='C:/10137_WorkSpace/env/.env')
    p.add_argument('--start-year',type=int,required=True); p.add_argument('--end-year',type=int,required=True)
    p.add_argument('--year',type=int,action='append'); p.add_argument('--month',type=int); p.add_argument('--sleep',type=float,default=.25)
    p.add_argument('--dry-run',action='store_true'); p.add_argument('--force',action='store_true')
    args=p.parse_args()
    db=(ROOT/args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db)
    windows=campaign_windows(args.start_year,args.end_year)
    if args.year: windows=[w for w in windows if w[0] in set(args.year)]
    if args.month is not None:
        if not 1<=args.month<=12: raise SystemExit('--month must be between 1 and 12')
        windows=[w for w in windows if int(w[1][5:7])==args.month]
    query='OpenDART list pblntf_ty=B; report keywords: '+','.join(KEYWORDS)
    tasks=[]
    for year,start,end in windows:
        scheduled=f'{start}T00:00:00Z'
        tasks.append({'year':year,'start':start,'end':end,'jobCode':job_code(year),'scheduled':scheduled,
                      'skip':False if args.force else completed(db,job_code(year),scheduled,query)})
    if args.dry_run:
        print(json.dumps({'startYear':args.start_year,'endYear':args.end_year,'partitions':len(tasks),'alreadyCompleted':sum(t['skip'] for t in tasks),'byYear':{str(y):sum(t['year']==y for t in tasks) for y in sorted({t['year'] for t in tasks})}},ensure_ascii=False)); return
    key=load_key(Path(args.env)); summary=[]
    for t in tasks:
        if t['skip']:
            row={**t,'status':'SKIPPED_EXISTING','apiRecords':0,'filteredDocuments':0,'inserted':0,'updated':0}; summary.append(row); print(json.dumps(row,ensure_ascii=False),flush=True); continue
        all_items,total_count=fetch_month(key,t['start'],t['end'],args.sleep)
        start_dt=datetime.fromisoformat(t['start']).replace(tzinfo=timezone.utc); end_dt=datetime.fromisoformat(t['end']).replace(tzinfo=timezone.utc)
        documents=parse_dart_filings({'status':'000','list':all_items},start=start_dt,end=end_dt,report_keywords=KEYWORDS)
        result=ingest_partition(db_path=db,source_code='OPENDART',job_code=t['jobCode'],category_code='SALE',window_start=t['scheduled'],window_end=f"{t['end']}T00:00:00Z",query_rendered=query,documents=documents,runner_version=runner_version(t['year']))
        row={**t,'status':'COMPLETED','apiRecords':total_count,'filteredDocuments':len(documents),'inserted':result.inserted_count,'updated':result.updated_count,'runId':result.run_id}; summary.append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
    payload={'campaign':'BACKFILL_HISTORICAL_OPENDART_SALE_V3','startYear':args.start_year,'endYear':args.end_year,'generatedAt':datetime.now(timezone.utc).isoformat(),'partitions':summary,
             'totals':{'partitions':len(summary),'completed':sum(r['status']=='COMPLETED' for r in summary),'skipped':sum(r['status']=='SKIPPED_EXISTING' for r in summary),'apiRecords':sum(r['apiRecords'] for r in summary),'filteredDocuments':sum(r['filteredDocuments'] for r in summary),'inserted':sum(r['inserted'] for r in summary),'updated':sum(r['updated'] for r in summary)}}
    out=ROOT/'artifacts'/f"backfill-{args.start_year}-{args.end_year}-opendart-sale-v3-summary.json"; out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(payload['totals'],ensure_ascii=False))

if __name__=='__main__': main()
