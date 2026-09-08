from __future__ import annotations

from collector.dart_cre_scope import classify_dart_cre_scope


def type_asset(asset: str, extra: str = "", category: str = "토지 및 건물") -> str:
    return f"""주요사항보고서 유형자산 양수 결정
1. 자산구분 {category}
- 자산명 {asset}
2. 양수내역
양수금액(원) 10,000,000,000
3. 양수목적 사업기반 확보
4. 양수영향 자산 증가
{extra}
"""


def business_transfer(subject: str, detail: str, purpose: str = "경영 효율화") -> str:
    return f"""본점 소재지 서울특별시 강남구 테헤란로 1
영업양도 결정
1. 양도영업 {subject}
2. 양도영업 주요내용 {detail}
3. 양도가액 (원) 10,000,000,000
4. 양도목적 {purpose}
5. 양도예정일자 2026년 1월 1일
"""


def test_confirms_type_asset_only_from_explicit_property_field() -> None:
    result = classify_dart_cre_scope(
        "주요사항보고서(유형자산양수결정)",
        type_asset("서울특별시 강남구 역삼동 123 토지 1,200㎡ 및 업무시설 건물"),
    )
    assert result.status == "CRE_CONFIRMED"
    assert result.asset_text == "서울특별시 강남구 역삼동 123 토지 1,200㎡ 및 업무시설 건물"
    assert "EXPLICIT_PROPERTY_SUBJECT" in result.reason_codes


def test_excludes_non_property_asset_despite_company_address() -> None:
    text = "본점 소재지 서울특별시 강남구 테헤란로 1\n" + type_asset(
        "반도체 생산설비 및 기계장치 일체", category="기계장치"
    )
    result = classify_dart_cre_scope("주요사항보고서(유형자산양수결정)", text)
    assert result.status == "OUT_OF_SCOPE_NON_CRE"


def test_mixed_property_and_machinery_requires_review() -> None:
    result = classify_dart_cre_scope(
        "주요사항보고서(유형자산양도결정)",
        type_asset("전북 익산시 신흥동 토지 및 건물, 구축물, 기계장치 일체"),
    )
    assert result.status == "CRE_REVIEW_MIXED"
    assert "MIXED_REAL_ESTATE_AND_EQUIPMENT" in result.reason_codes


def test_correction_uses_bounded_final_asset_field() -> None:
    text = """정정사항 자산명 오기 정정전 반도체 장비 정정후 토지 및 건물
주요사항보고서 유형자산 양수 결정
1. 자산구분 토지 및 건물
- 자산명 경기도 성남시 판교동 123 토지 및 건물
2. 양수내역
양수금액(원) 20,000,000,000
3. 양수목적 사옥 확보
4. 양수영향 자산 증가
"""
    result = classify_dart_cre_scope("[기재정정]주요사항보고서(유형자산양수결정)", text)
    assert result.status == "CRE_CONFIRMED"
    assert result.asset_text == "경기도 성남시 판교동 123 토지 및 건물"


def test_business_transfer_property_is_review_only() -> None:
    result = classify_dart_cre_scope(
        "영업양수결정",
        business_transfer("분당두산타워 토지·건물 양수", "분당두산타워 부동산 임대사업 관련 자산 일체"),
    )
    assert result.status == "CRE_REVIEW"
    assert result.report_kind == "BUSINESS_TRANSFER"


def test_type_asset_address_only_is_property_evidence() -> None:
    result = classify_dart_cre_scope(
        "주요사항보고서(유형자산양수결정)",
        type_asset("서울시 성동구 왕십리로 58 포휴 제10층 제1001호부터 제1014호"),
    )
    assert result.status == "CRE_CONFIRMED"
    assert "PROPERTY_LOCATION_IN_ASSET_FIELD" in result.reason_codes


def test_type_asset_named_logistics_site_is_property_evidence() -> None:
    result = classify_dart_cre_scope(
        "주요사항보고서(유형자산양수결정)",
        type_asset("용인국제물류4.0 물류단지 M2 블록"),
    )
    assert result.status == "CRE_CONFIRMED"


def test_real_estate_asset_category_confirms_opaque_building_name() -> None:
    result = classify_dart_cre_scope(
        "주요사항보고서(유형자산양수결정)",
        type_asset("에이원타워 당산"),
    )
    assert result.status == "CRE_CONFIRMED"
    assert result.asset_category == "토지 및 건물"
    assert "REAL_ESTATE_ASSET_CATEGORY" in result.reason_codes


def test_business_transfer_address_inside_subject_is_review() -> None:
    result = classify_dart_cre_scope(
        "영업양도결정",
        business_transfer("비유동자산 양도", "보유 비유동자산 일체(서울특별시 강남구 역삼동 832-21)"),
    )
    assert result.status == "CRE_REVIEW"


def test_mixed_residential_and_commercial_development_is_review() -> None:
    result = classify_dart_cre_scope(
        "영업양수결정",
        business_transfer(
            "역세권 청년주택 및 근린생활시설 개발사업",
            "사업부지 및 지상 건축물의 부동산매매계약 매수자 지위",
        ),
    )
    assert result.status == "CRE_REVIEW"


def test_business_transfer_ignores_hotel_word_outside_subject_sections() -> None:
    result = classify_dart_cre_scope(
        "영업양도결정",
        business_transfer("위탁급식 사업", "위탁급식 사업에 관한 권리와 의무 일체", "호텔 사업 집중"),
    )
    assert result.status == "OUT_OF_SCOPE_NON_CRE"


def test_business_transfer_parse_failure_is_reviewed_not_deleted() -> None:
    result = classify_dart_cre_scope("영업양도결정", "양도 대상 field가 손상된 공시")
    assert result.status == "CRE_REVIEW_PARSE_FAILED"
    assert "TRANSFER_FIELDS_NOT_PARSED" in result.reason_codes


def test_business_transfer_partial_parse_is_reviewed_not_deleted() -> None:
    result = classify_dart_cre_scope(
        "영업양도결정",
        "1. 양도영업 위탁급식 사업 2. 양도영업 주요내용이 손상되어 후속 section이 없음",
    )
    assert result.status == "CRE_REVIEW_PARSE_FAILED"
    assert "TRANSFER_FIELDS_NOT_PARSED" in result.reason_codes


def test_unsupported_disclosure_kind_is_reviewed_not_deleted() -> None:
    result = classify_dart_cre_scope("타법인주식및출자증권취득결정", "본문")
    assert result.status == "CRE_REVIEW_PARSE_FAILED"
    assert "UNSUPPORTED_REPORT_KIND" in result.reason_codes


def test_residential_property_is_separately_out_of_scope() -> None:
    result = classify_dart_cre_scope(
        "영업양수결정",
        business_transfer("역삼동 임대주택 사업", "임대주택 부동산 매수자 지위 및 개발사업권"),
    )
    assert result.status == "OUT_OF_SCOPE_RESIDENTIAL"
