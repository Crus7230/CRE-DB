"""Conservative CRE scope classifier for OpenDART transfer disclosures.

The classifier only reads transaction-subject fields. Company addresses, filer names,
and purpose text outside those fields are deliberately ignored.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


CLASSIFIER_VERSION = "DART_CRE_SCOPE_RULE_V1"

PROPERTY_PATTERN = re.compile(
    r"토지|필지|대지|부지|건물|건축물|부동산|사옥|오피스|업무시설|상가|판매시설|"
    r"근린생활시설|집합건물|공장|호텔|리조트|골프장|물류(?:센터|창고|단지)|"
    r"산업단지|데이터센터|IDC",
    re.I,
)
PROPERTY_NAME_PATTERN = re.compile(r"타워|빌딩|물류단지|산업단지|(?:^|\s)[가-힣A-Za-z0-9]+CC(?:\s|$)", re.I)
PROPERTY_LOCATION_PATTERN = re.compile(
    r"(?:서울(?:특별시|시)?|부산(?:광역시|시)?|대구(?:광역시|시)?|인천(?:광역시|시)?|"
    r"광주(?:광역시|시)?|대전(?:광역시|시)?|울산(?:광역시|시)?|세종(?:특별자치시|시)?|"
    r"경기(?:도)?|강원(?:특별자치도|도)?|충북|충남|전북|전남|경북|경남|제주(?:특별자치도|도)?)"
    r".{0,80}(?:시|군|구|읍|면|동|리|로|길|번지|블록)",
    re.I | re.S,
)
RESIDENTIAL_PATTERN = re.compile(
    r"아파트|공동주택|단독주택|다가구|다세대|임대주택|청년주택|주거시설|주택사업",
    re.I,
)
NON_RESIDENTIAL_PATTERN = re.compile(
    r"사옥|오피스|업무시설|상가|판매시설|근린생활시설|공장|호텔|리조트|골프장|"
    r"물류(?:센터|창고|단지)|산업단지|데이터센터|IDC",
    re.I,
)
EQUIPMENT_PATTERN = re.compile(
    r"기계(?:장치|기구)?|설비|생산라인|생산시설|장비|차량|운반구|선박|항공기|"
    r"금형|비품|재고자산|소프트웨어|특허|상표|라이선스",
    re.I,
)
REAL_ESTATE_CATEGORY_PATTERN = re.compile(r"토지|대지|부지|건물|건축물|부동산", re.I)


@dataclass(frozen=True)
class DartCreScopeResult:
    status: str
    report_kind: str
    reason_codes: tuple[str, ...]
    asset_text: str | None = None
    asset_category: str | None = None
    subject_text: str | None = None
    detail_text: str | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.replace("&cr;", " ").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip(" ·-–—|")
    return value or None


def _last_group(text: str, pattern: str) -> str | None:
    matches = list(re.finditer(pattern, text, flags=re.I | re.S))
    return _clean(matches[-1].group(1)) if matches else None


def _type_asset_fields(text: str) -> tuple[str | None, str | None]:
    starts = list(re.finditer(r"자산명\s+", text, flags=re.I))
    for start in reversed(starts):
        tail = text[start.end(): start.end() + 2000]
        end = re.search(r"\s+2\.\s*(?:양도|양수)내역", tail, flags=re.I)
        if not end:
            continue
        candidate = tail[:end.start()]
        if re.search(r"자산명|주요사항보고서", candidate, flags=re.I):
            continue
        prefix = text[max(0, start.start() - 500):start.start()]
        category_starts = list(re.finditer(r"1\.\s*자산구분\s+", prefix, flags=re.I))
        category = None
        if category_starts:
            category = _clean(prefix[category_starts[-1].end():])
        return category, _clean(candidate)
    return None, None


def _business_fields(text: str) -> tuple[str | None, str | None]:
    subject = _last_group(
        text,
        r"1\.\s*(?:양도|양수)영업\s+(.{1,2000}?)(?=\s+2\.\s*(?:양도|양수)영업\s*주요내용)",
    )
    detail = _last_group(
        text,
        r"2\.\s*(?:양도|양수)영업\s*주요내용\s+(.{1,4000}?)(?=\s+3\.\s*(?:양도|양수)가액)",
    )
    return subject, detail


def classify_dart_cre_scope(title: str | None, stored_text: str | None) -> DartCreScopeResult:
    title = title or ""
    text = stored_text or ""
    if "유형자산" in title or re.search(r"유형자산\s*(?:양도|양수)\s*결정", text):
        asset_category, asset = _type_asset_fields(text)
        if not asset:
            return DartCreScopeResult(
                "CRE_REVIEW_PARSE_FAILED", "TYPE_ASSET", ("ASSET_FIELD_NOT_PARSED",),
                asset_category=asset_category,
            )
        scoped_asset = " ".join(x for x in (asset_category, asset) if x)
        has_residential = bool(RESIDENTIAL_PATTERN.search(scoped_asset))
        has_non_residential = bool(NON_RESIDENTIAL_PATTERN.search(scoped_asset))
        if has_residential and not has_non_residential:
            return DartCreScopeResult(
                "OUT_OF_SCOPE_RESIDENTIAL", "TYPE_ASSET", ("RESIDENTIAL_ONLY",),
                asset_text=asset, asset_category=asset_category,
            )
        has_real_estate_category = bool(
            asset_category and REAL_ESTATE_CATEGORY_PATTERN.search(asset_category)
        )
        has_property_term = bool(PROPERTY_PATTERN.search(asset) or PROPERTY_NAME_PATTERN.search(asset))
        has_property_location = bool(PROPERTY_LOCATION_PATTERN.search(asset))
        has_property = has_real_estate_category or has_property_term or has_property_location
        if not has_property:
            return DartCreScopeResult(
                "OUT_OF_SCOPE_NON_CRE", "TYPE_ASSET", ("NO_PROPERTY_IN_ASSET_FIELD",),
                asset_text=asset, asset_category=asset_category,
            )
        if EQUIPMENT_PATTERN.search(scoped_asset):
            return DartCreScopeResult(
                "CRE_REVIEW_MIXED",
                "TYPE_ASSET",
                ("EXPLICIT_PROPERTY_SUBJECT", "MIXED_REAL_ESTATE_AND_EQUIPMENT"),
                asset_text=asset,
                asset_category=asset_category,
            )
        reasons = ["EXPLICIT_PROPERTY_SUBJECT"]
        if has_real_estate_category:
            reasons.append("REAL_ESTATE_ASSET_CATEGORY")
        if has_property_location:
            reasons.append("PROPERTY_LOCATION_IN_ASSET_FIELD")
        return DartCreScopeResult(
            "CRE_CONFIRMED", "TYPE_ASSET", tuple(reasons),
            asset_text=asset, asset_category=asset_category,
        )

    if "영업양도" in title or "영업양수" in title or re.search(r"영업\s*(?:양도|양수)\s*결정", text):
        subject, detail = _business_fields(text)
        scoped = " ".join(x for x in (subject, detail) if x)
        if not subject or not detail:
            return DartCreScopeResult(
                "CRE_REVIEW_PARSE_FAILED", "BUSINESS_TRANSFER", ("TRANSFER_FIELDS_NOT_PARSED",)
            )
        has_residential = bool(RESIDENTIAL_PATTERN.search(scoped))
        has_non_residential = bool(NON_RESIDENTIAL_PATTERN.search(scoped))
        if has_residential and not has_non_residential:
            return DartCreScopeResult(
                "OUT_OF_SCOPE_RESIDENTIAL",
                "BUSINESS_TRANSFER",
                ("RESIDENTIAL_ONLY",),
                subject_text=subject,
                detail_text=detail,
            )
        if PROPERTY_PATTERN.search(scoped) or PROPERTY_NAME_PATTERN.search(scoped) or PROPERTY_LOCATION_PATTERN.search(scoped):
            return DartCreScopeResult(
                "CRE_REVIEW",
                "BUSINESS_TRANSFER",
                ("PROPERTY_IN_TRANSFER_SUBJECT", "BUSINESS_TRANSFER_REVIEW_ONLY"),
                subject_text=subject,
                detail_text=detail,
            )
        return DartCreScopeResult(
            "OUT_OF_SCOPE_NON_CRE",
            "BUSINESS_TRANSFER",
            ("NO_PROPERTY_IN_TRANSFER_FIELDS",),
            subject_text=subject,
            detail_text=detail,
        )

    return DartCreScopeResult("CRE_REVIEW_PARSE_FAILED", "OTHER", ("UNSUPPORTED_REPORT_KIND",))
