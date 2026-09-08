import argparse
from datetime import date, datetime
import json

import pytest

import scripts.collect_daily_rss_supabase as collector


q = collector.q
utc_window_for_seoul_day = collector.utc_window_for_seoul_day


def test_seoul_day_uses_utc_boundaries() -> None:
    start, end = utc_window_for_seoul_day(date(2026, 8, 19))
    assert start.isoformat() == "2026-08-18T15:00:00+00:00"
    assert end.isoformat() == "2026-08-19T15:00:00+00:00"


def test_postgres_identifier_guard() -> None:
    assert q("market_intelligence") == '"market_intelligence"'
    with pytest.raises(ValueError):
        q("market_intelligence; drop schema public")


def test_incremental_slot_behavior_has_a_new_runner_version() -> None:
    assert collector.RUNNER_VERSION == "daily-google-news-rss-postgres-v2"
    assert collector.JOB_VERSION == 2


def test_daily_config_covers_2026_managed_market_families() -> None:
    config = json.loads(collector.DEFAULT_CONFIG.read_text(encoding="utf-8"))

    assert config["year"] == 2026
    assert set(config["categories"]) == {
        "SALE", "LEASE", "NEW_SUPPLY", "PERMIT", "PF", "LOAN", "INVESTMENT",
    }
    assert all(term in config["categories"]["SALE"] for term in ("매각", "매입", "공매", "경매"))
    assert all(term in config["categories"]["LEASE"] for term in ("임대차계약", "본사이전", "공실"))
    assert all(term in config["categories"]["NEW_SUPPLY"] for term in ("착공", "준공", "사용승인"))
    assert all(term in config["categories"]["PF"] for term in ("본PF", "리파이낸싱", "EOD"))


@pytest.mark.parametrize(
    ("moment", "expected_slot"),
    [
        ("2026-08-19T00:00:00+09:00", "2026-08-18T21:00+09:00"),
        ("2026-08-19T05:59:59+09:00", "2026-08-18T21:00+09:00"),
        ("2026-08-19T06:00:00+09:00", "2026-08-19T06:00+09:00"),
        ("2026-08-19T11:59:59+09:00", "2026-08-19T09:00+09:00"),
        ("2026-08-19T12:00:00+09:00", "2026-08-19T12:00+09:00"),
        ("2026-08-19T18:00:00+09:00", "2026-08-19T18:00+09:00"),
        ("2026-08-19T21:00:00+09:00", "2026-08-19T21:00+09:00"),
        ("2026-08-19T23:59:59+09:00", "2026-08-19T21:00+09:00"),
    ],
)
def test_collection_slot_key_uses_most_recent_scheduler_fire(
    moment: str,
    expected_slot: str,
) -> None:
    assert collector.collection_slot_key(datetime.fromisoformat(moment)) == expected_slot


def test_explicit_collection_slot_requires_a_real_scheduler_fire() -> None:
    assert collector.parse_collection_slot("2026-08-19T15:00:00+09:00") == "2026-08-19T15:00+09:00"
    with pytest.raises(argparse.ArgumentTypeError):
        collector.parse_collection_slot("2026-08-19T14:52:00+09:00")


def test_collection_run_lock_uses_transaction_advisory_lock() -> None:
    calls: list[tuple[str, tuple[str]]] = []

    class Connection:
        def execute(self, sql: str, params: tuple[str]):
            calls.append((sql, params))

    collector.lock_collection_run(Connection(), "run-123")

    assert calls == [
        ("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("run-123",))
    ]


def test_statement_timeout_is_committed_before_partition_transactions() -> None:
    calls = []

    class Connection:
        def execute(self, sql):
            calls.append(("execute", sql))

        def commit(self):
            calls.append(("commit", None))

    collector.configure_connection(Connection())

    assert calls == [
        ("execute", "SET statement_timeout TO 60000"),
        ("commit", None),
    ]


def test_partition_cursor_identity_changes_between_collection_slots() -> None:
    morning = collector.partition_cursor_json(
        date(2026, 8, 19),
        "2026-08-19T09:15+09:00",
    )
    afternoon = collector.partition_cursor_json(
        date(2026, 8, 19),
        "2026-08-19T15:15+09:00",
    )

    assert morning != afternoon
    assert morning == collector.partition_cursor_json(
        date(2026, 8, 19),
        "2026-08-19T09:15+09:00",
    )
