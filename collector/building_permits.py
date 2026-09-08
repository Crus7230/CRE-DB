"""Normalization and conservative CRE taxonomy for official building-permit APIs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Iterable

RULE_VERSION = "cre-permit-v1"
CORE_SCOPE_STATUSES = {
    "IN_SCOPE", "REVIEW_MIXED", "REVIEW_DATA_CENTER", "REVIEW_OTHER", "REVIEW_UNKNOWN"
}

RESIDENTIAL_TERMS = ("단독주택", "공동주택", "다가구", "다세대", "연립주택", "기숙사")
NONCOMMERCIAL_TERMS = (
    "종교시설", "교정 및 군사시설", "교정및군사시설", "묘지관련시설", "동물 및 식물관련시설",
    "동물및식물관련시설", "자원순환 관련 시설", "자원순환관련시설", "발전시설",
)
OFFICE_TERMS = ("업무시설",)
LOGISTICS_TERMS = ("창고시설", "물류시설", "운수시설")
HOTEL_TERMS = ("숙박시설", "호텔")
RETAIL_TERMS = ("판매시설", "근린생활시설", "위락시설")
OTHER_COMMERCIAL_TERMS = (
    "문화 및 집회시설", "문화및집회시설", "교육연구시설", "의료시설", "운동시설",
    "자동차관련시설", "자동차 관련 시설", "공장", "관광휴게시설", "장례시설",
)
DATA_CENTER_TERMS = ("데이터센터", "데이터 센터", "전산센터", "전산 센터", "IDC", "IDC센터")
TELECOM_TERMS = ("방송통신시설", "방송 통신 시설")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{sha256_text(raw)[:32]}"


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def parse_date(value: Any) -> str | None:
    text = clean_text(value)
    if not text or text in {"0", "00000000", "-"}:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    return None


def parse_float(value: Any) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        number = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    return float(number)


def parse_int(value: Any) -> int | None:
    number = parse_float(value)
    return int(number) if number is not None else None


def _contains(text: str, terms: Iterable[str]) -> bool:
    compact = text.replace(" ", "").casefold()
    return any(term.replace(" ", "").casefold() in compact for term in terms)


def construction_action(construction_type: Any) -> str:
    value = clean_text(construction_type) or ""
    if "용도변경" in value:
        return "USE_CONVERSION"
    if "증축" in value:
        return "AREA_EXPANSION"
    if any(term in value for term in ("개축", "재축", "대수선")):
        return "REDEVELOPMENT"
    if "신축" in value:
        return "NEW_SUPPLY"
    return "OTHER"


def classify_cre_permit(raw: dict[str, Any]) -> dict[str, Any]:
    use = clean_text(raw.get("MN_USG_CD_NM") or raw.get("mainPurpsCdNm") or raw.get("main_use_name")) or ""
    name = clean_text(raw.get("BLDG_NM") or raw.get("bldNm") or raw.get("building_name")) or ""
    other = clean_text(raw.get("ETC_PURPS") or raw.get("etcPurps") or raw.get("other_use_name")) or ""
    searchable = " ".join((use, name, other))
    households = parse_int(raw.get("HH_CNT") if "HH_CNT" in raw else raw.get("hhldCnt")) or 0
    families = parse_int(raw.get("FML_CNT") if "FML_CNT" in raw else raw.get("fmlyCnt")) or 0
    residential = _contains(use, RESIDENTIAL_TERMS)
    explicit_mixed = _contains(searchable, ("복합용도", "주상복합", "복합시설"))
    commercial_signal = any(
        _contains(searchable, terms)
        for terms in (OFFICE_TERMS, LOGISTICS_TERMS, HOTEL_TERMS, RETAIL_TERMS, OTHER_COMMERCIAL_TERMS, TELECOM_TERMS)
    )
    reason: dict[str, Any] = {
        "mainUse": use,
        "buildingName": name,
        "householdCount": households,
        "familyCount": families,
    }
    action = construction_action(raw.get("ARCH_SE_CD_NM") or raw.get("archGbCdNm") or raw.get("construction_type"))

    if explicit_mixed or ((households > 0 or families > 0 or residential) and commercial_signal):
        status, asset, confidence = "REVIEW_MIXED", "MIXED_USE", 0.8
        reason["rule"] = "mixed_use_or_residential_count_with_commercial_signal"
    elif residential:
        status, asset, confidence = "EXCLUDED_RESIDENTIAL", "RESIDENTIAL", 0.98
        reason["rule"] = "residential_main_use"
    elif _contains(searchable, DATA_CENTER_TERMS):
        status, asset, confidence = "IN_SCOPE", "DATA_CENTER", 0.95
        reason["rule"] = "explicit_data_center_text"
    elif _contains(use, TELECOM_TERMS):
        status, asset, confidence = "REVIEW_DATA_CENTER", "DATA_CENTER", 0.6
        reason["rule"] = "broadcast_telecom_requires_data_center_confirmation"
    elif _contains(use, OFFICE_TERMS):
        status, asset, confidence = "IN_SCOPE", "OFFICE", 0.95
        reason["rule"] = "office_main_use"
    elif _contains(use, LOGISTICS_TERMS):
        status, asset, confidence = "IN_SCOPE", "LOGISTICS", 0.92
        reason["rule"] = "warehouse_logistics_transport_main_use"
    elif _contains(use, HOTEL_TERMS):
        status, asset, confidence = "IN_SCOPE", "HOTEL", 0.95
        reason["rule"] = "lodging_main_use"
    elif _contains(use, RETAIL_TERMS):
        status, asset, confidence = "IN_SCOPE", "RETAIL", 0.9
        reason["rule"] = "retail_neighborhood_entertainment_main_use"
    elif _contains(use, NONCOMMERCIAL_TERMS):
        status, asset, confidence = "EXCLUDED_NONCOMMERCIAL", "NONCOMMERCIAL", 0.9
        reason["rule"] = "noncommercial_main_use"
    elif _contains(use, OTHER_COMMERCIAL_TERMS):
        status, asset, confidence = "REVIEW_OTHER", "OTHER_COMMERCIAL", 0.65
        reason["rule"] = "alternative_commercial_candidate"
    elif not use:
        status, asset, confidence = "REVIEW_UNKNOWN", "UNKNOWN", 0.2
        reason["rule"] = "missing_main_use"
    else:
        status, asset, confidence = "REVIEW_OTHER", "OTHER_COMMERCIAL", 0.4
        reason["rule"] = "unmapped_nonresidential_use"

    return {
        "rule_version": RULE_VERSION,
        "scope_status": status,
        "asset_type": asset,
        "construction_action": action,
        "confidence_score": confidence,
        "reason": reason,
    }


def _district(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    matches = re.findall(r"(?:^|\s)([^\s]+구)(?:\s|$)", text)
    return matches[-1] if matches else text.replace("서울특별시 ", "").strip()


def normalize_seoul_record(raw: dict[str, Any]) -> dict[str, Any]:
    key = clean_text(raw.get("PRMSN_LDGR_SN"))
    if not key:
        raise ValueError("Seoul permit record is missing PRMSN_LDGR_SN")
    return {
        "source_record_key": key,
        "source_created_date": None,
        "sigungu_code": None,
        "bjdong_code": None,
        "district_name": _district(raw.get("SGG_CD_NM")),
        "legal_dong_name": clean_text(raw.get("STDG_CD_NM")),
        "parcel_address": clean_text(raw.get("PLAT_PLC")),
        "road_address": None,
        "parcel_type_code": None,
        "main_lot_number": None,
        "sub_lot_number": None,
        "building_name": clean_text(raw.get("BLDG_NM")),
        "construction_type": clean_text(raw.get("ARCH_SE_CD_NM")),
        "main_use_code": None,
        "main_use_name": clean_text(raw.get("MN_USG_CD_NM")),
        "site_area_m2": parse_float(raw.get("SIAR")),
        "building_area_m2": parse_float(raw.get("BDAR")),
        "total_floor_area_m2": parse_float(raw.get("GFA")),
        "household_count": parse_int(raw.get("HH_CNT")),
        "unit_count": parse_int(raw.get("HO_CNT")),
        "family_count": parse_int(raw.get("FML_CNT")),
        "permit_date": parse_date(raw.get("ARCH_PRMSN_YMD")),
        "planned_start_date": parse_date(raw.get("BGNCST_PRNMNT_YMD")),
        "delayed_start_date": parse_date(raw.get("BGNCST_PPM_YMD")),
        "actual_start_date": parse_date(raw.get("ACTL_BGNCST_YMD")),
        "use_approval_date": parse_date(raw.get("USE_APRV_YMD")),
    }


def normalize_buildinghub_record(raw: dict[str, Any]) -> dict[str, Any]:
    key = clean_text(raw.get("mgmPmsrgstPk"))
    if not key:
        raise ValueError("BuildingHUB permit record is missing mgmPmsrgstPk")
    return {
        "source_record_key": key,
        "source_created_date": parse_date(raw.get("crtnDay")),
        "sigungu_code": clean_text(raw.get("sigunguCd")),
        "bjdong_code": clean_text(raw.get("bjdongCd")),
        "district_name": clean_text(raw.get("sigunguCdNm")),
        "legal_dong_name": clean_text(raw.get("bjdongCdNm")),
        "parcel_address": clean_text(raw.get("platPlc")),
        "road_address": clean_text(raw.get("newPlatPlc")),
        "parcel_type_code": clean_text(raw.get("platGbCd")),
        "main_lot_number": clean_text(raw.get("bun")),
        "sub_lot_number": clean_text(raw.get("ji")),
        "building_name": clean_text(raw.get("bldNm")),
        "construction_type": clean_text(raw.get("archGbCdNm")),
        "main_use_code": clean_text(raw.get("mainPurpsCd")),
        "main_use_name": clean_text(raw.get("mainPurpsCdNm")),
        "site_area_m2": parse_float(raw.get("platArea")),
        "building_area_m2": parse_float(raw.get("archArea")),
        "total_floor_area_m2": parse_float(raw.get("totArea")),
        "household_count": parse_int(raw.get("hhldCnt")),
        "unit_count": parse_int(raw.get("hoCnt")),
        "family_count": parse_int(raw.get("fmlyCnt")),
        "permit_date": parse_date(raw.get("archPmsDay")),
        "planned_start_date": parse_date(raw.get("stcnsSchedDay")),
        "delayed_start_date": parse_date(raw.get("stcnsDelayDay")),
        "actual_start_date": parse_date(raw.get("realStcnsDay")),
        "use_approval_date": parse_date(raw.get("useAprDay")),
    }


def event_rows(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for event_type, field in (
        ("PERMIT", "permit_date"),
        ("ACTUAL_START", "actual_start_date"),
        ("USE_APPROVAL", "use_approval_date"),
    ):
        value = normalized.get(field)
        if value:
            result.append({"event_type": event_type, "event_date": value, "event_month": value[:7]})
    return result
