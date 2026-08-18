from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import html,io,json
from pathlib import Path
import re,sqlite3,sys,time
import urllib.parse,urllib.request
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from collector.backfill_2025 import DiscoveredDocument,ingest_partition

class NonZipResponse(RuntimeError): pass

def job_code(year:int,report_kind:str='TYPE_ASSET')->str:
    return (f'BACKFILL_{year}_OPENDART_SALE_DOCUMENT_TEXT_V3' if report_kind=='TYPE_ASSET'
            else f'BACKFILL_{year}_OPENDART_BUSINESS_TRANSFER_TEXT_V1')
def runner_version(year:int,report_kind:str='TYPE_ASSET')->str:
    return (f'backfill-{year}-dart-document-text-v3' if report_kind=='TYPE_ASSET'
            else f'backfill-{year}-dart-business-transfer-text-v1')

def load_key(path:Path)->str:
    values={}
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        s=raw.strip()
        if s and not s.startswith('#') and '=' in s:
            k,v=s.split('=',1); values[k.strip()]=v.strip().strip('"').strip("'")
    if not values.get('DART_API_KEY'): raise SystemExit('DART_API_KEY is not configured')
    return values['DART_API_KEY']

def parse_api_error(payload:bytes)->tuple[str,str]:
    try: root=ET.fromstring(payload)
    except ET.ParseError as exc: raise NonZipResponse('OpenDART non-ZIP/non-XML response') from exc
    return root.findtext('status') or 'UNKNOWN',root.findtext('message') or 'OpenDART document error'

def decode_xml(data:bytes)->str:
    for enc in ('utf-8','cp949','euc-kr'):
        try:return data.decode(enc)
        except UnicodeDecodeError:pass
    return data.decode('utf-8',errors='replace')

def clean_xml(text:str)->str:
    text=re.sub(r'<script\b[^>]*>.*?</script>',' ',text,flags=re.I|re.S); text=re.sub(r'<style\b[^>]*>.*?</style>',' ',text,flags=re.I|re.S)
    return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',text))).strip()

def fetch_document(task:dict,key:str)->dict:
    error=None
    for attempt in range(1,4):
        try:
            url='https://opendart.fss.or.kr/api/document.xml?'+urllib.parse.urlencode({'crtfc_key':key,'rcept_no':task['receipt_no']})
            payload=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Hermes CRE official filing research'}),timeout=45).read()
            if not payload.startswith(b'PK'):
                status,message=parse_api_error(payload)
                if status=='014': return {**task,'status':'UNAVAILABLE_014','error':f'OpenDARTStatus014: {message}'}
                raise RuntimeError(f'OpenDARTStatus{status}: {message}')
            with zipfile.ZipFile(io.BytesIO(payload)) as z:
                names=sorted(z.namelist()); sections=[clean_xml(decode_xml(z.read(name))) for name in names]
            stored='\n\n'.join(x for x in sections if x)
            if not stored: raise ValueError('empty filing text')
            metadata=dict(task['metadata']); metadata.update({'document_api':'OpenDART document.xml','document_file_count':len(names),'full_text_collected_at':datetime.now(timezone.utc).isoformat()})
            doc=DiscoveredDocument(canonical_url=task['canonical_url'],external_key=task['receipt_no'],title=task['title'],publisher_name=metadata.get('filer_name'),published_at=task['published_at'],snippet_text=task['snippet_text'],document_type='OFFICIAL_FILING',rights_status='FULL_STORAGE_ALLOWED',stored_text=stored,metadata=metadata)
            return {**task,'status':'OK','document':doc,'text_bytes':len(stored.encode('utf-8'))}
        except Exception as exc:
            error=f'{type(exc).__name__}: {exc}'
            if attempt<3:time.sleep(2**(attempt-1))
    return {**task,'status':'FAILED_RETRYABLE','error':error}

def select_tasks(db:Path,start_year:int,end_year:int,report_kind:str='TYPE_ASSET')->list[dict]:
    con=sqlite3.connect(db)
    title_filter=("(v.title like '%유형자산양도%' or v.title like '%유형자산양수%')" if report_kind=='TYPE_ASSET'
                  else "(v.title like '%영업양도%' or v.title like '%영업양수%')")
    rows=con.execute("""select d.external_document_key,d.canonical_url,v.title,v.published_at,v.snippet_text,v.metadata_json
      from source_documents d join collection_sources s on s.source_id=d.source_id join document_versions v on v.document_id=d.document_id
      where s.source_code='OPENDART' and v.published_at>=? and v.published_at<?
        and """+title_filter+"""
        and v.version_no=(select max(v2.version_no) from document_versions v2 where v2.document_id=d.document_id)
        and v.stored_text is null order by v.published_at,d.external_document_key""",(f'{start_year}-01-01',f'{end_year+1}-01-01')).fetchall();con.close()
    return [{'receipt_no':r[0],'canonical_url':r[1],'title':r[2],'published_at':r[3],'snippet_text':r[4],'metadata':json.loads(r[5] or '{}'),'month':r[3][:7]} for r in rows]

