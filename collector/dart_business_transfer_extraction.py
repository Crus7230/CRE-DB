from __future__ import annotations

import re

CRE_BUSINESS_PATTERN = re.compile(
    r"토지|필지|건물|건축물|부동산|사옥|오피스|업무시설|호텔|리조트|"
    r"물류(?:센터|창고)|데이터센터|IDC",
    re.I,
)


def extract_business_transfer_cre_candidate(text: str | None) -> dict | None:
    """Return exact keyword spans only; never infer an asset sale or closing."""
    if not text or not re.search(r"영업\s*(?:양도|양수)", text):
        return None
    window = text[:12000]
    spans = [
        {"raw": match.group(0), "start": match.start(), "end": match.end()}
        for match in CRE_BUSINESS_PATTERN.finditer(window)
    ]
    if not spans:
        return None
    return {
        "candidateVersion": "1.0.0",
        "keywordSpans": spans,
        "requiresReview": True,
        "classificationPolicy": "BUSINESS_TRANSFER_IS_NOT_AUTOMATICALLY_AN_ASSET_SALE",
        "canonicalAutoCreate": False,
    }
