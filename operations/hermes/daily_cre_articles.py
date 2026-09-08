"""Canonical daily RSS entrypoint: collect, enrich, then classify review candidates.

Importing this module is side-effect free. Scheduler launchers should call this
file rather than copying the pipeline, so deployed jobs follow repository fixes.
Item-level enrichment failures are PARTIAL (exit 0); failed pipeline processes
are FAILED (nonzero). Classification does not depend on full article access.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
LOG = LOCAL_APP_DATA / "hermes" / "cron" / "output" / "cre-daily-articles-latest.log"
SEOUL = ZoneInfo("Asia/Seoul")


def resolve_uv(local_app_data: Path | None = None) -> str:
    executable = shutil.which("uv")
    if executable:
        return executable
    fallback = (local_app_data or LOCAL_APP_DATA) / "hermes" / "bin" / "uv.exe"
    if fallback.is_file():
        return str(fallback)
    raise RuntimeError("uv executable was not found on PATH or in LOCALAPPDATA/hermes/bin")


def run_step(
    arguments: list[str], timeout: int, *, uv: str, root: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    command = [uv, "run", *arguments]
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    try:
        return subprocess.run(
            command, cwd=root, text=True, encoding="utf-8", errors="replace",
            env=environment, capture_output=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(command, 124, output, f"step timed out after {timeout}s")
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, "", f"{type(exc).__name__}: {exc}")


def last_json_summary(output: str) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def run_pipeline(
    *, uv: str, target_date: date, lookback_days: int = 2,
    root: Path = ROOT, log_path: Path = LOG,
) -> dict[str, Any]:
    if not 1 <= lookback_days <= 7:
        raise ValueError("lookback_days must be between 1 and 7")
    first_date = target_date - timedelta(days=lookback_days - 1)
    end_date = target_date + timedelta(days=1)
    report: dict[str, Any] = {
        "status": "RUNNING", "exit_code": 0,
        "target_date": target_date.isoformat(), "lookback_days": lookback_days,
        "classification_from_date": first_date.isoformat(),
        "classification_to_date_exclusive": end_date.isoformat(),
        "started_at": datetime.now(SEOUL).isoformat(),
        "partial_reasons": [], "steps": {},
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8")

    def execute(name: str, arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        result = run_step(arguments, timeout, uv=uv, root=root)
        summary = last_json_summary(result.stdout)
        report["steps"][name] = {
            "status": "COMPLETED" if result.returncode == 0 else "FAILED",
            "exit_code": result.returncode,
            "completed_at": datetime.now(SEOUL).isoformat(), "summary": summary,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{name.upper()}\nexit_code={result.returncode}\n{result.stdout}\n")
            if result.stderr:
                handle.write("STDERR\n" + result.stderr + "\n")
        return result

    collector = execute("collector", [
        "--with", "psycopg[binary]",
        "python", "scripts/collect_daily_rss_supabase.py",
        "--date", target_date.isoformat(), "--lookback-days", str(lookback_days),
    ], 1200)
    if collector.returncode == 0:
        enrichment = execute("enrichment", [
            "--with", "psycopg[binary]", "--with", "googlenewsdecoder",
            "--with", "trafilatura", "python", "scripts/enrich_document_content.py",
            "--types", "RSS_ITEM", "--limit", "150",
        ], 1800)
        enrichment_summary = report["steps"]["enrichment"]["summary"] or {}
        if enrichment.returncode == 0:
            failed = enrichment_summary.get("failed")
            if isinstance(failed, int) and failed > 0:
                report["partial_reasons"].append(f"ENRICHMENT_ITEMS_FAILED:{failed}")
            elif not isinstance(failed, int):
                report["partial_reasons"].append("ENRICHMENT_SUMMARY_MISSING")
            if enrichment_summary.get("skipped_concurrent"):
                report["partial_reasons"].append("ENRICHMENT_CONCURRENT_RUN")
            if report["partial_reasons"]:
                report["steps"]["enrichment"]["status"] = "PARTIAL"

        # Classification uses title/snippet evidence even if body extraction
        # fails. Pin both stages to the same KST window across midnight; include
        # the previous day for delayed articles and idempotent catch-up.
        classification = execute("classification", [
            "--with", "psycopg[binary]",
            "python", "scripts/process_daily_rss_classifications.py",
            "--from-date", first_date.isoformat(), "--to-date", end_date.isoformat(),
            "--apply",
        ], 1200)
        report["exit_code"] = classification.returncode or enrichment.returncode
    else:
        report["exit_code"] = collector.returncode

    report["status"] = (
        "FAILED" if report["exit_code"] else
        "PARTIAL" if report["partial_reasons"] else "COMPLETED"
    )
    report["completed_at"] = datetime.now(SEOUL).isoformat()
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\nPIPELINE_SUMMARY\n" + json.dumps(report, ensure_ascii=False) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, help="KST collection date; defaults to today")
    parser.add_argument("--lookback-days", type=int, choices=range(1, 8), default=2)
    args = parser.parse_args(argv)
    try:
        executable = resolve_uv()
    except RuntimeError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        return 127
    report = run_pipeline(
        uv=executable, target_date=args.date or datetime.now(SEOUL).date(),
        lookback_days=args.lookback_days,
    )
    print(json.dumps(report, ensure_ascii=False))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