def month_bounds(month:str)->tuple[str,str,int]:
    y,m=map(int,month.split('-')); ny,nm=(y+1,1) if m==12 else (y,m+1)
    return f'{y:04d}-{m:02d}-01T00:00:00Z',f'{ny:04d}-{nm:02d}-01T00:00:00Z',y

def main()->None:
    p=argparse.ArgumentParser(description='Historical OpenDART sale full-text enrichment')
    p.add_argument('--db',default='data/market.db');p.add_argument('--env',default='C:/10137_WorkSpace/env/.env');p.add_argument('--start-year',type=int,required=True);p.add_argument('--end-year',type=int,required=True);p.add_argument('--workers',type=int,default=6);p.add_argument('--dry-run',action='store_true');p.add_argument('--report-kind',choices=('TYPE_ASSET','BUSINESS_TRANSFER'),default='TYPE_ASSET')
    a=p.parse_args(); db=(ROOT/a.db).resolve() if not Path(a.db).is_absolute() else Path(a.db)
    tasks=select_tasks(db,a.start_year,a.end_year,a.report_kind)
    if a.dry_run:
        print(json.dumps({'reportKind':a.report_kind,'attempted':len(tasks),'byYear':{str(y):sum(t['published_at'].startswith(str(y)) for t in tasks) for y in range(a.start_year,a.end_year+1)}},ensure_ascii=False));return
    key=load_key(Path(a.env));results=[]
    with ThreadPoolExecutor(max_workers=max(1,a.workers)) as pool:
        futures=[pool.submit(fetch_document,t,key) for t in tasks]
        for future in as_completed(futures):
            r=future.result();results.append(r);print(json.dumps({'receipt_no':r['receipt_no'],'status':r['status'],'text_bytes':r.get('text_bytes'),'error':r.get('error')},ensure_ascii=False),flush=True)
    months=sorted({t['month'] for t in tasks}); ingested=[]
    for month in months:
        month_results=[r for r in results if r['month']==month]; retryable=[r for r in month_results if r['status']=='FAILED_RETRYABLE']
        if retryable:
            ingested.append({'month':month,'status':'FAILED_RETRYABLE_NOT_COMMITTED','documents':sum(r['status']=='OK' for r in month_results),'retryableFailures':len(retryable)});continue
        docs=[r['document'] for r in month_results if r['status']=='OK'];start,end,year=month_bounds(month)
        result=ingest_partition(db_path=db,source_code='OPENDART',job_code=job_code(year,a.report_kind),category_code='SALE',window_start=start,window_end=end,query_rendered=f'OpenDART document.xml full text for {year} {a.report_kind} filings',documents=docs,runner_version=runner_version(year,a.report_kind))
        ingested.append({'month':month,'status':'COMPLETED','documents':len(docs),'unavailable014':sum(r['status']=='UNAVAILABLE_014' for r in month_results),'inserted':result.inserted_count,'updated':result.updated_count})
    summary={'reportKind':a.report_kind,'startYear':a.start_year,'endYear':a.end_year,'attempted':len(tasks),'downloaded':sum(r['status']=='OK' for r in results),'unavailable014':sum(r['status']=='UNAVAILABLE_014' for r in results),'retryableFailures':sum(r['status']=='FAILED_RETRYABLE' for r in results),'textBytes':sum(r.get('text_bytes',0) for r in results),'ingestedByMonth':ingested,'failures':[{'receiptNo':r['receipt_no'],'status':r['status'],'error':r.get('error')} for r in results if r['status']!='OK']}
    suffix='sale-document-text-v3' if a.report_kind=='TYPE_ASSET' else 'business-transfer-document-text-v1'
    out=ROOT/'artifacts'/f'backfill-{a.start_year}-{a.end_year}-opendart-{suffix}-summary.json';out.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:summary[k] for k in ('reportKind','attempted','downloaded','unavailable014','retryableFailures','textBytes')},ensure_ascii=False))

if __name__=='__main__':main()
