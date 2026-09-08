import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STEM = "manager-by-manager-institutional-lp-fund-report-20260816"


def test_manager_chapter_report_reconciles_programs_and_preserves_amount_semantics():
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "report_manager_lp_fund_chapters.py")],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    payload = json.loads((ROOT / "artifacts" / f"{STEM}.json").read_text(encoding="utf-8"))
    assert payload["manager_count"] == 8
    managers = {x["manager_name"]: x for x in payload["chapters"]}

    woori = managers["우리글로벌자산운용"]
    assert woori["summary"]["program_count"] == 1
    assert woori["summary"]["target_fund_size_krw"] == "90000000000"
    assert woori["summary"]["official_track_cap_krw"] == "27000000000"

    capstone = managers["캡스톤자산운용"]
    assert capstone["summary"]["program_count"] == 2
    assert capstone["summary"]["likely_reported_allocation_krw"] == "130000000000"

    coolidge = managers["쿨리지코너인베스트먼트"]
    assert coolidge["summary"]["program_count"] == 2
    assert coolidge["summary"]["target_fund_size_krw"] == "37500000000"
    assert coolidge["summary"]["selection_requested_or_reported_krw"] == "30000000000"

    assert all(x["summary"]["verified_commitment_krw"] is None for x in managers.values())
    assert all(x["summary"]["verified_available_krw"] is None for x in managers.values())
    assert payload["global_guard"]["selection_vehicle_rows"] == 0
    assert payload["global_guard"]["deployment_rows"] == 0
    assert payload["global_guard"]["source_balance_rows"] == 0

    md = (ROOT / "artifacts" / f"{STEM}.md").read_text(encoding="utf-8")
    assert "## 1. 우리글로벌자산운용" in md
    assert "## 2. 캡스톤자산운용" in md
    assert "## 7. 쿨리지코너인베스트먼트" in md
    assert "운용사당 상한 ≤1,000억원" in md
    assert "track 기관재원 ≤2,000억원; 운용사당 상한 ≤500억원" in md
    assert "company dry powder = NULL / INSUFFICIENT_EVIDENCE" in md
