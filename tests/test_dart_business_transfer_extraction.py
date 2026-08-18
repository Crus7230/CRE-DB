from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.dart_business_transfer_extraction import extract_business_transfer_cre_candidate


class DartBusinessTransferExtractionTest(unittest.TestCase):
    def test_requires_business_transfer_and_preserves_exact_span(self) -> None:
        text = "영업 양도 결정 대상 사업에는 호텔 운영 및 관련 부동산이 포함된다."
        result = extract_business_transfer_cre_candidate(text)
        self.assertIsNotNone(result)
        self.assertFalse(result["canonicalAutoCreate"])
        for span in result["keywordSpans"]:
            self.assertEqual(span["raw"], text[span["start"]:span["end"]])

    def test_non_cre_business_transfer_is_not_a_candidate(self) -> None:
        self.assertIsNone(extract_business_transfer_cre_candidate("영업양도 결정 반도체 설계 사업부"))

    def test_asset_keyword_without_business_transfer_is_not_a_candidate(self) -> None:
        self.assertIsNone(extract_business_transfer_cre_candidate("호텔 부동산 매각"))


if __name__ == "__main__":
    unittest.main()
