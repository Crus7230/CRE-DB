from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import ingest_partition, month_windows, parse_google_news_rss, render_google_query

CANDIDATES_ONLY_POLICY = "CANDIDATES_ONLY_NO_AUTO_CANONICAL_EVENT"
ASSET_TYPES = ("OFFICE", "HOTEL", "LOGISTICS", "DATA_CENTER")


def load_campaign_config(path: str | Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if "year" in config:
        config.setdefault("startYear", int(config["year"]))
        config.setdefault("endYear", int(config["year"]))
    config.setdefault("jobVersion", 1)
    config.setdefault("queryVersion", config.get("campaignVersion"))
    config.setdefault(
        "jobCodeTemplate",
        "BACKFILL_{year}_BID_{asset_type}_{region_group}_{bundle_code}",
    )
    return config


def validate_campaign_config(config: dict, policy: dict) -> None:
    required = (
        "campaignCode",
        "campaignVersion",
        "startYear",
        "endYear",
        "sourceCode",
        "categoryCode",
        "geographyPolicy",
        "assetQueries",
        "processBundles",
        "canonicalEventPolicy",
        "jobVersion",
        "queryVersion",
        "jobCodeTemplate",
    )
    missing = [key for key in required if key not in config or config[key] in (None, "")]
    if missing:
        raise ValueError("missing campaign fields: " + ", ".join(missing))
    start_year = int(config["startYear"])
    end_year = int(config["endYear"])
    if start_year > end_year:
        raise ValueError("startYear must be less than or equal to endYear")
    if not 1900 <= start_year <= 9998 or not 1900 <= end_year <= 9998:
        raise ValueError("startYear and endYear must be between 1900 and 9998")
    if config["canonicalEventPolicy"] != CANDIDATES_ONLY_POLICY:
        raise ValueError(f"canonicalEventPolicy must be {CANDIDATES_ONLY_POLICY}")
    if int(config["jobVersion"]) != 1:
        raise ValueError("jobVersion must be 1 (the current ingestion contract supports version 1)")
    if not config["assetQueries"] or not config["processBundles"]:
        raise ValueError("assetQueries and processBundles must not be empty")
    for asset_type in config["assetQueries"]:
        if asset_type not in policy.get("assetUsePolicies", {}):
            raise ValueError(f"geography policy is missing asset type {asset_type}")
        for group in policy["assetUsePolicies"][asset_type].get("includedGroups", []):
            if group not in policy.get("regionGroups", {}):
                raise ValueError(f"geography policy is missing region group {group}")


def build_tasks(
    config: dict,
    policy: dict,
    *,
    month: int | None = None,
    assets: list[str] | None = None,
) -> list[dict]:
    validate_campaign_config(config, policy)
    if month is not None and not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    selected_assets = assets or list(config["assetQueries"])
    unknown = [asset for asset in selected_assets if asset not in config["assetQueries"]]
    if unknown:
        raise ValueError("unknown asset types: " + ", ".join(unknown))

    tasks: list[dict] = []
    for year in range(int(config["startYear"]), int(config["endYear"]) + 1):
        windows = month_windows(year)
        if month is not None:
            windows = [windows[month - 1]]
        for asset_type in selected_assets:
            included_groups = policy["assetUsePolicies"][asset_type]["includedGroups"]
            for group in included_groups:
                region_query = "(" + " OR ".join(policy["regionGroups"][group]["terms"]) + ")"
                for bundle_code, process_query in config["processBundles"].items():
                    base = f"{config['assetQueries'][asset_type]} {process_query} {region_query}"
                    job_code = config["jobCodeTemplate"].format(
                        year=year,
                        asset_type=asset_type,
                        region_group=group,
                        bundle_code=bundle_code,
                    )
                    for start, end in windows:
                        tasks.append(
                            {
                                "year": year,
                                "asset_type": asset_type,
                                "region_group": group,
                                "bundle": bundle_code,
                                "job_code": job_code,
                                "job_version": int(config["jobVersion"]),
                                "query_version": config["queryVersion"],
                                "start": start,
                                "end": end,
                                "scheduled": f"{start}T00:00:00Z",
                                "query": render_google_query(base, start, end),
                                "skip": False,
                            }
                        )
    return tasks


def completed(db: Path, task: dict) -> bool:
    if not db.exists() or not db.is_file():
        return False
    uri = db.resolve().as_uri() + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error:
        return False
    con.execute("PRAGMA busy_timeout=5000")
    try:
        return (
            con.execute(
                """SELECT 1 FROM collection_runs cr
                   JOIN collection_jobs j ON j.job_id=cr.job_id
                   WHERE j.job_code=? AND j.job_version=? AND cr.scheduled_for=?
                     AND cr.query_rendered=? AND cr.status_code='COMPLETED' LIMIT 1""",
                (task["job_code"], task["job_version"], task["scheduled"], task["query"]),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False
    finally:
        con.close()


def mark_completed_tasks(tasks: list[dict], db: Path) -> None:
    for task in tasks:
        task["skip"] = completed(db, task)


def fetch(task: dict, attempts: int = 5, request_delay: float = 0.75) -> dict:
    if task["skip"]:
        return {**task, "documents": None, "fetch_status": "SKIPPED_EXISTING"}
    params = {"q": task["query"], "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    error = None
    for attempt in range(1, attempts + 1):
        try:
            time.sleep(max(0.0, request_delay))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Hermes CRE research"})
            raw = urllib.request.urlopen(req, timeout=45).read()
            start = datetime.fromisoformat(task["start"]).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(task["end"]).replace(tzinfo=timezone.utc)
            documents = parse_google_news_rss(raw, start=start, end=end)
            return {**task, "documents": documents, "fetch_status": "OK"}
        except Exception as exc:  # retained in the campaign coverage summary
            error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                # Google News intermittently answers large historical campaigns
                # with 429/503. Long backoff avoids converting throttling into a
                # false coverage gap.
                time.sleep(min(60, 5 * (2 ** (attempt - 1))))
    return {**task, "documents": [], "fetch_status": "FAILED", "error": error}


def _summary(config: dict, policy: dict, rows: list[dict], generated_at: str, *, year: int | None) -> dict:
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    payload = {
        "campaign": config["campaignCode"],
        "campaignVersion": config["campaignVersion"],
        "queryVersion": config["queryVersion"],
        "jobVersion": int(config["jobVersion"]),
        "geographyPolicyVersion": policy["policyVersion"],
        "canonicalEventPolicy": config["canonicalEventPolicy"],
        "generatedAt": generated_at,
        "partitionCount": len(rows),
        "statusCounts": status_counts,
        "discovered": sum(row.get("discovered", 0) for row in rows),
        "inserted": sum(row.get("inserted", 0) for row in rows),
        "updated": sum(row.get("updated", 0) for row in rows),
        "saturatedPartitions": sum(bool(row.get("saturated")) for row in rows),
        "partitions": rows,
    }
    if year is not None:
        payload["year"] = year
    else:
        payload["startYear"] = int(config["startYear"])
        payload["endYear"] = int(config["endYear"])
    return payload


def build_summary_payloads(
    config: dict,
    policy: dict,
    rows: list[dict],
    *,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    ordered = sorted(rows, key=lambda row: (row["year"], row.get("asset_type", ""), row.get("region_group", ""), row.get("bundle", ""), row.get("start", "")))
    years = {
        year: _summary(config, policy, [row for row in ordered if row["year"] == year], generated_at, year=year)
        for year in range(int(config["startYear"]), int(config["endYear"]) + 1)
    }
    return {"years": years, "aggregate": _summary(config, policy, ordered, generated_at, year=None)}


def write_summary_payloads(payloads: dict, artifact_dir: Path, config: dict) -> dict:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for year, payload in payloads["years"].items():
        path = artifact_dir / f"backfill-{year}-bid-process-summary.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths[str(year)] = str(path)
    aggregate_name = (
        f"backfill-{int(config['startYear'])}-bid-process-summary.json"
        if int(config["startYear"]) == int(config["endYear"])
        else f"backfill-{int(config['startYear'])}-{int(config['endYear'])}-bid-process-summary.json"
    )
    aggregate_path = artifact_dir / aggregate_name
    # For a single year, the aggregate is the same named deliverable as the annual summary.
    aggregate_path.write_text(json.dumps(payloads["aggregate"], ensure_ascii=False, indent=2), encoding="utf-8")
    paths["aggregate"] = str(aggregate_path)
    return paths


def dry_run_payload(tasks: list[dict], config: dict, db: Path) -> dict:
    # Read-only resume inspection: a missing DB remains missing.
    mark_completed_tasks(tasks, db)
    by_year = {str(year): 0 for year in range(int(config["startYear"]), int(config["endYear"]) + 1)}
    by_asset: dict[str, int] = {}
    for task in tasks:
        by_year[str(task["year"])] += 1
        by_asset[task["asset_type"]] = by_asset.get(task["asset_type"], 0) + 1
    return {
        "validation": "VALID",
        "campaign": config["campaignCode"],
        "campaignVersion": config["campaignVersion"],
        "queryVersion": config["queryVersion"],
        "jobVersion": int(config["jobVersion"]),
        "canonicalEventPolicy": config["canonicalEventPolicy"],
        "partitionCount": len(tasks),
        "byYear": by_year,
        "byAsset": by_asset,
        "alreadyCompleted": sum(task["skip"] for task in tasks),
    }


def main(argv: list[str] | None = None, *, default_config: str = "campaigns/backfill-2020-2024-bid-process.json") -> None:
    parser = argparse.ArgumentParser(description="Run resumable historical asset-use x region x bid-process Google News campaign")
    parser.add_argument("--db", default="data/market.db")
    parser.add_argument("--config", default=default_config)
    parser.add_argument("--artifact-dir", default="artifacts")
    parser.add_argument("--asset", action="append", choices=ASSET_TYPES)
    parser.add_argument("--month", type=int)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--request-delay", type=float, default=0.75)
    parser.add_argument("--dry-run", action="store_true", help="validate and plan only; performs no network calls or writes")
    args = parser.parse_args(argv)

    db = (ROOT / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db)
    config_path = (ROOT / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    artifact_dir = (ROOT / args.artifact_dir).resolve() if not Path(args.artifact_dir).is_absolute() else Path(args.artifact_dir)
    config = load_campaign_config(config_path)
    policy_path = (ROOT / config["geographyPolicy"]).resolve()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    try:
        tasks = build_tasks(config, policy, month=args.month, assets=args.asset)
    except ValueError as exc:
        parser.error(str(exc))

    if args.dry_run:
        print(json.dumps(dry_run_payload(tasks, config, db), ensure_ascii=False))
        return

    mark_completed_tasks(tasks, db)
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(fetch, task, 5, args.request_delay) for task in tasks]
        for future in as_completed(futures):
            item = future.result()
            row = {key: item[key] for key in ("year", "asset_type", "region_group", "bundle", "start", "end")}
            if item["fetch_status"] == "SKIPPED_EXISTING":
                row.update({"status": "SKIPPED_EXISTING", "discovered": 0, "inserted": 0, "updated": 0})
            elif item["fetch_status"] == "FAILED":
                row.update({"status": "FAILED", "error": item.get("error"), "discovered": 0, "inserted": 0, "updated": 0})
            else:
                result = ingest_partition(
                    db_path=db,
                    source_code=config["sourceCode"],
                    job_code=item["job_code"],
                    category_code=config["categoryCode"],
                    window_start=item["scheduled"],
                    window_end=f"{item['end']}T00:00:00Z",
                    query_rendered=item["query"],
                    documents=item["documents"],
                    runner_version=config["campaignVersion"],
                )
                row.update(
                    {
                        "status": "SKIPPED_EXISTING" if result.skipped_existing_run else "COMPLETED",
                        "discovered": result.discovered_count,
                        "inserted": result.inserted_count,
                        "updated": result.updated_count,
                        "saturated": result.discovered_count >= int(config.get("saturationResultCount", 100)),
                        "run_id": result.run_id,
                    }
                )
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

    payloads = build_summary_payloads(config, policy, rows)
    paths = write_summary_payloads(payloads, artifact_dir, config)
    aggregate = payloads["aggregate"]
    print(
        json.dumps(
            {
                key: aggregate[key]
                for key in ("partitionCount", "statusCounts", "discovered", "inserted", "updated", "saturatedPartitions")
            }
            | {"summaries": paths},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
