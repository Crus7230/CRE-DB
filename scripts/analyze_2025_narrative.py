from __future__ import annotations

import csv
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.db"
OUT = ROOT / "reports" / "2025_local_news_disclosure_analysis"
OUT.mkdir(parents=True, exist_ok=True)

THEMES = {
    "금리": r"금리|기준금리|국고채|회사채|채권금리",
    "유동성": r"유동성|자금조달|조달시장|기관투자|투자심리|자금시장",
    "PF": r"부동산\s*PF|프로젝트파이낸싱|브릿지론|본\s*PF|대주단",
    "대출": r"대출|담보대출|인수금융|리파이낸싱|차환|만기연장|셀다운|LTV",
    "리츠": r"리츠|REITs?",
    "오피스": r"오피스|업무시설|사옥|본사이전",
    "물류센터": r"물류센터|물류창고|풀필먼트",
    "데이터센터": r"데이터센터|데이터 센터|IDC",
    "호텔": r"호텔|리조트|숙박",
    "리테일": r"리테일|상가|쇼핑몰|백화점|마트|아울렛",
    "매각/투자": r"매각|매입|매매|인수|취득|양도|투자|출자|우선협상|입찰|클로징",
}
# (기본 테마, 한정 표현): 두 패턴이 같은 문서에 있어야 하위 내러티브로 센다.
SUBTHEMES = {
    "금리_완화": ("금리", r"금리.{0,8}인하|인하.{0,8}금리|저금리|통화완화"),
    "금리_부담": ("금리", r"고금리|금리.{0,8}인상|금리 부담|이자 부담"),
    "PF_스트레스": ("PF", r"부실|연체|위기|워크아웃|구조조정|경매|공매|도산|부도|우발채무|경색"),
    "PF_정상화지원": ("PF", r"정상화|지원|재구조화|유동성 공급|보증|연착륙"),
    "오피스_임대": ("오피스", r"임대|임차|공실|렌트프리|입주|이전|임대료"),
    "오피스_공급": ("오피스", r"착공|준공|공급|개발|재개발|정비사업"),
    "물류_과잉부담": ("물류센터", r"공실|과잉|미매각|부실|경매|공급 부담|임차인 확보"),
    "데이터센터_인프라규제": ("데이터센터", r"전력|전기|인허가|허가|민원|규제|분산에너지|전력망"),
    "호텔_수요운영": ("호텔", r"관광|외국인|투숙|객실|숙박|운영|개장|브랜드"),
    "리테일_수요재편": ("리테일", r"소비|매출|공실|폐점|리뉴얼|체험|복합|온라인|유통"),
    "거래_진행": ("매각/투자", r"매각주관|예비입찰|본입찰|우선협상|매매계약|거래종결|클로징"),
}
# 제목/스니펫에 명시된 수도권 지명만 식별하는 보수적 필터.
CAPITAL = re.compile(
    r"수도권|서울|경기도|경기\s+(?:안양|성남|고양|수원|용인|화성|평택|이천)|인천|강남|서초|송파|강동|마포|용산|영등포|여의도|종로|성동|성수|"
    r"구로|금천|동작|관악|광진|잠실|상암|판교|분당|성남|과천|하남|고양|일산|김포|부천|광명|"
    r"안양|군포|의왕|수원|용인|화성|평택|안산|시흥|파주|남양주|구리|의정부|양주|포천|이천|"
    r"여주|광교|동탄|송도|청라|영종|남동|부평|계양|CBD|GBD|YBD",
    re.I,
)

def quarter(iso: str) -> str:
    m = int(iso[5:7])
    return f"2025Q{(m - 1) // 3 + 1}"

