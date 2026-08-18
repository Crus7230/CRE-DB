"""Evidence-preserving candidate extraction for competitive real-estate sales.

This module never creates canonical events. It emits review candidates from title/snippet
text and preserves source spans, comparators and uncertainty.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class MoneyMention:
    raw_value: str
    normalized_krw_decimal: str
    comparator_code: str
    evidence_start: int
    evidence_end: int


@dataclass(frozen=True)
class RankMention:
    raw_value: str
    rank: int
    evidence_start: int
    evidence_end: int


@dataclass(frozen=True)
class OrganizationMention:
    raw_value: str
    normalized_text: str
    evidence_start: int
    evidence_end: int


@dataclass(frozen=True)
class BidProcessCandidate:
    combined_text: str
    asset_types: tuple[str, ...]
    region_groups: tuple[str, ...]
    stage_signals: tuple[str, ...]
    participation_signals: tuple[str, ...]
    advisor_signals: tuple[str, ...]
    funding_signals: tuple[str, ...]
    money_mentions: tuple[MoneyMention, ...]
    reported_ranks: tuple[RankMention, ...]
    organization_mentions: tuple[OrganizationMention, ...]
    requires_review: bool = True

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def load_geography_policy(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


ASSET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OFFICE", re.compile(r"오피스|업무시설|업무용\s*빌딩|사옥|빌딩")),
    ("HOTEL", re.compile(r"호텔|리조트|관광숙박|콘도")),
    ("LOGISTICS", re.compile(r"물류(?:센터|창고)|풀필먼트|저온창고|냉동창고|배송센터")),
    ("DATA_CENTER", re.compile(r"데이터\s*센터|데이터센터|IDC|AI\s*센터", re.I)),
)

STAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ADVISOR_SELECTED", re.compile(r"매각(?:주관|자문)사.{0,15}(?:선정|낙점)|매각(?:주관|자문)사로")),
    ("MARKETING_STARTED", re.compile(r"매각\s*(?:절차|작업|마케팅).{0,10}(?:착수|개시|본격화)|IM\s*배포", re.I)),
    ("PRELIMINARY_BID", re.compile(r"예비입찰|인수의향서|LOI\s*(?:접수|제출)", re.I)),
    ("SHORTLISTED", re.compile(r"숏리스트|쇼트리스트|적격인수후보")),
    ("FINAL_BID", re.compile(r"본입찰|최종입찰|최종\s*입찰")),
    ("PREFERRED_BIDDER_SELECTED", re.compile(r"우선협상대상자|우협(?:자로|에|\s*선정)|우협\s*선정")),
    ("MOU_SIGNED", re.compile(r"(?:MOU|양해각서).{0,10}(?:체결|서명)", re.I)),
    ("DUE_DILIGENCE", re.compile(r"인수\s*실사|정밀실사|가격\s*협상|우협.{0,12}협상")),
    ("SPA_SIGNED", re.compile(r"(?:SPA|주식매매계약|부동산매매계약|매매계약).{0,10}(?:체결|서명)", re.I)),
    ("CONDITIONS_PENDING", re.compile(r"선행조건|기업결합승인|인허가.{0,8}(?:대기|조건)")),
    ("CLOSED", re.compile(r"잔금\s*(?:납입|지급)\s*완료|소유권\s*이전|거래\s*종결\s*(?:완료|성사|했다)|클로징\s*완료")),
    ("SALE_FAILED", re.compile(r"협상\s*결렬|매각\s*무산|인수\s*무산|계약\s*해제|거래\s*무산")),
    ("SALE_WITHDRAWN", re.compile(r"매각\s*(?:철회|중단|보류)")),
    ("REBID", re.compile(r"재입찰|재매각|다시\s*매물|매각\s*재개")),
)

PARTICIPATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRELIMINARY_BID_SUBMITTED", re.compile(r"예비입찰.{0,20}(?:참여|제출)|인수의향서.{0,10}제출")),
    ("FINAL_BID_SUBMITTED", re.compile(r"본입찰.{0,20}(?:참여|제출|써내)|최종입찰.{0,20}(?:참여|제출|써내)")),
    ("WITHDREW", re.compile(r"입찰.{0,12}(?:철회|불참)|인수전.{0,10}이탈")),
    ("INTEREST_REPORTED", re.compile(r"인수\s*검토|입찰\s*참여.{0,8}검토|관심을\s*보")),
)

ADVISOR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SELL_SIDE_ADVISOR", re.compile(r"매각주관사|매각자문사|매도측\s*자문")),
    ("LEGAL_ADVISOR", re.compile(r"법률자문사|법무법인.{0,12}자문")),
    ("DEBT_ARRANGER", re.compile(r"인수금융\s*주선|금융주관사|대출\s*주선")),
)

FUNDING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("BLIND_FUND_EQUITY", re.compile(r"블라인드\s*펀드")),
    ("PROJECT_FUND_EQUITY", re.compile(r"프로젝트\s*펀드|프로젝트형\s*펀드")),
    ("REIT_EQUITY", re.compile(r"리츠|REIT", re.I)),
    ("LP_EQUITY", re.compile(r"기관\s*LP|출자자|에쿼티|지분\s*투자")),
    ("CO_INVESTMENT", re.compile(r"공동투자|코인베스트|컨소시엄")),
    ("ACQUISITION_DEBT", re.compile(r"인수금융|담보대출|대주단")),
    ("BRIDGE_DEBT", re.compile(r"브릿지론|브리지론")),
    ("OWN_BALANCE_SHEET", re.compile(r"자기자본|고유계정|자체자금")),
)

ORG_PATTERN = re.compile(
    r"(?:[가-힣A-Za-z0-9&·]+(?:자산운용|투자운용|증권|은행|보험|캐피탈|리츠|펀드|컨소시엄|공사|그룹|법무법인))"
)
RANK_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*위(?!\d)")
COMBINED_MONEY_PATTERN = re.compile(r"(?P<qual>약|대략|최소|최대)?\s*(?P<jo>[\d,.]+)\s*조\s*(?P<eok>[\d,.]+)\s*억\s*원")
SIMPLE_MONEY_PATTERN = re.compile(r"(?P<qual>약|대략|최소|최대|이상|이하)?\s*(?P<num>[\d,.]+)\s*(?P<unit>조원|억원|만원|원)")


def _comparator(qual: str | None) -> str:
    return {
        "약": "ABOUT", "대략": "ABOUT", "최소": "AT_LEAST", "이상": "AT_LEAST",
        "최대": "AT_MOST", "이하": "AT_MOST",
    }.get((qual or "").strip(), "EXACT")


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _money_mentions(text: str) -> tuple[MoneyMention, ...]:
    found: list[MoneyMention] = []
    occupied: list[tuple[int, int]] = []
    for m in COMBINED_MONEY_PATTERN.finditer(text):
        jo = Decimal(m.group("jo").replace(",", ""))
        eok = Decimal(m.group("eok").replace(",", ""))
        value = jo * Decimal("1000000000000") + eok * Decimal("100000000")
        found.append(MoneyMention(m.group(0), _decimal_text(value), _comparator(m.group("qual")), m.start(), m.end()))
        occupied.append((m.start(), m.end()))
    multipliers = {"조원": Decimal("1000000000000"), "억원": Decimal("100000000"), "만원": Decimal("10000"), "원": Decimal("1")}
    for m in SIMPLE_MONEY_PATTERN.finditer(text):
        if any(m.start() < e and m.end() > s for s, e in occupied):
            continue
        value = Decimal(m.group("num").replace(",", "")) * multipliers[m.group("unit")]
        found.append(MoneyMention(m.group(0), _decimal_text(value), _comparator(m.group("qual")), m.start(), m.end()))
    return tuple(sorted(found, key=lambda x: x.evidence_start))


def _region_groups(text: str, policy: dict[str, Any]) -> tuple[str, ...]:
    found: list[str] = []
    for code, row in policy.get("regionGroups", {}).items():
        if any(term and term in text for term in row.get("terms", [])):
            found.append(code)
    return tuple(found)


def _signals(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> tuple[str, ...]:
    return tuple(code for code, pattern in patterns if pattern.search(text))


def extract_bid_process_candidate(
    title: str | None,
    snippet: str | None,
    geography_policy: dict[str, Any],
) -> BidProcessCandidate | None:
    # Google News RSS appends `` - publisher`` (sometimes another descriptor)
    # to the headline. Publisher names must not become asset geography or parties.
    title = (title or "").split(" - ", 1)[0].strip()
    snippet = snippet or ""
    # Google RSS descriptions frequently repeat the cleaned headline followed
    # only by the publisher. Treat that as duplicate metadata, not evidence.
    if title and snippet.startswith(title):
        snippet = ""
    combined = title if not snippet else f"{title}\n{snippet}"
    asset_types = tuple(code for code, pattern in ASSET_PATTERNS if pattern.search(combined))
    stages = _signals(combined, STAGE_PATTERNS)
    participation = list(_signals(combined, PARTICIPATION_PATTERNS))
    # A submitted bid is stronger than a generic interest expression in the same document.
    if any(s.endswith("BID_SUBMITTED") for s in participation) and "INTEREST_REPORTED" in participation:
        participation.remove("INTEREST_REPORTED")
    advisors = _signals(combined, ADVISOR_PATTERNS)
    funding = _signals(combined, FUNDING_PATTERNS)
    if not asset_types or not (stages or participation or advisors or funding):
        return None
    ranks = tuple(
        RankMention(m.group(0), int(m.group(1)), m.start(), m.end())
        for m in RANK_PATTERN.finditer(combined)
    )
    organizations = tuple(
        OrganizationMention(m.group(0), re.sub(r"\s+", "", m.group(0)), m.start(), m.end())
        for m in ORG_PATTERN.finditer(combined)
    )
    return BidProcessCandidate(
        combined_text=combined,
        asset_types=asset_types,
        region_groups=_region_groups(combined, geography_policy),
        stage_signals=stages,
        participation_signals=tuple(participation),
        advisor_signals=advisors,
        funding_signals=funding,
        money_mentions=_money_mentions(combined),
        reported_ranks=ranks,
        organization_mentions=organizations,
        requires_review=True,
    )
