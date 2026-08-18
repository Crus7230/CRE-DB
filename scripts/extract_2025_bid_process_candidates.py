from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.sale_process_candidates import extract_and_queue_bid_process_candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/market.db")
    parser.add_argument("--policy", default="config/asset-use-geography-policies.json")
    parser.add_argument("--runner-version", default="2025-bid-process-v1")
    parser.add_argument("--pipeline-version", default="BID_PROCESS_TITLE_SNIPPET_V3")
    args = parser.parse_args()
    db = Path(args.db) if Path(args.db).is_absolute() else ROOT / args.db
    policy = Path(args.policy) if Path(args.policy).is_absolute() else ROOT / args.policy
    result = extract_and_queue_bid_process_candidates(
        db_path=db,
        geography_policy_path=policy,
        collection_runner_version=args.runner_version,
        pipeline_version=args.pipeline_version,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
