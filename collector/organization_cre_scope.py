from __future__ import annotations

from dataclasses import dataclass
import re


CLASSIFIER_VERSION = "ORG_CRE_SCOPE_RULE_V1"
_CRE_INDUSTRY = re.compile(
    r"부동산|건물\s*건설|토목\s*건설|종합\s*건설|전문직별\s*공사|건축기술|"
    r"건설업|신탁업\s*및\s*집합투자업",
    re.IGNORECASE,
)
_CRE_NAME = re.compile(r"리츠|REIT", re.IGNORECASE)


@dataclass(frozen=True)
class OrganizationCreScopeResult:
    status_code: str
    reason_codes: tuple[str, ...]
    classifier_version: str = CLASSIFIER_VERSION


def classify_organization_cre_scope(
    *,
    status_code: str | None,
    metadata: dict | None,
    has_event_participation: bool,
    has_resolved_mention: bool,
    canonical_name: str = "",
) -> OrganizationCreScopeResult:
    values = metadata if isinstance(metadata, dict) else {}
    normalized_status = (status_code or "").upper()
    if normalized_status != "ACTIVE":
        return OrganizationCreScopeResult("CRE_REVIEW", ("IDENTITY_NOT_ACTIVE",))
    if has_event_participation:
        return OrganizationCreScopeResult("CRE_CONFIRMED", ("CANONICAL_EVENT_PARTICIPANT",))
    if has_resolved_mention:
        return OrganizationCreScopeResult("CRE_CONFIRMED", ("RESOLVED_DOCUMENT_MENTION",))
    industry = str(values.get("kind_industry") or "")
    if _CRE_INDUSTRY.search(industry) or _CRE_NAME.search(canonical_name or ""):
        return OrganizationCreScopeResult("CRE_CONFIRMED", ("DIRECT_CRE_INDUSTRY",))
    if values.get("krx_snapshot_date"):
        return OrganizationCreScopeResult("CRE_CONTEXT_ONLY", ("KRX_IDENTITY_UNIVERSE_ONLY",))
    return OrganizationCreScopeResult("CRE_CONFIRMED", ("CURATED_NON_KRX_IDENTITY",))