def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = list(con.execute(
        """
        SELECT dv.document_version_id, cs.source_code, dv.published_at,
               dv.title, COALESCE(dv.snippet_text,'' ) AS snippet,
               COALESCE(sd.publisher_name,'') AS publisher, sd.canonical_url
        FROM document_versions dv
        JOIN source_documents sd ON sd.document_id=dv.document_id
        JOIN collection_sources cs ON cs.source_id=sd.source_id
        WHERE cs.source_code IN ('GOOGLE_NEWS_RSS','OPENDART')
          AND dv.published_at >= '2025-01-01' AND dv.published_at < '2026-01-01'
        """
    ))
    docs = []
    for r in rows:
        d = dict(r)
        d["quarter"] = quarter(d["published_at"])
        # Google RSS snippet가 제목을 반복하는 경우가 많으므로 문서 단위 boolean만 집계한다.
        d["text"] = f'{d["title"]} {d["snippet"]}'
        # RSS 제목 끝의 " - 매체명"은 지리정보가 아니므로 수도권 판정에서 제외.
        geo_title = re.sub(rf"\s+-\s+{re.escape(d['publisher'])}\s*$", "", d["title"], flags=re.I)
        d["capital_explicit"] = bool(CAPITAL.search(geo_title))
        docs.append(d)

    source_q = Counter((d["source_code"], d["quarter"]) for d in docs)
    with (OUT / "source_quarter_counts.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["source","quarter","documents"])
        for key, n in sorted(source_q.items()): w.writerow([*key, n])

    out_rows = []
    for scope_name, subset in [
        ("전체", [d for d in docs if d["source_code"] == "GOOGLE_NEWS_RSS"]),
        ("수도권지명명시", [d for d in docs if d["source_code"] == "GOOGLE_NEWS_RSS" and d["capital_explicit"]]),
    ]:
        for q in ["2025Q1","2025Q2","2025Q3","2025Q4"]:
            qdocs = [d for d in subset if d["quarter"] == q]
            for theme, pat in THEMES.items():
                n = sum(bool(re.search(pat, d["text"], re.I)) for d in qdocs)
                out_rows.append([scope_name,q,theme,n,len(qdocs),round(100*n/len(qdocs),2) if qdocs else 0])
    with (OUT / "theme_quarter_counts.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["scope","quarter","theme","matched_docs","quarter_docs","share_pct"]);w.writerows(out_rows)

    sub_rows=[]
    gdocs=[d for d in docs if d["source_code"]=="GOOGLE_NEWS_RSS"]
    for q in ["2025Q1","2025Q2","2025Q3","2025Q4"]:
        qdocs=[d for d in gdocs if d["quarter"]==q]
        for theme,(base,pat) in SUBTHEMES.items():
            n=sum(bool(re.search(THEMES[base],d["text"],re.I)) and bool(re.search(pat,d["text"],re.I)) for d in qdocs)
            sub_rows.append([q,theme,n,len(qdocs),round(100*n/len(qdocs),2)])
    with (OUT / "subtheme_quarter_counts.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["quarter","subtheme","matched_docs","quarter_docs","share_pct"]);w.writerows(sub_rows)

    # 매크로-섹터 동시 언급: 인과가 아니라 제목/스니펫의 연관 신호.
    co_rows=[]
    for q in ["2025Q1","2025Q2","2025Q3","2025Q4"]:
        qdocs=[d for d in gdocs if d["quarter"]==q]
        for macro in ["금리","유동성","PF","대출","리츠"]:
            for sector in ["오피스","물류센터","데이터센터","호텔","리테일","매각/투자"]:
                n=sum(bool(re.search(THEMES[macro],d["text"],re.I)) and bool(re.search(THEMES[sector],d["text"],re.I)) for d in qdocs)
                co_rows.append([q,macro,sector,n])
    with (OUT / "macro_sector_cooccurrence.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["quarter","macro_theme","sector_theme","documents"]);w.writerows(co_rows)

    # 각 테마별 수도권 명시 사례. 단순·재현 가능한 순서(분기, 날짜, 제목)로 최대 12건.
    ex=[]
    for theme,pat in THEMES.items():
        candidates=[d for d in gdocs if d["capital_explicit"] and re.search(pat,d["text"],re.I)]
        per_q=defaultdict(int)
        for d in sorted(candidates,key=lambda x:(x["quarter"],x["published_at"],x["title"])):
            if per_q[d["quarter"]] < 3:
                ex.append([theme,d["quarter"],d["published_at"][:10],d["publisher"],d["title"],d["canonical_url"]])
                per_q[d["quarter"]]+=1
    with (OUT / "capital_region_examples.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["theme","quarter","date","publisher","title","url"]);w.writerows(ex)

    # DART 공시 원문 메타데이터는 제목/스니펫 수준. 분기별 유형과 제출인 집계.
    dart=[d for d in docs if d["source_code"]=="OPENDART"]
    dart_rows=[]
    for q in ["2025Q1","2025Q2","2025Q3","2025Q4"]:
        qd=[d for d in dart if d["quarter"]==q]
        title_counts=Counter(re.sub(r"^\[(?:기재|첨부)?정정\]", "[정정]", d["title"]) for d in qd)
        for title,n in title_counts.most_common(): dart_rows.append([q,title,n])
    with (OUT / "dart_quarter_report_types.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["quarter","normalized_report_title","documents"]);w.writerows(dart_rows)

    print(f"documents={len(docs)} google={len(gdocs)} dart={len(dart)}")
    print("google quarter", dict(sorted(Counter(d['quarter'] for d in gdocs).items())))
    print("dart quarter", dict(sorted(Counter(d['quarter'] for d in dart).items())))
    print("capital explicit", sum(d['capital_explicit'] for d in gdocs))
    print("wrote", OUT)

if __name__ == "__main__":
    main()
