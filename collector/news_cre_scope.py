from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence


CLASSIFIER_VERSION = "NEWS_CRE_SCOPE_RULE_V3"

_COMMERCIAL_ASSET_PATTERN = re.compile(
    r"오피스|업무시설|업무복합시설|업무용\s*빌딩|사옥|물류(?:센터|창고|단지)|"
    r"데이터\s*센터|\bIDC\b|공장|산업시설|호텔|리조트|상업시설|"
    r"리테일\s*(?:시설|센터|몰|자산|부동산)|쇼핑몰|상가|"
    r"지식산업센터|복합개발|개발부지|골프장|\bCC\b|"
    r"[가-힣A-Za-z0-9]+\s*(?:타워|센터|플라자|스퀘어)",
    re.IGNORECASE,
)
_TRANSACTION_PATTERN = re.compile(
    r"매각|매입|인수|취득|매매|거래종결|우선협상대상자|우협|"
    r"예비입찰|본입찰|매각주관사|임대차|임차|리파이낸싱|담보대출|"
    r"착공|준공|완공|사용승인|건축허가|사업시행인가|자산편입",
    re.IGNORECASE,
)
_RESIDENTIAL_PATTERN = re.compile(
    r"아파트|공동주택|단독주택|다가구|다세대|연립주택|민간임대주택|청년주택|"
    r"주택분양|아파트분양|전세|(?<![가-힣])빌라(?![가-힣])",
    re.IGNORECASE,
)
_GENERIC_PROPERTY_PATTERN = re.compile(
    r"부동산|토지|건물|빌딩|건축|개발사업|재개발|재건축|정비사업|"
    r"부동산\s*PF|(?<![A-Za-z])PF(?![A-Za-z])|프로젝트\s*파이낸싱|브릿지론|본PF",
    re.IGNORECASE,
)
_PF_PROJECT_PATTERN = re.compile(
    r"사업장|개발사업|시행사|시공사|대주단|책임준공|자금보충|채무인수|"
    r"프로젝트|(?<![A-Za-z])SPC(?![A-Za-z])|(?<![A-Za-z])PFV(?![A-Za-z])",
    re.IGNORECASE,
)
_PF_ACTION_PATTERN = re.compile(
    r"브릿지론|본\s*PF|대주단\s*구성|금융주선|만기\s*연장|차환|리파이낸싱|"
    r"재구조화|기한이익상실|(?<![A-Za-z])EOD(?![A-Za-z])|연체|부실|워크아웃|공매",
    re.IGNORECASE,
)
_NON_CRE_TRANSACTION_OBJECT_PATTERN = re.compile(
    r"(?:지분|주식|경영권|사업부|브랜드|상표권|법인|자회사|종속회사|"
    r"가상자산|암호화폐|도지코인|비트코인|알트코인|(?<![A-Za-z])DOGE(?![A-Za-z])|"
    r"(?<![A-Za-z])BTC(?![A-Za-z])|(?<![A-Za-z])ETH(?![A-Za-z])|토큰)"
    r"(?:\s*[0-9,.%억조만천백원]+)?\s*(?:전량\s*)?"
    r"(?:매각|매입|인수|취득|매매|양도|양수)",
    re.IGNORECASE,
)
_EXPLICIT_NON_CRE_PATTERN = re.compile(
    r"반도체|바이오|신약|의약품|자동차|배터리|가상자산|비트코인|코인|"
    r"(?<![가-힣])게임(?![가-힣])|엔터테인먼트|아이돌|항공기|선박",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NewsCreScopeResult:
    status_code: str
    reason_codes: tuple[str, ...]
    classifier_version: str = CLASSIFIER_VERSION


def classify_news_cre_scope(
    *,
    title: str | None,
    snippet: str | None,
    category_codes: Sequence[str] = (),
) -> NewsCreScopeResult:
    text = " ".join(part.strip() for part in (title or "", snippet or "") if part.strip())
    if not text:
        return NewsCreScopeResult("CRE_REVIEW_PARSE_FAILED", ("NEWS_FIELDS_EMPTY",))
    if _RESIDENTIAL_PATTERN.search(text) and not _COMMERCIAL_ASSET_PATTERN.search(text):
        return NewsCreScopeResult("OUT_OF_SCOPE_RESIDENTIAL", ("RESIDENTIAL_ONLY_ARTICLE",))
    if _NON_CRE_TRANSACTION_OBJECT_PATTERN.search(text):
        return NewsCreScopeResult("OUT_OF_SCOPE_NON_CRE", ("NON_CRE_TRANSACTION_OBJECT",))
    if _COMMERCIAL_ASSET_PATTERN.search(text) and _TRANSACTION_PATTERN.search(text):
        return NewsCreScopeResult("CRE_CONFIRMED", ("COMMERCIAL_ASSET_TRANSACTION",))
    categories = {str(code).strip().upper() for code in category_codes}
    if "PF" in categories and _GENERIC_PROPERTY_PATTERN.search(text) \
            and _PF_PROJECT_PATTERN.search(text) and _PF_ACTION_PATTERN.search(text):
        return NewsCreScopeResult("CRE_CONFIRMED", ("PROJECT_SPECIFIC_PF_ACTION",))
    if _EXPLICIT_NON_CRE_PATTERN.search(text) and not (
        _COMMERCIAL_ASSET_PATTERN.search(text) or _GENERIC_PROPERTY_PATTERN.search(text)
    ) and not categories.intersection({"PERMIT", "NEW_SUPPLY"}):
        return NewsCreScopeResult("OUT_OF_SCOPE_NON_CRE", ("EXPLICIT_NON_CRE_SUBJECT",))
    if _COMMERCIAL_ASSET_PATTERN.search(text):
        return NewsCreScopeResult("CRE_REVIEW", ("COMMERCIAL_CONTEXT_WITHOUT_TRANSACTION",))
    return NewsCreScopeResult("CRE_REVIEW", ("INSUFFICIENT_DIRECT_CRE_EVIDENCE",))
