from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('dart_history',ROOT/'scripts'/'run_backfill_dart_sale.py')
MOD=importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


class DartHistoricalCampaignTest(unittest.TestCase):
    def test_builds_five_year_monthly_windows(self):
        rows=MOD.campaign_windows(2020,2024)
        self.assertEqual(60,len(rows))
        self.assertEqual((2020,'2020-01-01','2020-02-01'),rows[0])
        self.assertEqual((2024,'2024-12-01','2025-01-01'),rows[-1])

    def test_year_scoped_identity(self):
        self.assertEqual('BACKFILL_2022_OPENDART_SALE_V3',MOD.job_code(2022))
        self.assertEqual('backfill-2022-dart-sale-v3',MOD.runner_version(2022))

    def test_invalid_range_rejected(self):
        with self.assertRaises(ValueError): MOD.campaign_windows(2025,2024)

    def test_status_013_is_empty_not_failure(self):
        self.assertEqual([],MOD.items_from_payload({'status':'013','message':'조회된 데이타가 없습니다.'}))
        with self.assertRaises(RuntimeError): MOD.items_from_payload({'status':'999','message':'bad'})


if __name__=='__main__': unittest.main()
