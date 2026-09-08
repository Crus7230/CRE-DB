from collector.news_cre_scope import classify_news_cre_scope


def test_confirms_named_commercial_asset_sale() -> None:
    result = classify_news_cre_scope(
        title="NH투자증권, 여의도 파크원 타워2 인수 우협 선정",
        snippet="파크원 타워2 매각 절차에서 우선협상대상자로 선정됐다.",
        category_codes=("SALE",),
    )

    assert result.status_code == "CRE_CONFIRMED"
    assert "COMMERCIAL_ASSET_TRANSACTION" in result.reason_codes


def test_excludes_residential_only_article() -> None:
    result = classify_news_cre_scope(
        title="LH 공공지원 민간임대주택 우선협상대상자 선정",
        snippet="공동주택 공급 사업자를 선정했다.",
        category_codes=("SALE",),
    )

    assert result.status_code == "OUT_OF_SCOPE_RESIDENTIAL"


def test_excludes_explicit_non_cre_investment_article() -> None:
    result = classify_news_cre_scope(
        title="삼성자산운용, 반도체 장비업체 지분 5% 신규 취득",
        snippet="반도체 기업에 대한 주식 투자다.",
        category_codes=("INVESTMENT",),
    )

    assert result.status_code == "OUT_OF_SCOPE_NON_CRE"


def test_keeps_hotel_promotion_in_review() -> None:
    result = classify_news_cre_scope(
        title="반얀트리 호텔, 프리미엄 설 선물세트 선보여",
        snippet="호텔 고객을 위한 시즌 프로모션이다.",
        category_codes=("NEW_SUPPLY",),
    )

    assert result.status_code == "CRE_REVIEW"
    assert "COMMERCIAL_CONTEXT_WITHOUT_TRANSACTION" in result.reason_codes


def test_empty_news_fields_fail_to_review() -> None:
    result = classify_news_cre_scope(title=None, snippet="", category_codes=("SALE",))

    assert result.status_code == "CRE_REVIEW_PARSE_FAILED"


def test_semiconductor_factory_sale_is_cre_not_non_cre() -> None:
    result = classify_news_cre_scope(
        title="머큐리, 한미반도체에 인천공장 560억 매각",
        snippet="인천 공장 자산을 매각해 투자 재원을 확보한다.",
        category_codes=("SALE",),
    )

    assert result.status_code == "CRE_CONFIRMED"


def test_commercial_brand_containing_villa_is_not_residential() -> None:
    result = classify_news_cre_scope(
        title="롯데 타임빌라스 상암 개발 디자인 변경",
        snippet="개발 일정과 디자인이 조정됐다.",
        category_codes=("NEW_SUPPLY",),
    )

    assert result.status_code != "OUT_OF_SCOPE_RESIDENTIAL"


def test_pf_article_with_bongeim_phrase_is_not_game_industry() -> None:
    result = classify_news_cre_scope(
        title="롯데건설 PF 정상화, 현금창출 본게임",
        snippet="건설사 프로젝트 금융 정상화 분석이다.",
        category_codes=("PF",),
    )

    assert result.status_code != "OUT_OF_SCOPE_NON_CRE"


def test_confirms_project_specific_pf_action_without_named_asset() -> None:
    result = classify_news_cre_scope(
        title="성수 프로젝트 사업장 본PF 3천억원 금융주선 완료",
        snippet="시행사와 대주단이 자금보충 조건을 포함한 본PF 약정을 체결했다.",
        category_codes=("PF",),
    )

    assert result.status_code == "CRE_CONFIRMED"
    assert "PROJECT_SPECIFIC_PF_ACTION" in result.reason_codes


def test_keeps_aggregate_pf_policy_article_in_review() -> None:
    result = classify_news_cre_scope(
        title="금융당국, 부동산 PF 정상화 정책 점검",
        snippet="전국 PF 잔액과 연체율을 종합 점검했다.",
        category_codes=("PF",),
    )

    assert result.status_code == "CRE_REVIEW"


def test_non_cre_industry_word_does_not_exclude_permit_project() -> None:
    result = classify_news_cre_scope(
        title="성남 바이오헬스 첨단클러스터 실시계획 인가 신청",
        snippet="도시개발 절차를 진행한다.",
        category_codes=("PERMIT",),
    )

    assert result.status_code != "OUT_OF_SCOPE_NON_CRE"


def test_mixed_residential_and_office_article_is_retained() -> None:
    result = classify_news_cre_scope(
        title="아파트 리모델링과 역세권 업무복합시설 조성",
        snippet="두 개발 안건을 함께 다룬다.",
        category_codes=("PERMIT",),
    )

    assert result.status_code != "OUT_OF_SCOPE_RESIDENTIAL"


def test_excludes_crypto_sale_that_only_mentions_future_data_center_strategy() -> None:
    result = classify_news_cre_scope(
        title="클린코어, 4억6300만 DOGE 전량 매각…AI 데이터센터로 대전환",
        snippet="도지코인 보유분을 처분하고 신규 사업을 검토한다.",
        category_codes=("SALE",),
    )

    assert result.status_code == "OUT_OF_SCOPE_NON_CRE"
    assert "NON_CRE_TRANSACTION_OBJECT" in result.reason_codes


def test_excludes_share_sale_that_mentions_data_center_as_use_of_proceeds() -> None:
    result = classify_news_cre_scope(
        title="삼성SDI, AI 데이터센터에 승부…삼성D 지분 매각 4.45조 실탄확보",
        snippet="계열사 지분을 매각해 투자 재원을 마련한다.",
        category_codes=("SALE",),
    )

    assert result.status_code == "OUT_OF_SCOPE_NON_CRE"


def test_keeps_corporate_brand_sale_without_property_object_out_of_confirmed_scope() -> None:
    result = classify_news_cre_scope(
        title="LG생활건강, 미국 에이본 매각…리테일·디지털 중심 재편",
        snippet="화장품 사업 브랜드를 정리한다.",
        category_codes=("SALE",),
    )

    assert result.status_code != "CRE_CONFIRMED"
