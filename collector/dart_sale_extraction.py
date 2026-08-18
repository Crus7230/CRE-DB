"""Rule extraction for OpenDART type-asset sale/acquisition filings.

Outputs review candidates only. Scheduled dates never imply closing.
"""
from __future__ import annotations

import re
from typing import Any

from collector.bid_extraction import ASSET_PATTERNS

CRE_PATTERN = re.compile(r"토지|필지|건물|건축물|부동산|사옥|오피스|업무시설|호텔|리조트|물류(?:센터|창고)|데이터센터|IDC", re.I)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip(" -")
    return value or None


def _field(text: str, pattern: str) -> tuple[str | None, dict | None]:
    match = re.search(pattern, text, flags=re.I | re.S)
    if not match:
        return None, None
    value = _clean(match.group(1))
    return value, {"raw": match.group(1), "start": match.start(1), "end": match.end(1)}


def extract_dart_type_asset_sale(text: str | None, geography_policy: dict[str, Any]) -> dict[str, Any] | None:
    if not text or "유형자산" not in text:
        return None
    # Preserve character offsets against stored_text: CR/LF are replaced one-for-one,
    # and whitespace is not collapsed.
    normalized = text.replace("\r", " ").replace("\n", " ")
    asset_name, asset_span = _field(
        normalized, r"(?:-|\s)자산명\s+(.+?)\s+2\.\s+(?:양도|양수)내역"
    )
    if not CRE_PATTERN.search(asset_name or normalized[:3000]):
        return None
    amount_raw, amount_span = _field(
        normalized, r"(?:양도|양수)금액\(원\)\s+([0-9,]+|-)\s+자산총액"
    )
    amount_decimal = None
    if amount_raw and amount_raw != "-":
        digits = amount_raw.replace(",", "")
        if digits.isdigit():
            amount_decimal = str(int(digits))
    purpose, purpose_span = _field(
        normalized, r"3\.\s+(?:양도|양수)목적\s+(.+?)\s+4\.\s+(?:양도|양수)영향"
    )
    counterparty, counterparty_span = _field(
        normalized, r"6\.\s+거래상대방\s+회사명\(성명\)\s+(.+?)\s+자본금\(원\)"
    )
    contract_date, contract_span = _field(
        normalized, r"계약체결일\s+(.+?)\s+(?:양도|양수)기준일"
    )
    base_date, base_span = _field(
        normalized, r"(?:양도|양수)기준일\s+(.+?)\s+등기예정일"
    )
    registration_date, registration_span = _field(
        normalized, r"등기예정일\s+(.+?)\s+6\.\s+거래상대방"
    )
    payment_terms, payment_span = _field(
        normalized, r"7\.\s+거래대금지급\s+(.+?)\s+8\.\s+외부평가"
    )
    funding_signals: list[str] = []
    for code, pattern in (
        ("ACQUISITION_DEBT", r"차입|인수금융"),
        ("BOND_FINANCING", r"사채"),
        ("OWN_CAPITAL", r"자기자금"),
        ("EQUITY_RAISE", r"유상증자"),
        ("FUND_EQUITY", r"투자신탁|펀드"),
    ):
        if re.search(pattern, payment_terms or ""):
            funding_signals.append(code)
    status: list[str] = []
    failure = bool(re.search(
        r"계약(?:이|을|은)?\s*해제|계약해지|잔금.{0,30}(?:미지급|지급.{0,8}(?:않|못))|양도결정\s*철회|양수결정\s*철회",
        normalized,
    ))
    if failure:
        status.append("SALE_FAILED")
    if re.search(r"유형자산(?:양도|양수)결정\s*철회|공시.*철회", normalized):
        status.append("SALE_WITHDRAWN")
    if not failure and re.search(r"잔금.{0,15}지급\s*완료|소유권\s*이전\s*완료|거래\s*종결\s*(?:완료|성사)", normalized):
        status.append("CLOSED")
    direction = "DISPOSITION" if "유형자산 양도" in normalized or "유형자산양도" in normalized else "ACQUISITION"
    asset_types = [code for code, pattern in ASSET_PATTERNS if pattern.search(asset_name or normalized)]
    if not asset_types:
        asset_types = ["OTHER_CRE"]
    region_groups: list[str] = []
    geography_text = asset_name or normalized[:3000]
    for code, row in geography_policy.get("regionGroups", {}).items():
        if any(term and term in geography_text for term in row.get("terms", [])):
            region_groups.append(code)
    evidence = {
        "assetName": asset_span, "amount": amount_span, "purpose": purpose_span,
        "counterparty": counterparty_span, "contractDate": contract_span,
        "baseDate": base_span, "registrationDate": registration_span,
        "paymentTerms": payment_span,
    }
    return {
        "candidateVersion": "1.0.0", "direction": direction,
        "assetName": asset_name, "assetTypes": asset_types, "regionGroups": region_groups,
        "amountRaw": amount_raw, "amountKrwDecimal": amount_decimal,
        "purpose": purpose, "counterparty": counterparty,
        "contractDateRaw": contract_date, "baseDateRaw": base_date,
        "registrationDateRaw": registration_date, "paymentTerms": payment_terms,
        "fundingSignals": funding_signals, "statusSignals": status,
        "evidenceSpans": evidence, "requiresReview": True,
        "closingPolicy": "SCHEDULED_DATE_IS_NOT_CLOSING",
    }
