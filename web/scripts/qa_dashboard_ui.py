from __future__ import annotations

import json
from pathlib import Path
import re
import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:3001"
OUT = Path(__file__).resolve().parents[2] / "artifacts" / "dashboard-qa"
OUT.mkdir(parents=True, exist_ok=True)


def wait_data(page):
    page.wait_for_load_state("networkidle", timeout=30_000)


def run_desktop(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.goto(BASE, wait_until="networkidle", timeout=60_000)
    page.get_by_role("heading", name="시장 카테고리로 찾고, 근거문서로 검증").wait_for()
    assert page.locator(".category-rail").is_visible()
    assert page.get_by_role("region", name="상세 필터").is_visible()
    page.screenshot(path=OUT / "01-market-desktop.png", full_page=True)

    page.get_by_role("button", name="문서 라이브러리 공시·공식 API·기사·공고를 출처별 구분").click()
    page.get_by_text("DOCUMENT TYPES").wait_for()
    document_types = page.locator(".document-taxonomy button").count()
    assert document_types >= 3
    page.screenshot(path=OUT / "02-documents-desktop.png", full_page=True)
    page.locator(".document-projection .projection-card > button").first.click()
    document_drawer = page.get_by_role("dialog", name="문서 상세")
    document_drawer.wait_for(timeout=30_000)
    page.get_by_role("heading", name="원문 기반 요약").wait_for(timeout=30_000)
    assert document_drawer.get_by_role("link", name=re.compile("원문 열기")).is_visible()
    page.screenshot(path=OUT / "02-document-detail-desktop.png", full_page=False)
    page.get_by_role("button", name="상세 닫기").click()
    small_transaction_toggle = page.get_by_role("checkbox", name=re.compile("1,000억원 미만 실거래 포함"))
    assert not small_transaction_toggle.is_checked()
    page.locator(".document-taxonomy").get_by_role("button", name=re.compile("공식 실거래 원자료")).click()
    page.locator(".transaction-card-template").first.wait_for(timeout=30_000)
    default_transaction_count = int(page.locator(".results-heading > strong").inner_text().replace(",", "").replace("건", ""))
    small_transaction_toggle.check()
    page.wait_for_function("count => Number(document.querySelector('.results-heading > strong').textContent.replace(/[^0-9]/g,'')) > count", arg=default_transaction_count)
    expanded_transaction_count = int(page.locator(".results-heading > strong").inner_text().replace(",", "").replace("건", ""))
    small_transaction_toggle.uncheck()
    page.wait_for_function("count => Number(document.querySelector('.results-heading > strong').textContent.replace(/[^0-9]/g,'')) === count", arg=default_transaction_count)
    page.screenshot(path=OUT / "02-transactions-desktop.png", full_page=True)
    page.locator(".transaction-projection-card > button").first.click()
    page.locator(".transaction-detail-template").wait_for(timeout=30_000)
    page.screenshot(path=OUT / "02-transaction-detail-desktop.png", full_page=False)
    page.get_by_role("button", name="상세 닫기").click()

    page.get_by_role("button", name="시장 이벤트 매각·임대·공급·인허가·PF·대출·투자").click()
    page.locator(".event-projection .projection-card > button").first.wait_for(timeout=30_000)
    page.locator(".event-projection .projection-card > button").first.click()
    page.get_by_role("dialog", name="이벤트 상세").wait_for(timeout=30_000)
    page.locator(".entity-overview").wait_for(timeout=30_000)
    page.screenshot(path=OUT / "02-event-detail-desktop.png", full_page=False)
    page.get_by_role("button", name="상세 닫기").click()

    page.get_by_role("button", name="자산 이벤트와 연결된 canonical asset").click()
    page.locator(".asset-projection .projection-card > button").first.wait_for(timeout=30_000)
    page.locator(".asset-projection .projection-card > button").first.click()
    page.get_by_role("dialog", name="자산 상세").wait_for(timeout=30_000)
    page.locator(".entity-overview").wait_for(timeout=30_000)
    page.screenshot(path=OUT / "02-asset-detail-desktop.png", full_page=False)
    page.get_by_role("button", name="상세 닫기").click()

    page.get_by_role("button", name="회사·임차 시총·업종·관계").click()
    page.locator(".company-table tbody tr").first.wait_for(timeout=30_000)
    company_rows = page.locator(".company-table tbody tr").count()
    assert company_rows >= 5
    page.locator(".company-link").first.click()
    page.get_by_role("dialog", name="회사 360 상세").wait_for(timeout=30_000)
    page.locator(".drawer-tabs").wait_for(timeout=30_000)
    page.get_by_role("button", name=re.compile(r"^문서")).click()
    page.screenshot(path=OUT / "03-company-360-desktop.png", full_page=False)
    page.get_by_role("button", name="상세 닫기").click()

    page.get_by_role("button", name="기관자금 Mandate·선정·집행").click()
    page.locator(".capital-workspace .domain-card").first.wait_for(timeout=30_000)
    capital_cards = page.locator(".capital-workspace .domain-card").count()
    page.locator(".capital-workspace .domain-card").first.click()
    page.screenshot(path=OUT / "04-capital-desktop.png", full_page=True)

    page.get_by_role("button", name="매각절차 입찰·우협·종결").click()
    page.locator(".sale-workspace .domain-card").first.wait_for(timeout=30_000)
    sale_cards = page.locator(".sale-workspace .domain-card").count()
    page.locator(".sale-workspace .domain-card").first.click()
    page.screenshot(path=OUT / "05-sale-desktop.png", full_page=True)
    result = {
        "marketCategoryRail": True,
        "filterRegion": True,
        "documentTypes": document_types,
        "documentDetail": True,
        "transactionTemplate": True,
        "defaultTransactions1000EokPlus": default_transaction_count,
        "transactionsIncludingUnder1000Eok": expanded_transaction_count,
        "eventDetail": True,
        "assetDetail": True,
        "companyRows": company_rows,
        "companyDrawer": True,
        "capitalCards": capital_cards,
        "saleCards": sale_cards,
    }
    page.close()
    return result


def run_mobile(browser):
    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    page.goto(BASE, wait_until="networkidle", timeout=60_000)
    page.get_by_role("heading", name="시장 카테고리로 찾고, 근거문서로 검증").wait_for()
    metrics = page.evaluate("() => ({clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth})")
    page.screenshot(path=OUT / "06-market-mobile.png", full_page=True)
    assert metrics["scrollWidth"] <= metrics["clientWidth"]
    page.locator(".document-projection .projection-card > button").first.click()
    document_drawer = page.get_by_role("dialog", name="문서 상세")
    document_drawer.wait_for(timeout=30_000)
    page.get_by_role("heading", name="원문 기반 요약").wait_for(timeout=30_000)
    assert document_drawer.bounding_box()["width"] <= 390
    page.screenshot(path=OUT / "06-document-detail-mobile.png", full_page=False)
    page.get_by_role("button", name="상세 닫기").click()
    page.locator(".document-taxonomy").get_by_role("button", name=re.compile("공식 실거래 원자료")).click()
    page.locator(".transaction-card-template").first.wait_for(timeout=30_000)
    page.locator(".transaction-projection-card > button").first.click()
    transaction_drawer = page.get_by_role("dialog", name="문서 상세")
    page.locator(".transaction-detail-template").wait_for(timeout=30_000)
    assert transaction_drawer.bounding_box()["width"] <= 390
    page.screenshot(path=OUT / "06-transaction-detail-mobile.png", full_page=False)
    page.get_by_role("button", name="상세 닫기").click()
    page.get_by_role("button", name="시장 이벤트 매각·임대·공급·인허가·PF·대출·투자").click()
    page.locator(".event-projection .projection-card > button").first.wait_for(timeout=30_000)
    page.locator(".event-projection .projection-card > button").first.click()
    event_drawer = page.get_by_role("dialog", name="이벤트 상세")
    event_drawer.wait_for(timeout=30_000)
    page.locator(".entity-overview").wait_for(timeout=30_000)
    assert event_drawer.bounding_box()["width"] <= 390
    page.screenshot(path=OUT / "06-event-detail-mobile.png", full_page=False)
    page.get_by_role("button", name="상세 닫기").click()
    page.get_by_role("button", name="회사·임차 시총·업종·관계").click()
    page.locator(".company-table tbody tr").first.wait_for(timeout=30_000)
    page.screenshot(path=OUT / "06-company-mobile.png", full_page=True)
    page.locator(".company-link").first.click()
    drawer = page.get_by_role("dialog", name="회사 360 상세")
    drawer.wait_for(timeout=30_000)
    page.locator(".drawer-tabs").wait_for(timeout=30_000)
    assert drawer.bounding_box()["width"] <= 390
    page.get_by_role("button", name=re.compile(r"^문서")).click()
    page.screenshot(path=OUT / "07-company-drawer-mobile.png", full_page=False)
    page.close()
    return {"viewport": "390x844", "clientWidth": metrics["clientWidth"], "scrollWidth": metrics["scrollWidth"], "horizontalFit": True, "drawerFit": True}


started = time.perf_counter()
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    report = {"desktop": run_desktop(browser), "mobile": run_mobile(browser)}
    browser.close()
report["elapsedSeconds"] = round(time.perf_counter() - started, 2)
report["screenshots"] = sorted(path.name for path in OUT.glob("*.png"))
(OUT / "qa-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
