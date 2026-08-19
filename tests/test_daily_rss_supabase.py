from datetime import date

import pytest

from scripts.collect_daily_rss_supabase import q, utc_window_for_seoul_day


def test_seoul_day_uses_utc_boundaries() -> None:
    start, end = utc_window_for_seoul_day(date(2026, 8, 19))
    assert start.isoformat() == "2026-08-18T15:00:00+00:00"
    assert end.isoformat() == "2026-08-19T15:00:00+00:00"


def test_postgres_identifier_guard() -> None:
    assert q("market_intelligence") == '"market_intelligence"'
    with pytest.raises(ValueError):
        q("market_intelligence; drop schema public")
