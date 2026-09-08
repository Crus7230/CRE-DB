from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from scripts import run_market_refresh_pipeline as pipeline

NOW = datetime(2026, 8, 31, 1, tzinfo=timezone.utc)


def freshness(timestamp="2026-08-31T00:15:35Z"):
    return {"source_freshness": {"document_versions": 20, "rss_latest_collected_at": timestamp},
            "candidate_freshness": {"document_versions": 25, "rss_latest_collected_at": timestamp}}


def test_source_freshness_fails_closed():
    assert pipeline.validate_freshness(freshness(), now=NOW, max_age_hours=36)["sourceAgeHours"] < 1
    with pytest.raises(RuntimeError, match="stale"):
        pipeline.validate_freshness(freshness("2026-08-21T00:15:00Z"), now=NOW, max_age_hours=36)
    missing = freshness()
    missing["candidate_freshness"]["rss_latest_collected_at"] = "2026-08-30T00:00:00Z"
    with pytest.raises(RuntimeError, match="behind"):
        pipeline.validate_freshness(missing, now=NOW, max_age_hours=36)
    missing = freshness()
    missing["candidate_freshness"]["document_versions"] = 19
    with pytest.raises(RuntimeError, match="lost"):
        pipeline.validate_freshness(missing, now=NOW, max_age_hours=36)


def execute(tmp_path, *, apply=True, sync=True, sync_failure=False, stale=False):
    db = tmp_path / "market.db"
    db.write_bytes(b"original")
    calls = []

    def merge(archive, candidate, env):
        calls.append("merge")
        sqlite3.connect(candidate).close()
        return freshness("2026-08-21T00:15:00Z" if stale else "2026-08-31T00:15:35Z")

    def analyze(conn, **kwargs):
        calls.append("analyze")
        assert kwargs["reference_date"].isoformat() == "2026-08-31"
        return {"runId": "test-run", "status": "COMPLETED"}

    def sync_runner(env, archive, *, apply, **kwargs):
        calls.append("sync_apply" if apply else "sync_rehearsal")
        assert kwargs["sync_only"] is True
        if sync_failure:
            raise RuntimeError("password=do-not-leak")
        return {"status": "applied" if apply else "rollback_rehearsal"}

    def activate(candidate, archive):
        calls.append("activate")
        return {"activated": True}

    with patch.object(pipeline, "merge_archive", merge), \
         patch.object(pipeline, "run_daily_refresh", analyze), \
         patch.object(pipeline, "validate_candidate", return_value={"integrity": "ok"}), \
         patch.object(pipeline, "sync_analytics", sync_runner), \
         patch.object(pipeline, "activate", activate):
        report = pipeline.run_pipeline(
            db=db, env_file=tmp_path / "env", apply=apply, sync=sync, now=NOW,
            report_path=tmp_path / "report.json", log_path=tmp_path / "log.jsonl",
        )
    return report, calls


def test_pipeline_orders_merge_analysis_rehearsal_activation_and_sync(tmp_path):
    report, calls = execute(tmp_path)
    assert calls == ["merge", "analyze", "sync_rehearsal", "activate", "sync_apply"]
    assert report["status"] == "COMPLETED"


def test_rehearsal_never_activates_or_commits_supabase(tmp_path):
    report, calls = execute(tmp_path, apply=False)
    assert calls == ["merge", "analyze", "sync_rehearsal"]
    assert report["status"] == "REHEARSED"
    assert (tmp_path / "market.db").read_bytes() == b"original"


def test_failed_sync_rehearsal_preserves_original_and_sanitizes(tmp_path):
    report, calls = execute(tmp_path, sync_failure=True)
    assert calls == ["merge", "analyze", "sync_rehearsal"]
    assert report["status"] == "FAILED" and report["stage"] == "sync_rehearsal"
    assert "do-not-leak" not in (tmp_path / "report.json").read_text()


def test_stale_source_stops_before_analysis_or_sync(tmp_path):
    report, calls = execute(tmp_path, stale=True)
    assert calls == ["merge"]
    assert report["status"] == "FAILED" and report["stage"] == "source_freshness"


def test_disabled_sync_is_never_reported_as_end_to_end_success(tmp_path):
    report, calls = execute(tmp_path, sync=False)
    assert calls == ["merge", "analyze", "activate"]
    assert report["status"] == "LOCAL_ONLY_SYNC_DISABLED"


def test_installed_shim_delegates_without_copied_pipeline_logic():
    text = (pipeline.ROOT / "operations/hermes/daily_cre_articles_entrypoint.py").read_text(encoding="utf-8")
    assert 'runpy.run_path' in text and 'operations/hermes/daily_cre_articles.py' in text
    assert 'collect_daily_rss_supabase.py' not in text
    assert '기획추진' in text
