from pathlib import Path
from datetime import date
import sqlite3
import sys

import pytest

ROOT = Path(__file__).parents[1]; sys.path.insert(0, str(ROOT))
from scripts.run_daily_analytics_refresh import AlreadyRunning, analytics_file_lock, refresh_connection, run_daily_refresh  # noqa: E402


def database() -> sqlite3.Connection:
    c=sqlite3.connect(":memory:")
    c.executescript("""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL);
      INSERT INTO schema_meta VALUES('schema_version','3.4.1');
      CREATE TABLE analytics_refresh_runs(
        analytics_refresh_run_id TEXT PRIMARY KEY,pipeline_code TEXT,status_code TEXT,algorithm_version TEXT,
        window_start TEXT,window_end TEXT,source_scope_code TEXT NOT NULL DEFAULT 'ALL',input_count INTEGER NOT NULL DEFAULT 0,output_count INTEGER NOT NULL DEFAULT 0,
        started_at TEXT,completed_at TEXT,error_code TEXT,metadata_json TEXT NOT NULL DEFAULT '{}'
      );
    """); return c


def test_dry_run_is_read_only_and_apply_records_ordered_success() -> None:
    c=database(); calls=[]
    def keyword(conn, *, apply, commit, window_start, window_end): calls.append(("keyword",apply,commit,window_start,window_end)); return {"observations_written":7}
    def signal(conn, *, apply, commit, window_start, window_end): calls.append(("signal",apply,commit,window_start,window_end)); return {"signals_planned":2,"evidence_written":3}
    dry=run_daily_refresh(c,apply=False,keyword_runner=keyword,signal_runner=signal,reference_date=date(2026,8,22))
    assert dry["applied"] is False and c.execute("select count(*) from analytics_refresh_runs").fetchone()[0] == 0
    result=run_daily_refresh(c,apply=True,keyword_runner=keyword,signal_runner=signal,reference_date=date(2026,8,22))
    assert result["status"] == "COMPLETED"
    assert calls == [("keyword",False,False,"2026-05-25","2026-08-23"),("signal",False,False,"2026-05-25","2026-08-23"),("keyword",True,False,"2026-05-25","2026-08-23"),("signal",True,False,"2026-05-25","2026-08-23")]
    assert c.execute("select window_start,window_end,source_scope_code from analytics_refresh_runs").fetchone() == ("2026-05-25","2026-08-23","ROLLING_90D")
    assert c.execute("select status_code,output_count from analytics_refresh_runs").fetchone() == ("COMPLETED",12)
    c.close()


def test_transient_lock_retries_but_terminal_failure_is_sanitized() -> None:
    c=database(); attempts=0
    def locked_then_ok(conn, *, apply, commit, window_start, window_end):
        nonlocal attempts; attempts+=1
        if attempts == 1: raise sqlite3.OperationalError("database is locked")
        return {"observations_written":1}
    ok=lambda conn,apply,commit,window_start,window_end: {"signals_planned":1,"evidence_written":1}
    result=run_daily_refresh(c,apply=True,keyword_runner=locked_then_ok,signal_runner=ok,max_attempts=2,sleep=lambda _:None)
    assert result["retryCount"] == 1 and attempts == 2
    def secret_failure(conn, *, apply, commit, window_start, window_end): raise RuntimeError("password=must-not-leak")
    with pytest.raises(RuntimeError): run_daily_refresh(c,apply=True,keyword_runner=secret_failure,signal_runner=ok,max_attempts=1)
    failed=c.execute("select status_code,error_code,metadata_json from analytics_refresh_runs where status_code='FAILED'").fetchone()
    assert failed[0] == "FAILED" and failed[1] == "RuntimeError" and "must-not-leak" not in failed[2] and "RuntimeError" in failed[2]
    c.close()


def test_file_lock_rejects_a_second_runner(tmp_path: Path) -> None:
    lock=tmp_path/"analytics.lock"
    with analytics_file_lock(lock):
        with pytest.raises(AlreadyRunning):
            with analytics_file_lock(lock): pass


def test_dry_run_connection_is_a_writable_memory_clone(tmp_path: Path) -> None:
    db=tmp_path/"authority.db"; c=sqlite3.connect(db); c.execute("create table sample(value integer)"); c.execute("insert into sample values(1)"); c.commit(); c.close()
    with refresh_connection(db,apply=False) as clone:
        clone.execute("insert into sample values(2)"); clone.commit()
        assert clone.execute("select count(*) from sample").fetchone()[0] == 2
    source=sqlite3.connect(f"file:{db.as_posix()}?mode=ro",uri=True)
    assert source.execute("select count(*) from sample").fetchone()[0] == 1
    source.close()
