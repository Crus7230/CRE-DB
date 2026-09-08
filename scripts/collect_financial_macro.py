#!/usr/bin/env python
"""Collect official Korea/US financial macro history into the local authority DB."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.financial_macro import (
    fetch_ecos, fetch_nyfed, fetch_treasury, store_source_snapshot,
    ensure_series, utc_now, write_artifact,
)

DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ARTIFACTS = ROOT / "artifacts/financial-macro/raw"
DEFAULT_REPORT = ROOT / "artifacts/financial-macro/backfill-report.json"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env")


def load_env(path: Path) -> dict[str, str]:
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def collect(source: str, *, end_date: str, start_date: str | None, start_year: int, api_key: str, sleep_seconds: float):
    if source == "ecos":
        start_month = start_date[:7].replace("-", "") if start_date else None
        return "src_bok", "BOK_ECOS", fetch_ecos(api_key, end_date[:7].replace("-", ""), start_month=start_month, sleep_seconds=sleep_seconds)
    if source == "nyfed":
        return "src_ny_fed", "NY_FED_MARKETS", fetch_nyfed(end_date, start_date=start_date)
    if source == "treasury":
        return "src_us_treasury", "US_TREASURY_YIELD_CURVE", fetch_treasury(start_year, int(end_date[:4]), sleep_seconds=sleep_seconds)
    raise ValueError(source)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source", action="append", choices=("ecos", "nyfed", "treasury"))
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--start-date", type=date.fromisoformat, help="Rolling correction start for ECOS and NY Fed; history is retained")
    parser.add_argument("--treasury-start-year", type=int, default=1990)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    env = load_env(args.env)
    api_key = env.get("BOK_ECOS_API_KEY") or env.get("ECOS_API_KEY") or "sample"
    sources = args.source or ["ecos", "nyfed", "treasury"]
    retrieved_at = utc_now()
    report = {"status": "applied" if args.apply else "rollback_rehearsal", "retrievedAt": retrieved_at, "ecosAuth": "configured" if api_key != "sample" else "sample-pagination", "sources": {}}

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        feature = conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='financial_macro_schema_version'").fetchone()
        if not feature or feature[0] != "1.0.2":
            raise RuntimeError("financial macro feature 1.0.2 is required")
        ensure_series(conn)
        for source in sources:
            source_id, source_code, (observations, manifest) = collect(source, end_date=args.end_date, start_date=args.start_date.isoformat() if args.start_date else None, start_year=args.treasury_start_year, api_key=api_key, sleep_seconds=args.sleep)
            artifact, artifact_sha = write_artifact(args.artifacts, source_code, retrieved_at, manifest)
            stats = store_source_snapshot(conn, source_id, source_code, observations, artifact, artifact_sha, retrieved_at)
            periods = [o["period_start"] for o in observations]
            report["sources"][source] = {**stats, "minPeriod": min(periods) if periods else None, "maxPeriod": max(periods) if periods else None, "artifact": str(artifact.relative_to(ROOT)), "artifactSha256": artifact_sha}
        monthly = conn.execute("SELECT count(*) FROM v_financial_macro_monthly").fetchone()[0]
        report["monthlyRows"] = monthly
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
        report["persistedFinancialObservations"] = conn.execute("""SELECT count(*) FROM macro_observations o JOIN macro_series s ON s.macro_series_id=o.macro_series_id WHERE json_extract(s.metadata_json,'$.domain')='FINANCIAL_MARKETS'""").fetchone()[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
