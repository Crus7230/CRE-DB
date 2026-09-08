"""Run deterministic keyword and evidence-backed signal refresh as one bounded daily operation."""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.refresh_insight_signals import refresh_insight_signals
from scripts.refresh_keyword_analytics import refresh_keywords

ALGORITHM_VERSION = "DAILY_ANALYTICS_V1"
PIPELINE_CODE = "ANALYTICS_DAILY"

class AlreadyRunning(RuntimeError): pass

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")

@contextmanager
def analytics_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.touch(exist_ok=True)
    handle=path.open("r+b")
    if path.stat().st_size == 0:
        handle.write(b"0"); handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            try: msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as error: raise AlreadyRunning("analytics refresh already running") from error
        else:
            import fcntl
            try: fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as error: raise AlreadyRunning("analytics refresh already running") from error
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        except OSError: pass
        handle.close()

@contextmanager
def refresh_connection(db: Path, *, apply: bool) -> Iterator[sqlite3.Connection]:
    if apply:
        conn=sqlite3.connect(db,timeout=5)
    else:
        source=sqlite3.connect(f"file:{db.as_posix()}?mode=ro",uri=True)
        conn=sqlite3.connect(":memory:")
        try: source.backup(conn)
        finally: source.close()
    conn.execute("pragma foreign_keys=on")
    try: yield conn
    finally: conn.close()

def _output_rows(keyword: dict, signal: dict) -> int:
    return int(keyword.get("observations_written",0))+int(signal.get("signals_planned",0))+int(signal.get("evidence_written",0))

def _record_failure(conn: sqlite3.Connection, run_id: str, started: str, exception_type: str, retry_count: int,
                    window_start: str, window_end: str) -> None:
    completed=utc_now(); metadata=json.dumps({"exceptionType":exception_type,"retryCount":retry_count},sort_keys=True)
    conn.execute("""INSERT INTO analytics_refresh_runs(
      analytics_refresh_run_id,pipeline_code,status_code,algorithm_version,window_start,window_end,source_scope_code,input_count,output_count,started_at,completed_at,error_code,metadata_json
      ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(analytics_refresh_run_id) DO UPDATE SET status_code='FAILED',completed_at=excluded.completed_at,error_code=excluded.error_code,metadata_json=excluded.metadata_json""",
      (run_id,PIPELINE_CODE,"FAILED",ALGORITHM_VERSION,window_start,window_end,"ROLLING_90D",0,0,started,completed,exception_type,metadata))
    conn.commit()

