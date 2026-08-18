import html
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from html.parser import HTMLParser

ASSETS = [
    "현대그룹 연지동 사옥",
    "당산 TCC동양타워",
    "현대차증권빌딩",
    "광화문 크레센도빌딩",
    "강남 삼성동빌딩",
    "논현 두산건설 사옥",
    "현대모비스 본사 사옥",
    "AP타워",
    "공평동 G1 오피스",
]
SUFFIXES = [
    "매각",
    "본입찰",
    "우선협상대상자",
    "입찰가",
    "매각자문사",
    "인수금융",
    "매매계약",
    "거래종결",
    "무산 재입찰",
]

class ResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.depth = 0
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("data-heatmap-target") in (".tit", ".body"):
            self.current = {"kind": attrs["data-heatmap-target"], "url": attrs.get("href", ""), "text": []}
            self.depth = 1
        elif self.current is not None and tag == "a":
            self.depth += 1

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if self.current is not None and tag == "a":
            self.depth -= 1
            if self.depth == 0:
                self.items.append(self.current)
                self.current = None


def parse(text: str):
    p = ResultParser(); p.feed(text)
    out=[]; pending=None
    for item in p.items:
        item["text"] = re.sub(r"\s+", " ", "".join(item["text"])).replace("새 창 열림", "").strip()
        if item["kind"] == ".tit":
            pending = {"url": html.unescape(item["url"]), "title": item["text"], "snippet": ""}
            out.append(pending)
        elif item["kind"] == ".body" and pending and pending["url"] == html.unescape(item["url"]):
            pending["snippet"] = item["text"]
    seen=set(); uniq=[]
    for r in out:
        k=(r['url'],r['title'])
        if k not in seen:
            seen.add(k); uniq.append(r)
    return uniq

def main():
    session=requests.Session(); session.headers['User-Agent']='Mozilla/5.0'
    all_rows=[]
    for asset in ASSETS:
        for suffix in SUFFIXES:
            q=f'{asset} {suffix}'
            url='https://search.naver.com/search.naver?where=news&query='+quote(q)
            text=session.get(url,timeout=30).text
            rows=parse(text)
            all_rows.append({"asset":asset,"query":q,"search_url":url,"results":rows[:20]})
            print(asset, suffix, len(rows))
            time.sleep(0.15)
    p=Path('artifacts/bid-process-2025-search-results.json')
    p.write_text(json.dumps(all_rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print('wrote',p)
if __name__=='__main__': main()
