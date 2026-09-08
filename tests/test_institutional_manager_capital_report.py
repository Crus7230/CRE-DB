import csv
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STEM = "institutional-manager-capital-and-dry-powder-20260816"


def test_manager_capital_report_preserves_evidence_layers_and_never_fabricates_dry_powder():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "report_institutional_manager_capital.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads((ROOT / "artifacts" / f"{STEM}.json").read_text(encoding="utf-8"))
    assert payload["summary"]["official_selection_rows"] == payload["live_counts"]["lp_mandate_selections"]
    assert payload["summary"]["official_selection_rows"] == 5
    assert payload["summary"]["official_domestic_asset_manager_rows"] == 1
    assert payload["summary"]["official_domestic_other_gp_rows"] == 2
    assert payload["summary"]["foreign_manager_rows"] == 1
    assert payload["summary"]["likely_domestic_manager_count"] == 5
    assert payload["summary"]["likely_reported_allocation_krw"] == "350000000000"
    assert payload["summary"]["verified_available_krw"] is None
    assert payload["qa"]["verified_available_never_fabricated"] is True
    assert payload["qa"]["selection_vehicle_rows"] == 0
    assert payload["qa"]["deployment_rows"] == 0
    assert payload["qa"]["source_balance_rows"] == 0

    likely = {x["manager_name"]: x for x in payload["likely_reported_domestic_managers"]}
    assert likely["캡스톤자산운용"]["reported_allocation_krw"] == "130000000000"
    assert likely["코람코자산운용"]["reported_allocation_krw"] == "70000000000"
    assert all(x["verified_available_krw"] is None for x in likely.values())

    official = payload["official_selections"]
    woori = next(x for x in official if x["manager_name"] == "우리글로벌자산운용")
    assert woori["capital_trace_status"] == "OFFICIAL_SELECTED_NO_COMMITMENT"
    assert woori["announced_track_commitment_krw"] == "27000000000"
    assert woori["verified_commitment_krw"] is None
    assert woori["verified_available_krw"] is None
    coolidge = [x for x in official if x["manager_name"] == "쿨리지코너인베스트먼트"]
    assert all(x["capital_trace_status"] == "OFFICIAL_SELECTED_REQUEST_AMOUNT_ONLY" for x in coolidge)
    gcm = next(x for x in official if x["manager_name"] == "GCM Grosvenor")
    assert gcm["capital_trace_status"] == "OFFICIAL_SELECTED_NO_AMOUNT"
    khug = next(x for x in official if x["manager_name"] == "우리자산운용")
    assert khug["mandate_code"] == "KHUG-FUTURE-CITY-FUND-1"
    assert khug["evidence_layer"] == "CANONICAL_VERIFIED_SELECTION"
    assert khug["capital_trace_status"] == "OFFICIAL_SELECTED_NO_AMOUNT"
    assert khug["verified_available_krw"] is None

    with (ROOT / "artifacts" / f"{STEM}.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    official_rows = [row for row in rows if row["evidence_layer"] == "CANONICAL_VERIFIED_SELECTION"]
    likely_rows = [row for row in rows if row["evidence_layer"] == "LIKELY_REPORTED_PENDING_PRIMARY"]
    assert len(official_rows) == len(official)
    assert {row["manager"] for row in likely_rows} == set(likely)
    assert all(not row["verified_available_krw"] for row in rows)

    md = (ROOT / "artifacts" / f"{STEM}.md").read_text(encoding="utf-8")
    assert "0원이 아니라 산정 불가" in md
    assert "기사상 likely allocation 합계 3,500억원" in md
    assert "공식 위탁액·약정액·dry powder 합계에서 제외" in md
