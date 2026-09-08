from __future__ import annotations

from pathlib import Path
import sqlite3

from collector.financial_macro import (
    SERIES_BY_CODE, ensure_series, fetch_ecos, fetch_nyfed, parse_ecos_rows, parse_nyfed_rows,
    parse_treasury_xml, store_source_snapshot,
)

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "db/v2/schema.sql"
SEED = ROOT / "db/v2/seed.sql"
MIGRATION = ROOT / "db/v2/migrations/3.7.0_financial_macro.sqlite.sql"
SEMANTICS_PATCH = ROOT / "db/v2/migrations/3.7.1_financial_macro_semantics.sqlite.sql"
VALIDITY_PATCH = ROOT / "db/v2/migrations/3.7.2_financial_macro_validity.sqlite.sql"


def migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    conn.executescript(SEMANTICS_PATCH.read_text(encoding="utf-8"))
    conn.executescript(VALIDITY_PATCH.read_text(encoding="utf-8"))
    return conn


def test_financial_macro_feature_is_additive() -> None:
    conn = migrated()
    try:
        assert conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0] == "3.5.0"
        assert conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='financial_macro_schema_version'").fetchone()[0] == "1.0.2"
        objects = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        assert {"v_latest_macro_observations", "v_financial_macro_monthly", "financial_macro_monthly_serving"} <= objects
        assert conn.execute("SELECT count(*) FROM collection_sources WHERE source_id IN ('src_ny_fed','src_us_treasury')").fetchone()[0] == 2
    finally:
        conn.close()


def test_official_source_parsers() -> None:
    ecos = parse_ecos_rows(SERIES_BY_CODE["KR_GOVT_BOND_10Y"], [{"STAT_CODE":"721Y001","ITEM_CODE1":"5050000","ITEM_NAME1":"국고채(10년)","UNIT_NAME":"연%","TIME":"202601","DATA_VALUE":"3.125"}])
    assert ecos[0]["period_start"] == "2026-01-01"
    assert ecos[0]["period_end"] == "2026-01-31"
    assert ecos[0]["numeric_value"] == 3.125

    nyfed = parse_nyfed_rows("EFFR", [{"effectiveDate":"2026-01-02","type":"EFFR","percentRate":4.1,"targetRateFrom":4.0,"targetRateTo":4.25,"revisionIndicator":"R"}])
    assert {r["series_code"] for r in nyfed} == {"US_EFFR", "US_FED_TARGET_LOWER", "US_FED_TARGET_UPPER"}
    assert all(r["observation_status"] == "REVISED" for r in nyfed)
    legacy = parse_nyfed_rows("EFFR", [{"effectiveDate":"2007-01-03","type":"EFFR","percentRate":5.25,"targetRateFrom":5.25,"targetRateTo":None}])
    assert [r["series_code"] for r in legacy] == ["US_EFFR"]

    xml = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"><entry><content><m:properties><d:Id>1</d:Id><d:NEW_DATE>2026-01-02T00:00:00</d:NEW_DATE><d:BC_2YEAR>3.50</d:BC_2YEAR><d:BC_10YEAR>4.25</d:BC_10YEAR><d:BC_30YEAR>4.70</d:BC_30YEAR></m:properties></content></entry></feed>'''
    treasury = parse_treasury_xml(xml)
    values = {r["series_code"]: r["value_decimal_text"] for r in treasury}
    assert values["US_TREASURY_10Y_MINUS_2Y"] == "0.75"


def test_revision_safe_storage_and_monthly_view(tmp_path: Path) -> None:
    conn = migrated()
    try:
        ensure_series(conn)
        artifact = tmp_path / "source.json"
        artifact.write_text("{}", encoding="utf-8")
        first = [{"series_code":"KR_GOVT_BOND_10Y","period_start":"2026-01-01","period_end":"2026-01-31","numeric_value":3.1,"value_decimal_text":"3.1","raw_value":"3.1","source_record_key":"KR_GOVT_BOND_10Y:2026-01-01","observation_status":"FINAL","metadata":{}}]
        a = store_source_snapshot(conn,"src_bok","BOK_ECOS",first,artifact,"a"*64,"2026-02-01T00:00:00Z")
        b = store_source_snapshot(conn,"src_bok","BOK_ECOS",first,artifact,"a"*64,"2026-02-02T00:00:00Z")
        changed = [{**first[0],"numeric_value":3.2,"value_decimal_text":"3.2","raw_value":"3.2"}]
        c = store_source_snapshot(conn,"src_bok","BOK_ECOS",changed,artifact,"b"*64,"2026-02-03T00:00:00Z")
        assert a["inserted"] == 1 and b["unchanged"] == 1 and c["revised"] == 1
        row = conn.execute("SELECT numeric_value,observation_count FROM v_financial_macro_monthly WHERE series_code='KR_GOVT_BOND_10Y'").fetchone()
        assert row == (3.2, 1)
    finally:
        conn.close()


def test_recurring_fetches_accept_bounded_correction_windows(monkeypatch) -> None:
    urls = []

    def fake_bytes(url: str, **_kwargs) -> bytes:
        urls.append(url)
        if "ecos.bok.or.kr" in url:
            return b'{"StatisticSearch":{"list_total_count":0,"row":[]}}'
        return b'{"refRates":[]}'

    monkeypatch.setattr("collector.financial_macro.fetch_bytes", fake_bytes)
    fetch_ecos("sample", "202609", start_month="202409", sleep_seconds=0)
    fetch_nyfed("2026-09-08", start_date="2024-09-01")
    ecos_urls = [url for url in urls if "ecos.bok.or.kr" in url]
    nyfed_urls = [url for url in urls if "newyorkfed.org" in url]
    assert ecos_urls and all("/202409/202609/" in url for url in ecos_urls)
    assert nyfed_urls and all("startDate=2024-09-01" in url for url in nyfed_urls)
