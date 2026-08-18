import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BackfillCliTest(unittest.TestCase):
    def test_script_can_import_project_modules_when_launched_by_path(self):
        completed = subprocess.run(
            [sys.executable, "scripts/run_backfill_2025_rss.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Run resumable 2025", completed.stdout)


    def test_dart_script_can_import_project_modules_when_launched_by_path(self):
        completed = subprocess.run(
            [sys.executable, "scripts/run_backfill_2025_dart_sale.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("OpenDART sale", completed.stdout)


    def test_molit_script_can_import_project_modules_when_launched_by_path(self):
        completed = subprocess.run(
            [sys.executable, "scripts/run_backfill_2025_molit_seoul.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("MOLIT Seoul", completed.stdout)


    def test_molit_capital_script_can_import_project_modules_when_launched_by_path(self):
        completed = subprocess.run(
            [sys.executable, "scripts/run_backfill_2025_molit_capital.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("MOLIT Incheon/Gyeonggi", completed.stdout)


if __name__ == "__main__":
    unittest.main()
