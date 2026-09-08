"""Create immutable, reviewable keyword-burst signals with explicit evidence."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ALGORITHM_VERSION="KEYWORD_BURST_SIGNAL_V1"
MIN_DOCUMENT_FREQUENCY=3
MIN_BURST_SCORE=2.0
MAX_SIGNALS=20
MAX_EVIDENCE=5

def now()->str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")

def sid(prefix:str,*parts:str)->str:
    return f"{prefix}-"+hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]

def candidates(conn:sqlite3.Connection,window_start:str|None=None,window_end:str|None=None)->list[sqlite3.Row]:
    conn.row_factory=sqlite3.Row
    params=(MIN_DOCUMENT_FREQUENCY,MIN_BURST_SCORE,window_start,window_start,window_end,window_end,
            MIN_DOCUMENT_FREQUENCY,MIN_BURST_SCORE,window_start,window_start,window_end,window_end,MAX_SIGNALS)
    return conn.execute("""
      WITH latest_algorithm AS (
        SELECT algorithm_version FROM analytics_refresh_runs
        WHERE pipeline_code='KEYWORD_DAILY' AND status_code='COMPLETED'
        ORDER BY completed_at DESC,analytics_refresh_run_id DESC LIMIT 1
      ), qualified_day AS (
        SELECT max(o.bucket_date) day FROM keyword_observations_daily o
        JOIN keyword_dictionary k USING(keyword_id)
        JOIN latest_algorithm a ON a.algorithm_version=o.algorithm_version
        WHERE k.status_code='ACTIVE' AND k.is_collection_bias=0
          AND o.document_frequency>=? AND o.burst_score>=?
          AND (? IS NULL OR o.bucket_date>=?) AND (? IS NULL OR o.bucket_date<?)
      )
      SELECT o.*,k.normalized_term,k.display_term,k.is_collection_bias
      FROM keyword_observations_daily o JOIN keyword_dictionary k USING(keyword_id)
      JOIN latest_algorithm a ON a.algorithm_version=o.algorithm_version
      JOIN qualified_day d ON d.day=o.bucket_date
      WHERE k.status_code='ACTIVE' AND k.is_collection_bias=0
        AND o.document_frequency>=? AND o.burst_score>=?
        AND (? IS NULL OR o.bucket_date>=?) AND (? IS NULL OR o.bucket_date<?)
      ORDER BY o.burst_score DESC,o.document_frequency DESC,k.display_term LIMIT ?
    """,params).fetchall()

def evidence_rows(conn:sqlite3.Connection,term:str,signal_date:str)->list[sqlite3.Row]:
    return conn.execute("""
      WITH latest AS (
        SELECT dv.*,row_number() OVER(PARTITION BY dv.document_id ORDER BY dv.version_no DESC,dv.document_version_id DESC) rn
        FROM document_versions dv
      )
      SELECT sd.document_id,l.document_version_id,l.title,l.published_at,sd.canonical_url,
             sd.source_id,cs.source_name,cs.authority_tier
      FROM latest l JOIN source_documents sd ON sd.document_id=l.document_id
      LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
      WHERE l.rn=1 AND date(l.published_at)=?
        AND lower(coalesce(l.title,'')||' '||coalesce(l.snippet_text,'')) LIKE ?
      ORDER BY coalesce(cs.authority_tier,99),l.published_at DESC,sd.document_id LIMIT ?
    """,(signal_date,f"%{term}%",MAX_EVIDENCE)).fetchall()

def refresh_insight_signals(conn:sqlite3.Connection,*,apply:bool=False,commit:bool=True,
                            window_start:str|None=None,window_end:str|None=None)->dict[str,int|bool|str]:
    rows=candidates(conn,window_start,window_end);computed=now();evidence_total=0;signal_total=0;accepted_ids:set[str]=set()
    conn.execute("SAVEPOINT insight_refresh")
    try:
        for row in rows:
            signal_id=sid("signal","KEYWORD_BURST",row["bucket_date"],row["keyword_id"],ALGORITHM_VERSION)
            existing=conn.execute("SELECT review_status FROM insight_signals WHERE insight_signal_id=?",(signal_id,)).fetchone()
            if existing:
                accepted_ids.add(signal_id);signal_total+=1
                evidence_total+=conn.execute("SELECT count(*) FROM insight_signal_evidence WHERE insight_signal_id=?",(signal_id,)).fetchone()[0]
                continue
            evidence=evidence_rows(conn,row["normalized_term"],row["bucket_date"])
            source_count=len({item["source_id"] for item in evidence if item["source_id"]})
            if not evidence or source_count<2:continue
            strength=min(1.0,max(0.0,float(row["burst_score"])/5.0));evidence_score=min(1.0,len(evidence)/5.0);diversity=min(1.0,source_count/3.0)
            confidence=round(.5*strength+.3*evidence_score+.2*diversity,6)
            severity="HIGH" if strength>=.8 and evidence_score>=.4 else "MEDIUM" if strength>=.5 else "LOW"
            accepted_ids.add(signal_id)
            summary=f"발행일 기준 고유 문서 {row['document_frequency']}건, 28일 baseline {float(row['baseline_document_frequency']):.1f}건"
            metadata=json.dumps({"frequency_semantics":"DISTINCT_DOCUMENT","syndication_dedupe_status":"PARTIAL","source_count":source_count},ensure_ascii=False)
            conn.execute("INSERT INTO insight_signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
              (signal_id,"KEYWORD_BURST",row["bucket_date"],f"{row['display_term']} 언급 급상승",summary,"UNREVIEWED",severity,row["keyword_id"],strength,evidence_score,diversity,confidence,ALGORITHM_VERSION,computed,row["bucket_date"],row["bucket_date"],metadata))
            for rank,item in enumerate(evidence,1):
                evidence_id=sid("signal-evidence",signal_id,item["document_id"],"TRIGGER")
                detail={"source_id":item["source_id"],"source_name":item["source_name"],"authority_tier":item["authority_tier"],"published_at":item["published_at"],"canonical_url":item["canonical_url"]}
                conn.execute("INSERT INTO insight_signal_evidence VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(insight_signal_id,target_kind,target_id,evidence_role) DO NOTHING",
                  (evidence_id,signal_id,"DOCUMENT",item["document_id"],"TRIGGER",item["document_version_id"],rank,item["title"],json.dumps(detail,ensure_ascii=False),computed))
            evidence_total+=len(evidence);signal_total+=1
        scope=" AND (? IS NULL OR signal_date>=?) AND (? IS NULL OR signal_date<?)";scope_args=(window_start,window_start,window_end,window_end)
        if accepted_ids:
            placeholders=",".join("?" for _ in accepted_ids)
            superseded=conn.execute(f"UPDATE insight_signals SET review_status='SUPERSEDED' WHERE algorithm_version=? AND review_status='UNREVIEWED'{scope} AND insight_signal_id NOT IN ({placeholders})",(ALGORITHM_VERSION,*scope_args,*sorted(accepted_ids))).rowcount
        else:
            superseded=conn.execute(f"UPDATE insight_signals SET review_status='SUPERSEDED' WHERE algorithm_version=? AND review_status='UNREVIEWED'{scope}",(ALGORITHM_VERSION,*scope_args)).rowcount
        if apply:
            conn.execute("RELEASE insight_refresh")
            if commit:conn.commit()
        else:
            conn.execute("ROLLBACK TO insight_refresh");conn.execute("RELEASE insight_refresh")
    except Exception:
        conn.execute("ROLLBACK TO insight_refresh");conn.execute("RELEASE insight_refresh");raise
    return {"applied":apply,"algorithm_version":ALGORITHM_VERSION,"signals_planned":signal_total,"evidence_written":evidence_total,"signals_superseded":max(superseded,0)}

def main()->None:
    p=argparse.ArgumentParser();p.add_argument("--db",type=Path,default=Path(__file__).parents[1]/"data/market.db");p.add_argument("--apply",action="store_true");p.add_argument("--window-start");p.add_argument("--window-end");a=p.parse_args()
    conn=sqlite3.connect(a.db);conn.execute("pragma foreign_keys=on")
    try:
        version=conn.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()
        if not version or version[0] not in {"3.4.1","3.5.0"}:raise SystemExit(f"Expected schema 3.4.1 or 3.5.0, found {version[0] if version else 'missing'}")
        print(json.dumps(refresh_insight_signals(conn,apply=a.apply,window_start=a.window_start,window_end=a.window_end),ensure_ascii=False,indent=2))
    finally:conn.close()
if __name__=="__main__":main()
