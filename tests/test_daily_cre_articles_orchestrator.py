from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from operations.hermes import daily_cre_articles as runner  # noqa: E402


def completed(summary: dict | None = None, code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, json.dumps(summary or {}), "failure" if code else "")


class DailyCreArticlesTests(unittest.TestCase):
    def test_import_does_not_resolve_runtime_or_run_pipeline(self) -> None:
        spec = importlib.util.spec_from_file_location("daily_cre_articles_import_test", runner.__file__)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        with patch("shutil.which") as which, patch("subprocess.run") as run:
            spec.loader.exec_module(module)
        which.assert_not_called()
        run.assert_not_called()

    def test_uv_falls_back_to_hermes_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            fallback = local / "hermes" / "bin" / "uv.exe"
            fallback.parent.mkdir(parents=True)
            fallback.touch()
            with patch.object(runner.shutil, "which", return_value=None):
                self.assertEqual(runner.resolve_uv(local), str(fallback))
            with patch.object(runner.shutil, "which", return_value="path-uv"):
                self.assertEqual(runner.resolve_uv(local), "path-uv")

    def test_missing_runtime_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner.shutil, "which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "LOCALAPPDATA/hermes/bin"):
                    runner.resolve_uv(Path(directory))

    def run_fake_pipeline(self, results: list[subprocess.CompletedProcess[str]]) -> tuple[dict, list, str]:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "logs" / "latest.log"
            with patch.object(runner, "run_step", side_effect=results) as run:
                report = runner.run_pipeline(
                    uv="test-uv", target_date=date(2026, 8, 31), log_path=log,
                )
            return report, run.call_args_list, log.read_text(encoding="utf-8")

    def test_shared_two_day_window_and_complete_order(self) -> None:
        report, calls, log = self.run_fake_pipeline([
            completed({"status": "completed"}),
            completed({"selected": 150, "completed": 150, "failed": 0}),
            completed({"status": "applied", "canonicalEventsBefore": 16, "canonicalEventsAfter": 16}),
        ])
        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual(report["exit_code"], 0)
        commands = [call.args[0] for call in calls]
        self.assertIn("scripts/collect_daily_rss_supabase.py", commands[0])
        self.assertEqual(commands[0][-4:], ["--date", "2026-08-31", "--lookback-days", "2"])
        self.assertIn("scripts/enrich_document_content.py", commands[1])
        self.assertEqual(commands[2][-5:], ["--from-date", "2026-08-30", "--to-date", "2026-09-01", "--apply"])
        self.assertIn("PIPELINE_SUMMARY", log)
        self.assertEqual(json.loads(log.splitlines()[-1])["status"], "COMPLETED")

    def test_item_failures_are_partial_and_do_not_skip_classification(self) -> None:
        report, calls, log = self.run_fake_pipeline([
            completed(), completed({"selected": 150, "completed": 110, "failed": 40}), completed(),
        ])
        self.assertEqual(len(calls), 3)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["steps"]["classification"]["status"], "COMPLETED")
        self.assertIn("ENRICHMENT_ITEMS_FAILED:40", report["partial_reasons"])
        self.assertIn('"status": "PARTIAL"', log)

    def test_failed_enrichment_still_classifies_but_fails_pipeline(self) -> None:
        report, calls, _ = self.run_fake_pipeline([completed(), completed(code=4), completed()])
        self.assertEqual(len(calls), 3)
        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(report["exit_code"], 4)
        self.assertEqual(report["steps"]["classification"]["status"], "COMPLETED")

    def test_classification_failure_takes_precedence_over_partial(self) -> None:
        report, calls, _ = self.run_fake_pipeline([
            completed(), completed({"selected": 150, "completed": 110, "failed": 40}), completed(code=3),
        ])
        self.assertEqual(len(calls), 3)
        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(report["exit_code"], 3)

    def test_collector_failure_stops_remaining_steps(self) -> None:
        report, calls, _ = self.run_fake_pipeline([completed(code=2)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(report["exit_code"], 2)
        self.assertNotIn("classification", report["steps"])

    def test_missing_summary_is_not_reported_as_full_success(self) -> None:
        report, _, _ = self.run_fake_pipeline([completed(), completed(), completed()])
        self.assertEqual(report["status"], "PARTIAL")
        self.assertIn("ENRICHMENT_SUMMARY_MISSING", report["partial_reasons"])

    def test_timeout_is_recordable_process_failure(self) -> None:
        with patch.object(runner.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 5, output=b"partial")):
            result = runner.run_step(["python", "test.py"], 5, uv="test-uv")
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial")

    def test_invalid_lookback_is_rejected_before_execution(self) -> None:
        with self.assertRaises(ValueError):
            runner.run_pipeline(uv="test-uv", target_date=date(2026, 8, 31), lookback_days=0)


if __name__ == "__main__":
    unittest.main()
