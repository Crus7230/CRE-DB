from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import DiscoveredDocument, ingest_partition
from collector.sale_process_candidates import extract_and_queue_bid_process_candidates


class SaleProcessCandidateQueueTest(unittest.TestCase):
    def test_duplicate_discovery_creates_one_review_candidate_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "market.db"
            con = sqlite3.connect(db)
            con.executescript((ROOT / "db/v2/schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db/v2/seed.sql").read_text(encoding="utf-8"))
            con.close()
            doc = DiscoveredDocument(
                canonical_url="https://example.com/deal-1",
                external_key="deal-1",
                title="코람코자산운용 부산 호텔 본입찰 2위",
                publisher_name="테스트뉴스",
                published_at="2025-05-01T00:00:00Z",
                snippet_text="약 3,200억원, 블라인드펀드와 인수금융 활용",
                document_type="RSS_ITEM",
                rights_status="EXCERPT_ALLOWED",
                metadata={},
            )
            for suffix in ("A", "B"):
                ingest_partition(
                    db_path=db,
                    source_code="GOOGLE_NEWS_RSS",
                    job_code=f"BACKFILL_2025_BID_TEST_{suffix}",
                    category_code="SALE",
                    window_start="2025-05-01T00:00:00Z",
                    window_end="2025-06-01T00:00:00Z",
                    query_rendered=f"query-{suffix}",
                    documents=[doc],
                    runner_version="2025-bid-process-v1",
                )
            first = extract_and_queue_bid_process_candidates(
                db_path=db,
                geography_policy_path=ROOT / "config/asset-use-geography-policies.json",
            )
            self.assertEqual(1, first.scanned_documents)
            self.assertEqual(1, first.matched_documents)
            self.assertEqual(1, first.inserted_event_mentions)
            self.assertEqual(1, first.inserted_review_tasks)
            second = extract_and_queue_bid_process_candidates(
                db_path=db,
                geography_policy_path=ROOT / "config/asset-use-geography-policies.json",
            )
            self.assertEqual(0, second.inserted_extraction_runs)
            self.assertEqual(0, second.inserted_event_mentions)
            self.assertEqual(0, second.inserted_review_tasks)
            con = sqlite3.connect(db)
            payload = con.execute(
                "SELECT payload_json FROM review_tasks WHERE review_type='SALE_PROCESS_EVIDENCE_REVIEW'"
            ).fetchone()[0]
            self.assertIn('"normalized_krw_decimal": "320000000000"', payload)
            self.assertEqual(0, con.execute("SELECT count(*) FROM events").fetchone()[0])
            self.assertEqual(0, con.execute("SELECT count(*) FROM sale_processes").fetchone()[0])
            con.close()


if __name__ == "__main__":
    unittest.main()
