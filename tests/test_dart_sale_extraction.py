from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.dart_sale_extraction import extract_dart_type_asset_sale
from collector.bid_extraction import load_geography_policy

POLICY = ROOT / "config/asset-use-geography-policies.json"


class DartSaleExtractionTest(unittest.TestCase):
    def test_extracts_official_asset_amount_counterparty_and_failure(self) -> None:
        text = (
            "유형자산 양도 결정 1. 자산구분 토지 및 건물 - 자산명 "
            "부산시 사하구 신평동 370-103외 4필지 및 지상 건축물 "
            "2. 양도내역 양도금액(원) 12,300,000,000 자산총액(원) 50,000,000,000 "
            "3. 양도목적 유휴 부동산 매각 4. 양도영향 재무구조 개선 "
            "5. 양도예정일자 계약체결일 2024년 02월 14일 양도기준일 2024년 12월 31일 등기예정일 2024년 12월 31일 "
            "6. 거래상대방 회사명(성명) 테스트매수법인 자본금(원) 1,000,000,000 주요사업 부동산업 "
            "매수자가 잔금 지급을 완료하지 않음에 따라 최종적으로 계약이 해제 됨 유형자산양도결정 철회"
        )
        c = extract_dart_type_asset_sale(text, load_geography_policy(POLICY))
        self.assertIsNotNone(c)
        assert c is not None
        self.assertIn("BUSAN_ULSAN_GYEONGNAM", c["regionGroups"])
        self.assertEqual("12300000000", c["amountKrwDecimal"])
        self.assertEqual("테스트매수법인", c["counterparty"])
        self.assertIn("SALE_FAILED", c["statusSignals"])
        self.assertIn("SALE_WITHDRAWN", c["statusSignals"])
        self.assertNotIn("CLOSED", c["statusSignals"])

    def test_scheduled_date_does_not_mean_closed(self) -> None:
        text = (
            "유형자산 양수 결정 1. 자산구분 토지 및 건물 - 자산명 서울시 강남구 데이터센터 "
            "2. 양수내역 양수금액(원) 100,000,000,000 자산총액(원) 1 "
            "5. 양수예정일자 계약체결일 2025년 03월 01일 양수기준일 2025년 06월 30일 등기예정일 2025년 06월 30일 "
            "6. 거래상대방 회사명(성명) 매도법인 자본금(원) 1 주요사업 부동산업 "
            "7. 거래대금지급 자금조달방법 : 차입 및 사채발행 등 8. 외부평가에 관한 사항"
        )
        c = extract_dart_type_asset_sale(text, load_geography_policy(POLICY))
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(["DATA_CENTER"], c["assetTypes"])
        self.assertIn("ACQUISITION_DEBT", c["fundingSignals"])
        self.assertIn("BOND_FINANCING", c["fundingSignals"])
        self.assertNotIn("CLOSED", c["statusSignals"])


if __name__ == "__main__":
    unittest.main()
