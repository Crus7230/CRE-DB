from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/"data/market.db"


def sha(path:Path)->str:
    h=hashlib.sha256();
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def main()->None:
    con=sqlite3.connect(DB)
    tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    views={r[0] for r in con.execute("select name from sqlite_master where type='view'")}
    required_tables={"sale_processes","sale_process_roles","bid_rounds","bidder_participations","bidder_participation_members","bid_submissions","bid_funding_components","bid_decisions","transaction_milestones"}
    required_views={"v_bid_competition","v_bid_funding","v_sale_process_current"}
    campaign=con.execute("select count(*),sum(case when status_code='COMPLETED' then 1 else 0 end),sum(discovered_count) from collection_runs where runner_version='2025-bid-process-v1'").fetchone()
    rss_active=con.execute("""select count(*) from review_tasks rt join event_mentions em on em.event_mention_id=rt.target_id join extraction_runs er on er.extraction_run_id=em.extraction_run_id where rt.review_type='SALE_PROCESS_EVIDENCE_REVIEW' and rt.status_code='PENDING' and er.pipeline_version='BID_PROCESS_TITLE_SNIPPET_V3'""").fetchone()[0]
    rss_superseded=con.execute("""select count(*) from review_tasks rt join event_mentions em on em.event_mention_id=rt.target_id join extraction_runs er on er.extraction_run_id=em.extraction_run_id where rt.review_type='SALE_PROCESS_EVIDENCE_REVIEW' and rt.status_code='REJECTED' and er.pipeline_version in ('BID_PROCESS_TITLE_SNIPPET_V1','BID_PROCESS_TITLE_SNIPPET_V2')""").fetchone()[0]
    dart_latest=con.execute("""select count(*) from source_documents d join collection_sources s on s.source_id=d.source_id join document_versions v on v.document_id=d.document_id where s.source_code='OPENDART' and v.published_at>='2025-01-01' and v.published_at<'2026-01-01' and v.version_no=(select max(v2.version_no) from document_versions v2 where v2.document_id=d.document_id)""").fetchone()[0]
    dart_type=con.execute("""select count(*) from source_documents d join collection_sources s on s.source_id=d.source_id join document_versions v on v.document_id=d.document_id where s.source_code='OPENDART' and v.published_at>='2025-01-01' and v.published_at<'2026-01-01' and v.version_no=(select max(v2.version_no) from document_versions v2 where v2.document_id=d.document_id) and (v.title like '%유형자산양도%' or v.title like '%유형자산양수%')""").fetchone()[0]
    dart_full=con.execute("""select count(*) from source_documents d join collection_sources s on s.source_id=d.source_id join document_versions v on v.document_id=d.document_id where s.source_code='OPENDART' and v.published_at>='2025-01-01' and v.published_at<'2026-01-01' and v.version_no=(select max(v2.version_no) from document_versions v2 where v2.document_id=d.document_id) and (v.title like '%유형자산양도%' or v.title like '%유형자산양수%') and v.stored_text is not null""").fetchone()[0]
    dart_active=con.execute("""select count(*) from review_tasks rt join event_mentions em on em.event_mention_id=rt.target_id join extraction_runs er on er.extraction_run_id=em.extraction_run_id where rt.review_type='OFFICIAL_SALE_DISCLOSURE_REVIEW' and rt.status_code='PENDING' and er.pipeline_version='DART_TYPE_ASSET_SALE_RULE_V2'""").fetchone()[0]
    span_errors=con.execute("""select count(*) from mentions m join extraction_runs er on er.extraction_run_id=m.extraction_run_id join document_versions v on v.document_version_id=er.document_version_id where er.pipeline_version='DART_TYPE_ASSET_SALE_RULE_V2' and (m.char_end>length(v.stored_text) or substr(v.stored_text,m.char_start+1,m.char_end-m.char_start)<>m.surface_text)""").fetchone()[0]
    integrity=con.execute('pragma integrity_check').fetchone()[0]
    fk=len(con.execute('pragma foreign_key_check').fetchall())
    version=con.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()[0]
    canonical=con.execute('select count(*) from sale_processes').fetchone()[0]
    con.close()
    office_json=json.loads((ROOT/'artifacts/bid-process-2025-deep-dive.json').read_text(encoding='utf-8'))
    logistics_json=json.loads((ROOT/'artifacts/logistics-competitive-sales-2025-structured.json').read_text(encoding='utf-8'))
    hotel_md=(ROOT/'artifacts/hotel-competitive-sales-2025-deep-dive.md').read_text(encoding='utf-8')
    synthesis=(ROOT/'artifacts/competitive-sales-2025-expanded-synthesis.md').read_text(encoding='utf-8')
    office_urls=[s.get('url') for case in office_json['cases'] for s in case.get('sources',[])]
    logistics_urls=[s.get('url') for case in logistics_json['processes'] for s in case.get('sources',[])]
    hotel_case_count=len(re.findall(r'^### [A-J]\.',hotel_md,re.M))
    checks={
        'schemaVersion23':version=='2.3.0','requiredTables':not(required_tables-tables),'requiredViews':not(required_views-views),
        'integrity':integrity=='ok','foreignKeys':fk==0,'campaignPartitions':campaign[0]==684 and campaign[1]==684,
        'activeRssCandidates':rss_active==51,'supersededRssLineage':rss_superseded==106,
        'dartListCoverage':dart_latest==303 and dart_type==237,'dartFullTextCoverage':dart_full==228,
        'dartUnavailableFiles':dart_type-dart_full==9,'activeDartCandidates':dart_active==159,
        'evidenceSpanOffsets':span_errors==0,'noAutoCanonicalPromotion':canonical==0,
        'officeDeepDive':len(office_json['cases'])==8 and all(u and u.startswith('http') for u in office_urls),
        'logisticsDeepDive':len(logistics_json['processes'])==8 and all(u and u.startswith('http') for u in logistics_urls),
        'hotelDeepDive':hotel_case_count==10 and len(re.findall(r'https?://',hotel_md))>=30,
        'synthesisStatusDiscipline':all(x in synthesis for x in ['우협 보도만 있는 TCC동양타워','SPA만 확인된 SI타워','미발견','무검수 canonical sale process 자동 생성: **0건**']),
    }
    artifact_paths=[ROOT/'artifacts/bid-process-2025-candidates.json',ROOT/'artifacts/opendart-2025-type-asset-sale-candidates.json',ROOT/'artifacts/sale-process-model-v1.md',ROOT/'artifacts/backfill-2025-bid-process-summary.json',ROOT/'artifacts/bid-process-2025-deep-dive.md',ROOT/'artifacts/bid-process-2025-deep-dive.json',ROOT/'artifacts/hotel-competitive-sales-2025-deep-dive.md',ROOT/'artifacts/logistics-competitive-sales-2025-deep-dive.md',ROOT/'artifacts/logistics-competitive-sales-2025-structured.json',ROOT/'artifacts/competitive-sales-2025-expanded-synthesis.md']
    out={'generatedAt':datetime.now(timezone.utc).isoformat(),'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'metrics':{'schemaVersion':version,'campaignPartitions':campaign[0],'campaignCompleted':campaign[1],'campaignDiscovered':campaign[2],'activeRssCandidates':rss_active,'supersededRssCandidates':rss_superseded,'dartLatestDocuments':dart_latest,'dartTypeAssetFilings':dart_type,'dartFullTextDocuments':dart_full,'dartUnavailableStatus014':dart_type-dart_full,'activeDartCandidates':dart_active,'spanErrors':span_errors,'canonicalSaleProcesses':canonical},'artifactSha256':{str(p.relative_to(ROOT)):sha(p) for p in artifact_paths}}
    path=ROOT/'artifacts/capital-commercial-market-2025-bid-process-qa.json'; path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2))
    if out['status']!='PASS': raise SystemExit(1)

if __name__=='__main__': main()
