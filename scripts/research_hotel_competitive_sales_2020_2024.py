from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

QUERIES = [
    # known/adjacent-year leads
    "밀레니엄 서울 힐튼 매각 2020 2021 2022",
    "르메르디앙 서울 매각 본입찰 우선협상 2020 2021",
    "쉐라톤 서울 팔래스 강남 매각 본입찰 2020 2021",
    "신라스테이 마포 매각 키움 2023",
    "그래비티 조선 서울 판교 매각 퍼시픽 2024",
    "글래드호텔 3곳 매각 그래비티 GIC 2024",
    "그랜드 하얏트 서울 매각 2023 본입찰",
    "IFC 서울 매각 콘래드 호텔 본입찰 2022",
    "신라스테이 해운대 매각 2022 에비슨영 딜로이트",
    "파르나스호텔 제주 매각 자문 RFP 2024",
    # generic national discovery
    "호텔 매각 본입찰 우선협상대상자 2020",
    "호텔 매각 본입찰 우선협상대상자 2021",
    "호텔 매각 본입찰 우선협상대상자 2022",
    "호텔 매각 본입찰 우선협상대상자 2023",
    "호텔 매각 본입찰 우선협상대상자 2024",
    "호텔 매각 우협 무산 재매각 2020",
    "호텔 매각 우협 무산 재매각 2021",
    "호텔 매각 우협 무산 재매각 2022",
    "호텔 매각 우협 무산 재매각 2023",
    "호텔 매각 우협 무산 재매각 2024",
    # regions
    "부산 호텔 매각 본입찰 우협 2020 2021 2022 2023 2024",
    "울산 경남 호텔 매각 본입찰 우협 2020 2021 2022 2023 2024",
    "광주 전북 전남 호텔 리조트 매각 입찰 2020 2021 2022 2023 2024",
    "대전 세종 충북 충남 호텔 매각 입찰 2020 2021 2022 2023 2024",
    "대구 경북 호텔 매각 본입찰 우협 2020 2021 2022 2023 2024",
    "강원 호텔 리조트 매각 본입찰 우협 2020 2021 2022 2023 2024",
    "제주 호텔 리조트 매각 본입찰 우협 2020 2021 2022 2023 2024",
    "인천 호텔 매각 본입찰 우협 2020 2021 2022 2023 2024",
    "경기 호텔 매각 본입찰 우협 2020 2021 2022 2023 2024",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
NAVER_HOSTS = {"search.naver.com", "keep.naver.com", "help.naver.com", "www.naver.com"}


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def harvest(query: str, session: requests.Session) -> dict:
    url = "https://search.naver.com/search.naver?" + urllib.parse.urlencode(
        {
            "where": "news",
            "pd": "3",
            "ds": "2020.01.01",
            "de": "2026.12.31",
            "query": query,
        }
    )
    response = session.get(url, headers={"User-Agent": UA}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        parsed = urllib.parse.urlparse(href)
        if parsed.scheme not in {"http", "https"} or parsed.netloc in NAVER_HOSTS:
            continue
        title = compact(anchor.get_text(" ", strip=True))
        if not title or title == "새 창 열림" or href in seen:
            continue
        parent = anchor
        for _ in range(5):
            if parent.parent is None:
                break
            parent = parent.parent
            text = compact(parent.get_text(" ", strip=True))
            if 80 <= len(text) <= 1200:
                break
        context = compact(parent.get_text(" ", strip=True))[:1500]
        seen.add(href)
        results.append({"title_or_span": title[:500], "url": href, "search_context": context})
    return {"query": query, "search_url": url, "http_status": response.status_code, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--delay", type=float, default=0.35)
    args = parser.parse_args()
    session = requests.Session()
    out = []
    for i, query in enumerate(QUERIES, 1):
        try:
            out.append(harvest(query, session))
            print(f"[{i}/{len(QUERIES)}] {query}: {len(out[-1]['results'])}")
        except Exception as exc:
            out.append({"query": query, "error": type(exc).__name__ + ": " + str(exc), "results": []})
            print(f"[{i}/{len(QUERIES)}] ERROR {query}: {exc}")
        time.sleep(args.delay)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "NAVER news-search discovery only; title/snippet results are REVIEW_ONLY unless article full text is separately opened",
        "date_filter": ["2020-01-01", "2026-12-31"],
        "queries": out,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {args.output}")


if __name__ == "__main__":
    main()
