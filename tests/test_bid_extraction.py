from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.bid_extraction import extract_bid_process_candidate, load_geography_policy
POLICY = ROOT / "config" / "asset-use-geography-policies.json"


class BidExtractionTest(unittest.TestCase):
    def test_final_bid_price_rank_shortlist_and_funding_are_separate_signals(self) -> None:
        text = (
            "코람코자산운용, 부산 호텔 본입찰에 약 3,200억원 써내 2위…"
            "A컨소시엄과 숏리스트, 블라인드펀드·국민은행 인수금융 활용"
        )
        c = extract_bid_process_candidate(text, "", load_geography_policy(POLICY))
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(("HOTEL",), c.asset_types)
        self.assertIn("BUSAN_ULSAN_GYEONGNAM", c.region_groups)
        self.assertIn("FINAL_BID", c.stage_signals)
        self.assertIn("SHORTLISTED", c.stage_signals)
        self.assertIn("BLIND_FUND_EQUITY", c.funding_signals)
        self.assertIn("ACQUISITION_DEBT", c.funding_signals)
        money = c.money_mentions[0]
        self.assertEqual("320000000000", money.normalized_krw_decimal)
        self.assertEqual("ABOUT", money.comparator_code)
        self.assertEqual(2, c.reported_ranks[0].rank)
        self.assertTrue(c.requires_review)

    def test_preferred_is_not_closing_and_closing_needs_own_signal(self) -> None:
        preferred = extract_bid_process_candidate(
            "서울 오피스 우선협상대상자 선정", "SPA와 거래종결은 아직", load_geography_policy(POLICY)
        )
        assert preferred is not None
        self.assertIn("PREFERRED_BIDDER_SELECTED", preferred.stage_signals)
        self.assertNotIn("CLOSED", preferred.stage_signals)
        closed = extract_bid_process_candidate(
            "서울 오피스 잔금납입 완료, 소유권 이전으로 거래종결", "", load_geography_policy(POLICY)
        )
        assert closed is not None
        self.assertIn("CLOSED", closed.stage_signals)

    def test_interest_and_actual_submission_are_not_same(self) -> None:
        interest = extract_bid_process_candidate(
            "광주 데이터센터 인수 검토", "입찰 참여를 검토 중", load_geography_policy(POLICY)
        )
        submitted = extract_bid_process_candidate(
            "광주 데이터센터 예비입찰 참여", "인수의향서를 제출했다", load_geography_policy(POLICY)
        )
        assert interest is not None and submitted is not None
        self.assertIn("INTEREST_REPORTED", interest.participation_signals)
        self.assertNotIn("PRELIMINARY_BID_SUBMITTED", interest.participation_signals)
        self.assertIn("PRELIMINARY_BID_SUBMITTED", submitted.participation_signals)

    def test_negation_blocks_false_closing(self) -> None:
        c = extract_bid_process_candidate(
            "부산 호텔 매각, 거래종결 아니다", "우협 선정 이후 협상 중", load_geography_policy(POLICY)
        )
        assert c is not None
        self.assertNotIn("CLOSED", c.stage_signals)

    def test_google_news_publisher_suffix_does_not_create_false_region(self) -> None:
        c = extract_bid_process_candidate(
            "현대모비스 본사 사옥 우협에 이지스운용 - 부산파이낸셜뉴스",
            "현대모비스 본사 사옥 우협에 이지스운용 부산파이낸셜뉴스",
            load_geography_policy(POLICY),
        )
        assert c is not None
        self.assertNotIn("BUSAN_ULSAN_GYEONGNAM", c.region_groups)

    def test_geography_policy_office_capital_hotel_logistics_dc_nationwide(self) -> None:
        policy = load_geography_policy(POLICY)
        office = policy["assetUsePolicies"]["OFFICE"]
        self.assertEqual(["CAPITAL"], office["includedGroups"])
        for asset_type in ("HOTEL", "LOGISTICS", "DATA_CENTER"):
            row = policy["assetUsePolicies"][asset_type]
            self.assertEqual("NATIONWIDE_GROUPED", row["coverageMode"])
            self.assertIn("BUSAN_ULSAN_GYEONGNAM", row["includedGroups"])
            self.assertIn("HONAM", row["includedGroups"])


if __name__ == "__main__":
    unittest.main()
