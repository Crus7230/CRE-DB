import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from collector.backfill_2025 import DiscoveredDocument, ingest_partition
from scripts.collect_daily_rss_sqlite import (
    activate_candidate,
    classify_candidate,
    collect_partitions,
    retire_shadowed_v1_daily_jobs,
)

ROOT = Path(__file__).resolve().parents[1]


def test_activate_candidate_replaces_readonly_archive_and_restores_readonly_mode() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "market.db"
        candidate = root / "candidate.db"
        backup = root / "backups" / "pre.db"
        archive.write_text("old", encoding="utf-8")
        candidate.write_text("new", encoding="utf-8")
        archive.chmod(0o444)

        activate_candidate(candidate, archive, backup)

        assert archive.read_text(encoding="utf-8") == "new"
        assert backup.read_text(encoding="utf-8") == "old"
        assert not candidate.exists()
        assert archive.stat().st_mode & 0o222 == 0
        assert backup.stat().st_mode & 0o222 == 0


def test_retire_shadowed_v1_daily_jobs_preserves_runs_and_keeps_v2_active() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "market.db"
        con = sqlite3.connect(db_path)
        con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
        con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
        con.close()

        common = dict(
            db_path=db_path, source_code="GOOGLE_NEWS_RSS",
            job_code="DAILY_GOOGLE_NEWS_RSS_SALE", category_code="SALE",
            window_start="2026-09-04T00:00:00Z", window_end="2026-09-05T00:00:00Z",
            query_rendered="sale", documents=[], runner_version="test",
        )
        ingest_partition(**common, job_version=1, cadence_code="MANUAL")
        ingest_partition(**common, job_version=2, cadence_code="DAILY")

        assert retire_shadowed_v1_daily_jobs(db_path) == 1
        assert retire_shadowed_v1_daily_jobs(db_path) == 0
        con = sqlite3.connect(db_path)
        states = con.execute(
            "SELECT job_version,is_active FROM collection_jobs WHERE job_code='DAILY_GOOGLE_NEWS_RSS_SALE' ORDER BY job_version"
        ).fetchall()
        run_count = con.execute("SELECT count(*) FROM collection_runs").fetchone()[0]
        con.close()
        assert states == [(1, 0), (2, 1)]
        assert run_count == 2


def test_script_help_runs_from_project_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/collect_daily_rss_sqlite.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--allow-live-db" in result.stdout


def test_collect_partitions_writes_slot_provenance_and_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "market.db"
        con = sqlite3.connect(db_path)
        con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
        con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
        con.close()

        def fake_fetch(base_query: str, day: date):
            assert base_query == "상업용 부동산 매각"
            assert day == date(2026, 9, 4)
            return "상업용 부동산 매각 after:2026-09-03 before:2026-09-05", [
                DiscoveredDocument(
                    canonical_url="https://news.google.com/rss/articles/test",
                    external_key="guid-test",
                    title="서울 오피스 매각",
                    publisher_name="테스트신문",
                    published_at="2026-09-04T03:00:00Z",
                    snippet_text="서울 오피스 거래",
                    document_type="RSS_ITEM",
                    rights_status="EXCERPT_ALLOWED",
                )
            ]

        kwargs = {
            "db_path": db_path,
            "categories": {"SALE": "상업용 부동산 매각"},
            "target": date(2026, 9, 4),
            "lookback_days": 1,
            "collection_slot": "2026-09-04T15:15+09:00",
            "fetcher": fake_fetch,
        }
        first = collect_partitions(**kwargs)
        second = collect_partitions(**kwargs)

        assert first == {
            "partitions": 1,
            "skipped_partitions": 0,
            "discovered": 1,
            "inserted": 1,
            "updated": 0,
        }
        assert second["skipped_partitions"] == 1

        con = sqlite3.connect(db_path)
        run = con.execute("SELECT query_rendered,cursor_in FROM collection_runs").fetchone()
        job_contract = con.execute(
            "SELECT job_version,cadence_code FROM collection_jobs WHERE job_code='DAILY_GOOGLE_NEWS_RSS_SALE'"
        ).fetchone()
        counts = {
            "documents": con.execute("SELECT count(*) FROM source_documents").fetchone()[0],
            "versions": con.execute("SELECT count(*) FROM document_versions").fetchone()[0],
            "runs": con.execute("SELECT count(*) FROM collection_runs").fetchone()[0],
        }
        con.close()

        assert "collection_slot=2026-09-04T15:15+09:00" in run[0]
        assert json.loads(run[1])["collection_slot"] == "2026-09-04T15:15+09:00"
        assert job_contract == (2, "DAILY")
        assert counts == {"documents": 1, "versions": 1, "runs": 1}


def test_classify_candidate_creates_review_records_without_canonical_events() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "market.db"
        con = sqlite3.connect(db_path)
        con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
        con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
        con.close()

        def fake_fetch(_base_query: str, _day: date):
            return "오피스 매각 after:2026-09-03 before:2026-09-05", [
                DiscoveredDocument(
                    canonical_url="https://news.google.com/rss/articles/classify-test",
                    external_key="guid-classify-test",
                    title="서울 오피스 빌딩 매각 거래",
                    publisher_name="테스트신문",
                    published_at="2026-09-04T03:00:00Z",
                    snippet_text="상업용 부동산 오피스 매각",
                    document_type="RSS_ITEM",
                    rights_status="EXCERPT_ALLOWED",
                )
            ]

        collect_partitions(
            db_path=db_path,
            categories={"SALE": "오피스 매각"},
            target=date(2026, 9, 4),
            lookback_days=1,
            collection_slot="2026-09-04T15:15+09:00",
            fetcher=fake_fetch,
        )
        report = classify_candidate(
            db_path,
            from_date=date(2026, 9, 4),
            to_date=date(2026, 9, 5),
            collection_slot="2026-09-04T15:15+09:00",
        )

        assert report["status"] == "applied"
        assert report["candidates"] == 1
        assert report["canonicalEventsAfter"] == report["canonicalEventsBefore"]
        assert report["approvedMentionsAfter"] == report["approvedMentionsBefore"]
