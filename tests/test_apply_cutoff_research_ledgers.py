from collections import Counter
from pathlib import Path

from scripts.apply_cutoff_research_ledgers import parse_non_sale, parse_sales

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "research" / "2026-08-19"


def test_cutoff_sale_ledger_has_fourteen_processes():
    rows = parse_sales(ARTIFACT / "korea_cre_sale_process_manifest_candidate_2026-08-19.json")
    assert len(rows) == 14
    assert all(row["category"] == "cat_sale" for row in rows)
    assert all(row["urls"] for row in rows)


def test_cutoff_non_sale_ledger_preserves_all_six_areas():
    rows = parse_non_sale(ARTIFACT / "korea_cre_non_sale_candidates_2026-08-19.md")
    assert len(rows) == 33
    counts = Counter(row["category"] for row in rows)
    assert counts == {
        "cat_lease": 10,
        "cat_supply": 10,
        "cat_permit": 4,
        "cat_pf": 4,
        "cat_invest": 5,
    }
    assert all(row["stage"] and row["urls"] for row in rows)
