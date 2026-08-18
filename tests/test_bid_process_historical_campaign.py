from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_backfill_bid_process.py"
SPEC = importlib.util.spec_from_file_location("bid_process_history", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


class BidProcessHistoricalCampaignTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = MOD.load_campaign_config(
            ROOT / "campaigns" / "backfill-2020-2024-bid-process.json"
        )
        self.policy = json.loads(
            (ROOT / self.config["geographyPolicy"]).read_text(encoding="utf-8")
        )

    def test_builds_five_year_month_partitions_with_year_scoped_identity(self) -> None:
        tasks = MOD.build_tasks(self.config, self.policy)

        self.assertEqual(3420, len(tasks))
        self.assertEqual({2020, 2021, 2022, 2023, 2024}, {task["year"] for task in tasks})
        first = tasks[0]
        last = tasks[-1]
        self.assertEqual("2020-01-01", first["start"])
        self.assertEqual("2025-01-01", last["end"])
        self.assertTrue(first["job_code"].startswith("BACKFILL_2020_BID_"))
        self.assertTrue(last["job_code"].startswith("BACKFILL_2024_BID_"))
        self.assertEqual(1, first["job_version"])
        self.assertEqual("bid-process-query-v1", first["query_version"])
        self.assertIn("after:2019-12-31 before:2020-02-01", first["query"])

    def test_month_filter_applies_to_every_year(self) -> None:
        tasks = MOD.build_tasks(self.config, self.policy, month=2, assets=["OFFICE"])

        self.assertEqual(15, len(tasks))
        self.assertTrue(all(task["start"].endswith("-02-01") for task in tasks))

    def test_rejects_non_candidates_only_campaign(self) -> None:
        invalid = dict(self.config, canonicalEventPolicy="AUTO_CREATE_EVENTS")

        with self.assertRaisesRegex(ValueError, "CANDIDATES_ONLY"):
            MOD.validate_campaign_config(invalid, self.policy)

    def test_rejects_invalid_year_range(self) -> None:
        invalid = dict(self.config, startYear=2025, endYear=2024)

        with self.assertRaisesRegex(ValueError, "startYear"):
            MOD.validate_campaign_config(invalid, self.policy)

    def test_summarizes_each_year_and_the_aggregate(self) -> None:
        rows = [
            {"year": 2020, "status": "COMPLETED", "discovered": 2, "inserted": 1, "updated": 0},
            {"year": 2020, "status": "SKIPPED_EXISTING", "discovered": 0, "inserted": 0, "updated": 0},
            {"year": 2021, "status": "FAILED", "discovered": 0, "inserted": 0, "updated": 0},
        ]

        payload = MOD.build_summary_payloads(self.config, self.policy, rows, generated_at="fixed")

        self.assertEqual(2, payload["years"][2020]["partitionCount"])
        self.assertEqual({"COMPLETED": 1, "SKIPPED_EXISTING": 1}, payload["years"][2020]["statusCounts"])
        self.assertEqual(3, payload["aggregate"]["partitionCount"])
        self.assertEqual(2, payload["aggregate"]["discovered"])
        self.assertEqual("CANDIDATES_ONLY_NO_AUTO_CANONICAL_EVENT", payload["aggregate"]["canonicalEventPolicy"])

    def test_dry_run_validates_without_creating_database_or_summary_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            missing_db = Path(td) / "missing.db"
            artifact_dir = Path(td) / "artifacts"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(ROOT / "campaigns" / "backfill-2020-2024-bid-process.json"),
                    "--db",
                    str(missing_db),
                    "--artifact-dir",
                    str(artifact_dir),
                    "--dry-run",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(3420, result["partitionCount"])
            self.assertEqual({"2020": 684, "2021": 684, "2022": 684, "2023": 684, "2024": 684}, result["byYear"])
            self.assertEqual("VALID", result["validation"])
            self.assertFalse(missing_db.exists())
            self.assertFalse(artifact_dir.exists())

    def test_2025_wrapper_retains_original_default_campaign(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/run_backfill_2025_bid_process.py", "--dry-run", "--db", "NUL"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(684, result["partitionCount"])
        self.assertEqual({"2025": 684}, result["byYear"])


if __name__ == "__main__":
    unittest.main()
