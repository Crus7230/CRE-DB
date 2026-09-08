import json
from pathlib import Path

import pytest

from collector.approved_lp_mandate_manifest import validate_manifest
from scripts.apply_approved_lp_manifest_postgres import quote_ident

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = [
    ROOT / "fixtures" / "approved-lp-mandates" / "pensions-mutual-aid" / name
    for name in (
        "KOREAPOST-2026-DOMESTIC-REIT.json",
        "KOREAPOST-INSURANCE-2026-DOMESTIC-MULTISTRATEGY.json",
        "NPS-2026-DOMESTIC-REAL-ESTATE.json",
        "CW-2026-DOMESTIC-SENIOR-LOAN.json",
        "KBIZ-2026-DOMESTIC-EQUITY-BLIND.json",
        "POBA-2026-PUBLIC-GOLF.json",
        "KHUG-FUTURE-CITY-FUND-1-RESULT.json",
    )
]


def test_postgres_importer_rejects_unsafe_schema():
    assert quote_ident("market_intelligence") == '"market_intelligence"'
    with pytest.raises(ValueError):
        quote_ident("market_intelligence;drop schema public")


@pytest.mark.parametrize("path", MANIFESTS)
def test_koreapost_2026_manifests_pass_approved_preflight(path: Path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    assert manifest["mandate"]["vintage_year"] == 2026
    if path.name == "KHUG-FUTURE-CITY-FUND-1-RESULT.json":
        assert manifest["mandate"]["mandate_status"] == "SELECTED"
        assert manifest["selections"][0]["manager_organization_id"] == "org-woori-am"
        assert manifest["amounts"] == []
    else:
        assert manifest["selections"] == []
        assert manifest["amounts"][0]["amount_basis"] == "TRACK_LP_COMMITMENT"
