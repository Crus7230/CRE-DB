from __future__ import annotations

from dataclasses import asdict, is_dataclass
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import derive_molit_seoul_monthly_macro, extract_title_candidates
from collector.post_collection_relationships import reconcile_relationships
from collector.sale_process_candidates import extract_and_queue_bid_process_candidates
from collector.transaction_scope import apply_molit_transaction_scope


def pack(value):
    return asdict(value) if is_dataclass(value) else str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run idempotent post-collection processing")
    parser.add_argument("--db", default="data/market.db")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--campaign-version", default="2026.H1.1")
    parser.add_argument("--artifact", default="artifacts/backfill-2026-h1-post-processing-summary.json")
    args = parser.parse_args()
    db = Path(args.db)
    output = {
        "extraction": pack(extract_title_candidates(db_path=db, year=args.year, pipeline_version="TITLE_SNIPPET_V1")),
        "molit_scope": pack(apply_molit_transaction_scope(db_path=db)),
        "bid_process_monthly": pack(extract_and_queue_bid_process_candidates(
            db_path=db,
            geography_policy_path=ROOT / "config" / "asset-use-geography-policies.json",
            collection_runner_version=args.campaign_version,
            pipeline_version="BID_PROCESS_TITLE_SNIPPET_V3",
        )),
        "bid_process_recovery": pack(extract_and_queue_bid_process_candidates(
            db_path=db,
            geography_policy_path=ROOT / "config" / "asset-use-geography-policies.json",
            collection_runner_version=f"{args.campaign_version}-weekly-recovery",
            pipeline_version="BID_PROCESS_TITLE_SNIPPET_V3",
        )),
        "macro": pack(derive_molit_seoul_monthly_macro(db_path=db, year=args.year)),
        "relationships": pack(reconcile_relationships(db, allow_live=True)),
    }
    artifact = Path(args.artifact)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
