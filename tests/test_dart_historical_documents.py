from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('dart_docs_history',ROOT/'scripts'/'run_backfill_dart_sale_documents.py')
MOD=importlib.util.module_from_spec(SPEC); assert SPEC.loader; SPEC.loader.exec_module(MOD)


class DartHistoricalDocumentCampaignTest(unittest.TestCase):
    def test_year_scoped_partition_identity(self):
        self.assertEqual('BACKFILL_2022_OPENDART_SALE_DOCUMENT_TEXT_V3',MOD.job_code(2022))
        self.assertEqual('backfill-2022-dart-document-text-v3',MOD.runner_version(2022))

    def test_classifies_xml_014_as_final_unavailable(self):
        payload=b'<?xml version="1.0" encoding="UTF-8"?><result><status>014</status><message>file missing</message></result>'
        self.assertEqual(('014','file missing'),MOD.parse_api_error(payload))

    def test_non_xml_non_zip_is_retryable(self):
        with self.assertRaises(MOD.NonZipResponse): MOD.parse_api_error(b'not xml')


if __name__=='__main__': unittest.main()
