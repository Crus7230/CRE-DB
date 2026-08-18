from __future__ import annotations

import ast
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONTRACT = {
    "collector/backfill_2025.py": {"ingest_partition", "extract_title_candidates"},
    "collector/approved_sale_manifest.py": {"import_manifest"},
    "collector/approved_lp_mandate_manifest.py": {"import_manifest"},
    "collector/research_candidate_manifest.py": {"import_candidate"},
    "collector/sale_process_candidates.py": {"extract_and_queue_bid_process_candidates"},
    "collector/transaction_scope.py": {"apply_molit_transaction_scope"},
}


def called_names(function: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


class RelationshipHookContractTest(unittest.TestCase):
    def _empty_db(self, path: Path) -> None:
        con = sqlite3.connect(path)
        con.executescript((ROOT / 'db/v2/schema.sql').read_text(encoding='utf-8'))
        con.executescript((ROOT / 'db/v2/seed.sql').read_text(encoding='utf-8'))
        con.close()

    def test_every_authoritative_ingest_or_extraction_entrypoint_reconciles_relationships(self) -> None:
        missing: list[str] = []
        for relative, functions in CONTRACT.items():
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            definitions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
            for function_name in functions:
                self.assertIn(function_name, definitions, f"missing entrypoint {relative}:{function_name}")
                if "reconcile_relationships" not in called_names(definitions[function_name]):
                    missing.append(f"{relative}:{function_name}")
        self.assertEqual([], missing, "post-collection relationship hook missing")

    def test_zero_row_extraction_still_invokes_relationship_hook(self) -> None:
        from collector import backfill_2025
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'empty.db'; self._empty_db(db)
            with mock.patch.object(backfill_2025, 'reconcile_relationships') as hook:
                result = backfill_2025.extract_title_candidates(
                    db_path=db, year=2025, pipeline_version='runtime-hook-test',
                )
            self.assertEqual(0, result.inserted_extraction_runs)
            hook.assert_called_once_with(db, allow_live=True)

    def test_zero_scope_decisions_still_invoke_relationship_hook(self) -> None:
        from collector import transaction_scope
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'empty.db'; self._empty_db(db)
            with mock.patch.object(transaction_scope, 'reconcile_relationships') as hook:
                result = transaction_scope.apply_molit_transaction_scope(db_path=db)
            self.assertEqual(0, result.evaluated)
            hook.assert_called_once_with(db, allow_live=True)


if __name__ == "__main__":
    unittest.main()
