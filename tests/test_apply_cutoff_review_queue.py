from datetime import date

import pytest

from scripts.apply_cutoff_review_queue import quote_ident, stable_id


def test_stable_id_is_deterministic_and_namespaced():
    first = stable_id("cutoff_em", "doc-1", "SALE", "v1")
    assert first == stable_id("cutoff_em", "doc-1", "SALE", "v1")
    assert first.startswith("cutoff_em_")
    assert first != stable_id("cutoff_em", "doc-1", "LEASE", "v1")


def test_quote_ident_rejects_unsafe_schema_name():
    assert quote_ident("market_intelligence") == '"market_intelligence"'
    with pytest.raises(ValueError):
        quote_ident("market_intelligence;drop schema public")


def test_cutoff_date_contract_is_explicit():
    assert date.fromisoformat("2026-08-19").isoformat() == "2026-08-19"
