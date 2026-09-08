from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_bid_process_candidates.py"
SPEC = importlib.util.spec_from_file_location("extract_bid_process_candidates_cli", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


class ExtractBidProcessCandidatesCliTest(unittest.TestCase):
    def test_default_scope_covers_2020_through_2026_ytd(self) -> None:
        args = MOD.build_parser().parse_args([])
        runner_versions = args.runner_versions or list(MOD.DEFAULT_RUNNER_VERSIONS)

        self.assertEqual(
            [
                "2020-2024-bid-process-v1",
                "2025-bid-process-v1",
                "2026.H1.1",
                "2026.H1.1-weekly-recovery",
                "2026.H2.1",
                "2026.H2.1-weekly-recovery",
            ],
            runner_versions,
        )
        self.assertEqual(ROOT / "artifacts" / "bid-process-ytd-candidates.json", args.output)

    def test_explicit_runner_and_output_override_defaults(self) -> None:
        output = ROOT / "artifacts" / "custom-candidates.json"
        args = MOD.build_parser().parse_args(
            [
                "--runner-version",
                "custom-runner",
                "--output",
                str(output),
            ]
        )

        self.assertEqual(["custom-runner"], args.runner_versions)
        self.assertEqual(output, args.output)


if __name__ == "__main__":
    unittest.main()
