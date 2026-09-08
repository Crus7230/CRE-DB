#!/usr/bin/env python
from pathlib import Path
import json,psycopg

ENV=Path(r'C:\10137_WorkSpace\env\.env.supabase.local')
def env():
 out={}
 for raw in ENV.read_text(encoding='utf-8-sig').splitlines():
  s=raw.strip()
  if s and not s.startswith('#') and '=' in s:
   k,v=s.split('=',1);out[k.strip()]=v.strip().strip('"').strip("'")
 return out

def main():
 e=env();s=e.get('SUPABASE_DB_SCHEMA','market_intelligence');q={
 'cutoff_partitions':f"SELECT count(*)::int FROM {s}.collection_runs WHERE scheduled_for LIKE '2026-08-19%' AND status_code='COMPLETED'",
 'research_record_count':f"SELECT count(DISTINCT extraction_key)::int FROM {s}.event_mentions em JOIN {s}.extraction_runs er USING(extraction_run_id) WHERE er.pipeline_version='cutoff-research-ledger-20260819-v1'",
 'research_url_count':f"SELECT count(DISTINCT d.canonical_url)::int FROM {s}.source_documents d WHERE d.source_id='src_cutoff_research_20260819'",
 'research_mentions_by_category':f"SELECT event_category_id,count(*)::int FROM {s}.event_mentions em JOIN {s}.extraction_runs er USING(extraction_run_id) WHERE er.pipeline_version='cutoff-research-ledger-20260819-v1' GROUP BY 1 ORDER BY 1",
 'official_mandates':f"SELECT count(*)::int FROM {s}.lp_mandates WHERE (metadata_json::jsonb->>'manifest_id') LIKE 'approved-lpmandate-%2026%' OR mandate_id IN ('mandate-khug-future-city-fund-1')",
 'new_mandates':f"SELECT mandate_code,mandate_status,announced_at,application_deadline,selected_at FROM {s}.lp_mandates WHERE mandate_id IN ('mandate-koreapost-2026-domestic-reit','mandate-koreapost-insurance-2026-domestic-multistrategy','mandate-nps-2026-domestic-real-estate','mandate-cw-2026-domestic-senior-loan','mandate-kbiz-2026-domestic-equity-blind','mandate-poba-2026-public-golf','mandate-khug-future-city-fund-1') ORDER BY mandate_code",
 'new_tracks':f"SELECT count(*)::int FROM {s}.lp_mandate_tracks WHERE mandate_id IN ('mandate-koreapost-2026-domestic-reit','mandate-koreapost-insurance-2026-domestic-multistrategy','mandate-nps-2026-domestic-real-estate','mandate-cw-2026-domestic-senior-loan','mandate-kbiz-2026-domestic-equity-blind','mandate-poba-2026-public-golf','mandate-khug-future-city-fund-1')",
 'new_amounts':f"SELECT amount_basis,count(*)::int FROM {s}.lp_mandate_amounts WHERE mandate_track_id IN (SELECT mandate_track_id FROM {s}.lp_mandate_tracks WHERE mandate_id IN ('mandate-koreapost-2026-domestic-reit','mandate-koreapost-insurance-2026-domestic-multistrategy','mandate-nps-2026-domestic-real-estate','mandate-cw-2026-domestic-senior-loan','mandate-kbiz-2026-domestic-equity-blind','mandate-poba-2026-public-golf','mandate-khug-future-city-fund-1')) GROUP BY 1 ORDER BY 1",
 'new_selections':f"SELECT ms.selection_status,o.canonical_name,ms.selected_at FROM {s}.lp_mandate_selections ms JOIN {s}.organizations o ON o.organization_id=ms.manager_organization_id WHERE ms.mandate_track_id IN (SELECT mandate_track_id FROM {s}.lp_mandate_tracks WHERE mandate_id='mandate-khug-future-city-fund-1')",
 'orphan_tracks':f"SELECT count(*)::int FROM {s}.lp_mandate_tracks t LEFT JOIN {s}.lp_mandates m USING(mandate_id) WHERE m.mandate_id IS NULL",
 'orphan_guidelines':f"SELECT count(*)::int FROM {s}.lp_mandate_guidelines g LEFT JOIN {s}.claims c ON c.claim_id=g.source_claim_id WHERE g.evidence_status='SOURCE_CLAIM' AND c.claim_id IS NULL",
 'orphan_amounts':f"SELECT count(*)::int FROM {s}.lp_mandate_amounts a LEFT JOIN {s}.claims c ON c.claim_id=a.source_claim_id WHERE a.evidence_status='SOURCE_CLAIM' AND c.claim_id IS NULL",
 'duplicate_mandate_codes':f"SELECT mandate_code,count(*)::int FROM {s}.lp_mandates GROUP BY 1 HAVING count(*)>1",
 }
 out={}
 with psycopg.connect(e['SUPABASE_DB_URL']) as c:
  c.execute('SET TRANSACTION READ ONLY')
  for name,sql in q.items():
   cur=c.execute(sql);cols=[d.name for d in cur.description];rows=cur.fetchall();out[name]=rows[0][0] if len(rows)==1 and len(cols)==1 else [dict(zip(cols,r)) for r in rows]
 assert out['cutoff_partitions']==14,out
 assert out['research_record_count']==47,out
 assert out['research_url_count']>=45,out
 assert len(out['new_mandates'])==7,out
 assert out['new_tracks']==8,out
 assert len(out['new_selections'])==1,out
 assert out['orphan_tracks']==out['orphan_guidelines']==out['orphan_amounts']==0,out
 assert out['duplicate_mandate_codes']==[],out
 print(json.dumps(out,ensure_ascii=False,default=str,indent=2))
if __name__=='__main__': main()
