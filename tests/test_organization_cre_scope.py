from collector.organization_cre_scope import classify_organization_cre_scope


def test_krx_semiconductor_identity_is_context_only() -> None:
    result = classify_organization_cre_scope(
        status_code="ACTIVE",
        metadata={"krx_snapshot_date": "2026-08-01", "kind_industry": "반도체 제조업"},
        has_event_participation=False,
        has_resolved_mention=False,
    )
    assert result.status_code == "CRE_CONTEXT_ONLY"


def test_krx_real_estate_industry_is_confirmed() -> None:
    result = classify_organization_cre_scope(
        status_code="ACTIVE",
        metadata={"krx_snapshot_date": "2026-08-01", "kind_industry": "부동산 임대 및 공급업"},
        has_event_participation=False,
        has_resolved_mention=False,
    )
    assert result.status_code == "CRE_CONFIRMED"


def test_event_participant_is_confirmed_regardless_of_industry() -> None:
    result = classify_organization_cre_scope(
        status_code="ACTIVE",
        metadata={"krx_snapshot_date": "2026-08-01", "kind_industry": "전기전자"},
        has_event_participation=True,
        has_resolved_mention=False,
    )
    assert result.status_code == "CRE_CONFIRMED"


def test_quarantined_identity_fails_to_review() -> None:
    result = classify_organization_cre_scope(
        status_code="QUARANTINED",
        metadata={},
        has_event_participation=False,
        has_resolved_mention=False,
    )
    assert result.status_code == "CRE_REVIEW"


def test_inactive_identity_fails_to_review() -> None:
    result = classify_organization_cre_scope(
        status_code="INACTIVE",
        metadata={"krx_snapshot_date": "2026-08-01"},
        has_event_participation=False,
        has_resolved_mention=False,
    )
    assert result.status_code == "CRE_REVIEW"
