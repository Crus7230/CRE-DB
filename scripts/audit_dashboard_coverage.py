from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

TABLES = [
    "organizations", "event_participants", "event_assets", "event_projects",
    "event_mentions", "event_mention_links", "organization_property_occupancies",
    "market_universe_snapshots", "market_universe_members",
    "organization_industry_assignments", "industry_nodes", "lp_mandates",
    "lp_mandate_tracks", "lp_mandate_selections", "lp_mandate_amounts",
    "lp_mandate_selection_vehicles", "lp_mandate_deployments", "sale_processes",
    "sale_process_relations", "bid_rounds", "bidder_participations",
    "bid_submissions", "bid_decisions", "bid_funding_components",
    "transaction_milestones",
]


def scalar(con: sqlite3.Connection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/market.db")
    args = parser.parse_args()
    con = sqlite3.connect(Path(args.db))
    con.row_factory = sqlite3.Row
    report = {name: scalar(con, f"SELECT count(*) FROM {name}") for name in TABLES}
    report["docs_by_type"] = [dict(row) for row in con.execute(
        "SELECT document_type,count(*) AS count FROM source_documents GROUP BY document_type ORDER BY count DESC"
    )]
    report["participant_roles"] = [dict(row) for row in con.execute(
        "SELECT role_code,count(*) AS count FROM event_participants GROUP BY role_code ORDER BY count DESC"
    )]
    report["company_timeline"] = scalar(con, "SELECT count(*) FROM v_company_real_estate_timeline")
    report["company_universe_current"] = scalar(con, "SELECT count(*) FROM v_company_universe_current")
    report["latest_document_date"] = con.execute(
        "SELECT max(substr(published_at,1,10)) FROM document_versions"
    ).fetchone()[0]
    report["latest_transaction_date"] = con.execute(
        "SELECT max(json_extract(metadata_json,'$.deal_date')) FROM document_versions "
        "WHERE json_extract(metadata_json,'$.source_type')='MOLIT_RTMS_NRG_TRADE'"
    ).fetchone()[0]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()


if __name__ == "__main__":
    main()