def run_daily_refresh(conn: sqlite3.Connection, *, apply: bool=False,
    keyword_runner: Callable=refresh_keywords, signal_runner: Callable=refresh_insight_signals,
    max_attempts: int=3, sleep: Callable[[float],None]=time.sleep,
    reference_date: date | None=None, window_start: str | None=None, window_end: str | None=None) -> dict:
    version=conn.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()
    if not version or version[0] not in {"3.4.1", "3.5.0"}: raise RuntimeError(f"daily analytics requires schema 3.4.1 or 3.5.0, found {version[0] if version else 'missing'}")
    today=reference_date or datetime.now(timezone.utc).date()
    window_start=window_start or (today-timedelta(days=89)).isoformat()
    window_end=window_end or (today+timedelta(days=1)).isoformat()
    if not apply:
        keyword=keyword_runner(conn,apply=False,commit=False,window_start=window_start,window_end=window_end)
        signal=signal_runner(conn,apply=False,commit=False,window_start=window_start,window_end=window_end)
        return {"applied":False,"status":"DRY_RUN","algorithmVersion":ALGORITHM_VERSION,"windowStart":window_start,"windowEnd":window_end,"keyword":keyword,"signal":signal}
    max_attempts=max(1,min(5,int(max_attempts))); run_id=f"analytics-daily-{uuid.uuid4().hex}"; started=utc_now()
    for attempt in range(max_attempts):
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""INSERT INTO analytics_refresh_runs(
              analytics_refresh_run_id,pipeline_code,status_code,algorithm_version,window_start,window_end,source_scope_code,input_count,output_count,started_at,metadata_json
              ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (run_id,PIPELINE_CODE,"RUNNING",ALGORITHM_VERSION,window_start,window_end,"ROLLING_90D",0,0,started,json.dumps({"retryCount":attempt})))
            keyword=keyword_runner(conn,apply=True,commit=False,window_start=window_start,window_end=window_end)
            signal=signal_runner(conn,apply=True,commit=False,window_start=window_start,window_end=window_end)
            input_count=int(keyword.get("documents_in_scope",0)); output=_output_rows(keyword,signal); completed=utc_now()
            metadata=json.dumps({"retryCount":attempt,"keyword":keyword,"signal":signal},ensure_ascii=False,sort_keys=True)
            conn.execute("UPDATE analytics_refresh_runs SET status_code='COMPLETED',input_count=?,output_count=?,completed_at=?,metadata_json=? WHERE analytics_refresh_run_id=?",(input_count,output,completed,metadata,run_id))
            conn.commit()
            return {"applied":True,"status":"COMPLETED","runId":run_id,"retryCount":attempt,"windowStart":window_start,"windowEnd":window_end,"outputRows":output,"keyword":keyword,"signal":signal}
        except sqlite3.OperationalError as error:
            conn.rollback()
            if "locked" in str(error).lower() and attempt+1<max_attempts:
                sleep(min(8.0,2.0**attempt)); continue
            _record_failure(conn,run_id,started,type(error).__name__,attempt,window_start,window_end); raise
        except Exception as error:
            conn.rollback(); _record_failure(conn,run_id,started,type(error).__name__,attempt,window_start,window_end); raise
    raise AssertionError("unreachable")

def append_log(path: Path, event: str, report: dict | None=None) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    safe={"timestamp":utc_now(),"event":event}
    if report: safe.update({key:report.get(key) for key in ("status","runId","retryCount","outputRows")})
    with path.open("a",encoding="utf-8") as handle: handle.write(json.dumps(safe,ensure_ascii=False)+"\n")

def main() -> None:
    root=Path(__file__).parents[1]; default_db=root/"data/market.db"
    parser=argparse.ArgumentParser(); parser.add_argument("--db",type=Path,default=default_db); parser.add_argument("--apply",action="store_true"); parser.add_argument("--allow-live-db",action="store_true"); parser.add_argument("--max-attempts",type=int,default=3); parser.add_argument("--lock",type=Path); parser.add_argument("--log",type=Path,default=root/"logs/daily-analytics-refresh.jsonl"); args=parser.parse_args()
    db=args.db.resolve(); lock=(args.lock or db.with_suffix(db.suffix+".analytics.lock")).resolve()
    if args.apply and db == default_db.resolve() and not args.allow_live_db: raise SystemExit("live DB apply requires --allow-live-db")
    try:
        with analytics_file_lock(lock):
            original_mode=db.stat().st_mode; made_writable=False
            try:
                if args.apply and not (original_mode & stat.S_IWRITE):
                    db.chmod(original_mode|stat.S_IWRITE); made_writable=True
                with refresh_connection(db,apply=args.apply) as conn:
                    report=run_daily_refresh(conn,apply=args.apply,max_attempts=args.max_attempts)
            finally:
                if made_writable: db.chmod(original_mode)
        append_log(args.log,"COMPLETED" if args.apply else "DRY_RUN",report); print(json.dumps(report,ensure_ascii=False,indent=2))
    except AlreadyRunning:
        append_log(args.log,"ALREADY_RUNNING"); raise SystemExit(75)
    except Exception as error:
        append_log(args.log,"FAILED",{"status":"FAILED"}); print(json.dumps({"status":"FAILED","exceptionType":type(error).__name__}),file=os.sys.stderr); raise SystemExit(1) from None

if __name__ == "__main__": main()
