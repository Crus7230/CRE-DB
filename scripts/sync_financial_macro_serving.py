#!/usr/bin/env python
"""Publish compact financial macro series/monthly data from Local SQLite to personal Supabase."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
DEFAULT_REPORT = ROOT / "artifacts/financial-macro/supabase-sync-report.json"
DOTENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
SERIES_COLUMNS = (
    "macro_series_id", "series_code", "series_name_ko", "metric_code", "source_id",
    "external_series_key", "frequency_code", "unit_code", "region_id", "asset_class_id",
    "adjustment_code", "aggregation_code", "definition_text", "valid_from", "valid_to",
    "is_active", "metadata_json",
)
MONTHLY_COLUMNS = (
    "series_code", "source_id", "region_id", "observation_month", "numeric_value",
    "observation_count", "aggregation_code", "unit_code", "source_vintage_at", "published_at",
)


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = DOTENV_RE.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip().strip("\"'")
    return values


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def local_payload(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        version = conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='financial_macro_schema_version'").fetchone()
        if not version or version[0] != "1.0.2":
            raise RuntimeError("Local financial macro feature 1.0.2 is required")
        series = conn.execute(
            f"SELECT {','.join(SERIES_COLUMNS)} FROM macro_series WHERE json_extract(metadata_json,'$.domain')='FINANCIAL_MARKETS' ORDER BY series_code"
        ).fetchall()
        published_at = utc_now()
        monthly = [tuple(r) + (published_at,) for r in conn.execute(
            """SELECT series_code,source_id,region_id,observation_month,numeric_value,
                      observation_count,aggregation_code,unit_code,source_vintage_at
                 FROM v_financial_macro_monthly ORDER BY series_code,observation_month"""
        )]
        summary = {}
        for row in monthly:
            code = row[0]
            item = summary.setdefault(code, {"rows": 0, "minMonth": row[3], "maxMonth": row[3], "latestValue": row[4], "sum": 0.0})
            item["rows"] += 1
            item["minMonth"] = min(item["minMonth"], row[3])
            if row[3] >= item["maxMonth"]:
                item["maxMonth"] = row[3]
                item["latestValue"] = row[4]
            item["sum"] += float(row[4])
        for item in summary.values():
            item["sum"] = round(item["sum"], 10)
        return {"series": series, "monthly": monthly, "summary": summary}
    finally:
        conn.close()


def copy_rows(conn, table: str, columns: tuple[str, ...], rows: list[tuple]) -> None:
    with conn.cursor().copy(f"COPY {table} ({','.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def remote_summary(conn) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT series_code,count(*),min(observation_month),max(observation_month),sum(numeric_value)
             FROM market_intelligence.financial_macro_monthly_serving GROUP BY series_code ORDER BY series_code"""
    ).fetchall()
    result = {}
    for code, count, min_month, max_month, total in rows:
        latest = conn.execute(
            "SELECT numeric_value FROM market_intelligence.financial_macro_monthly_serving WHERE series_code=%s AND observation_month=%s",
            (code, max_month),
        ).fetchone()[0]
        result[code] = {"rows": count, "minMonth": min_month, "maxMonth": max_month, "latestValue": latest, "sum": round(float(total), 10)}
    return result


def summaries_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if expected.keys() != actual.keys():
        return False
    for code in expected:
        for key in ("rows", "minMonth", "maxMonth"):
            if expected[code][key] != actual[code][key]:
                return False
        for key in ("latestValue", "sum"):
            if abs(float(expected[code][key]) - float(actual[code][key])) > 1e-8:
                return False
    return True


def run(db: Path, env_path: Path, apply: bool) -> dict[str, Any]:
    import psycopg
    payload = local_payload(db)
    env = load_env(env_path)
    dsn = env.get("SUPABASE_DB_URL") or env.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("SUPABASE_DB_URL or DATABASE_URL is required")
    with psycopg.connect(dsn, autocommit=False) as conn:
        version = conn.execute("SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='financial_macro_schema_version'").fetchone()
        if not version or version[0] != "1.0.2":
            raise RuntimeError("Supabase financial macro feature 1.0.2 is required")
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('financial_macro_serving_sync'))")
        for row in payload["series"]:
            placeholders = ",".join(["%s"] * len(SERIES_COLUMNS))
            updates = ",".join(f"{c}=excluded.{c}" for c in SERIES_COLUMNS if c not in ("macro_series_id", "series_code"))
            conn.execute(
                f"INSERT INTO market_intelligence.macro_series ({','.join(SERIES_COLUMNS)}) VALUES({placeholders}) ON CONFLICT(series_code) DO UPDATE SET {updates}",
                row,
            )
        conn.execute("TRUNCATE market_intelligence.financial_macro_monthly_serving")
        copy_rows(conn, "market_intelligence.financial_macro_monthly_serving", MONTHLY_COLUMNS, payload["monthly"])
        actual = remote_summary(conn)
        if not summaries_match(payload["summary"], actual):
            raise RuntimeError("financial macro Supabase readback mismatch")
        if apply:
            conn.commit()
        else:
            conn.rollback()
        persisted = conn.execute("SELECT count(*) FROM market_intelligence.financial_macro_monthly_serving").fetchone()[0]
        db_bytes = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    return {
        "status": "applied" if apply else "rollback_rehearsal",
        "staged": {"series": len(payload["series"]), "monthlyRows": len(payload["monthly"])},
        "verification": {"status": "passed", "series": actual},
        "persistedMonthlyRows": persisted,
        "databaseBytes": db_bytes,
        "completedAt": utc_now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = run(args.db, args.env, args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**result, "report": str(args.report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
