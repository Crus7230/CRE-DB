from __future__ import annotations

from collector.building_permits import classify_cre_permit, event_rows, normalize_seoul_record


def record(**overrides):
    base = {
        "PLAT_PLC": "서울특별시 강남구 역삼동 1-1",
        "SGG_CD_NM": "서울특별시 강남구",
        "STDG_CD_NM": "역삼동",
        "PRMSN_LDGR_SN": "1234567890123456789012",
        "BLDG_NM": "테스트 빌딩",
        "ARCH_SE_CD_NM": "신축",
        "SIAR": 2000,
        "BDAR": 900,
        "GFA": 10000,
        "MN_USG_CD_NM": "업무시설",
        "HH_CNT": 0,
        "HO_CNT": 0,
        "FML_CNT": 0,
        "BGNCST_PRNMNT_YMD": "2025-02-01",
        "BGNCST_PPM_YMD": "",
        "ACTL_BGNCST_YMD": "2025-03-04",
        "ARCH_PRMSN_YMD": "2025-01-02",
        "USE_APRV_YMD": "2026-06-07",
    }
    base.update(overrides)
    return base


def test_core_cre_asset_taxonomy_is_conservative() -> None:
    assert classify_cre_permit(record(MN_USG_CD_NM="업무시설"))["asset_type"] == "OFFICE"
    assert classify_cre_permit(record(MN_USG_CD_NM="창고시설"))["asset_type"] == "LOGISTICS"
    assert classify_cre_permit(record(MN_USG_CD_NM="숙박시설"))["asset_type"] == "HOTEL"
    assert classify_cre_permit(record(MN_USG_CD_NM="판매시설"))["asset_type"] == "RETAIL"
    data_center = classify_cre_permit(
        record(MN_USG_CD_NM="방송통신시설", BLDG_NM="강남 데이터센터")
    )
    assert data_center["scope_status"] == "IN_SCOPE"
    assert data_center["asset_type"] == "DATA_CENTER"
    telecom = classify_cre_permit(record(MN_USG_CD_NM="방송통신시설", BLDG_NM="방송국"))
    assert telecom["scope_status"] == "REVIEW_DATA_CENTER"
    assert telecom["asset_type"] == "DATA_CENTER"


def test_residential_noncommercial_mixed_and_unknown_are_not_forced_in_scope() -> None:
    residential = classify_cre_permit(record(MN_USG_CD_NM="공동주택", HH_CNT=50))
    assert residential["scope_status"] == "EXCLUDED_RESIDENTIAL"
    mixed = classify_cre_permit(record(MN_USG_CD_NM="업무시설", HH_CNT=20))
    assert mixed["scope_status"] == "REVIEW_MIXED"
    assert mixed["asset_type"] == "MIXED_USE"
    religious = classify_cre_permit(record(MN_USG_CD_NM="종교시설"))
    assert religious["scope_status"] == "EXCLUDED_NONCOMMERCIAL"
    unknown = classify_cre_permit(record(MN_USG_CD_NM=""))
    assert unknown["scope_status"] == "REVIEW_UNKNOWN"


def test_use_change_is_not_counted_as_new_supply() -> None:
    result = classify_cre_permit(record(ARCH_SE_CD_NM="용도변경"))
    assert result["construction_action"] == "USE_CONVERSION"
    assert result["scope_status"] == "IN_SCOPE"


def test_normalization_and_actual_event_rows() -> None:
    normalized = normalize_seoul_record(record())
    assert normalized["source_record_key"] == "1234567890123456789012"
    assert normalized["district_name"] == "강남구"
    assert normalized["total_floor_area_m2"] == 10000.0
    assert normalized["permit_date"] == "2025-01-02"
    assert normalized["actual_start_date"] == "2025-03-04"
    events = event_rows(normalized)
    assert [(item["event_type"], item["event_month"]) for item in events] == [
        ("PERMIT", "2025-01"),
        ("ACTUAL_START", "2025-03"),
        ("USE_APPROVAL", "2026-06"),
    ]
