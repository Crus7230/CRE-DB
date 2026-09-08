import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:3002";
const outDir = path.resolve("../artifacts/redesign-qa");
await fs.mkdir(outDir, { recursive: true });

const metric = (value, previousValue, yearAgoValue, momPct, yoyPct, ytdValue, priorYtdValue, ytdYoyPct) => ({
  value, previousValue, yearAgoValue, momPct, yoyPct, ytdValue, priorYtdValue, ytdYoyPct,
});
const trend = Array.from({ length: 19 }, (_, index) => {
  const month = new Date(Date.UTC(2025, index, 1));
  const period = `${month.getUTCFullYear()}-${String(month.getUTCMonth() + 1).padStart(2, "0")}`;
  if (index === 17) return { period, transactionCount: 14, amountKrw: "1835841880000", areaM2: "176661.22", sourceRowCount: 14, uniquePayloadCount: 14 };
  if (index === 18) return { period, transactionCount: 12, amountKrw: "2203495600000", areaM2: "250983.21", sourceRowCount: 13, uniquePayloadCount: 12 };
  return { period, transactionCount: 0, amountKrw: "0", areaM2: "0", sourceRowCount: 0, uniquePayloadCount: 0 };
});
const marketPulse = {
  generatedAt: "2026-09-07T02:00:00.000Z", asOfPeriod: "2026-07",
  call: {
    headline: "거래금액은 늘었지만 건수는 줄어, 대형 거래 중심의 회복입니다",
    detail: "신고 거래금액 +20.0% · 고유 신고행 -14.3% · 신고행당 평균 +40.0%",
    caution: "면적당 금액은 동일자산 가격지수가 아닙니다.",
  },
  metrics: {
    amount: metric(2203495600000, 1835841880000, 1793915590000, 20.03, 22.83, 7537424030000, 6779917280000, 11.17),
    count: metric(12, 14, 13, -14.29, -7.69, 64, 44, 45.45),
    area: metric(250983.21, 176661.22, 202505.6, 42.07, 23.94, 849627.81, 700436.39, 21.3),
    averageTicket: { value: 183624633333.33, previousValue: 131131562857.14, yearAgoValue: 137993506923.08, momPct: 40.03, yoyPct: 33.07 },
    unitAmount: { value: 8779454.21, previousValue: 10391878.19, yearAgoValue: 8858597.44, momPct: -15.52, yoyPct: -0.89 },
  },
  trend,
  concentration: {
    topGroups: [
      { rank: 1, dealDate: "2026-07-16", district: "강남구", locality: "역삼동", buildingUse: "업무", amountKrw: "500000000000", areaM2: "32685.65", sharePct: 22.69 },
      { rank: 2, dealDate: "2026-07-17", district: "영등포구", locality: "여의도동", buildingUse: "업무", amountKrw: "400000000000", areaM2: "30000", sharePct: 18.15 },
      { rank: 3, dealDate: "2026-07-18", district: "강남구", locality: "삼성동", buildingUse: "판매", amountKrw: "300000000000", areaM2: "25000", sharePct: 13.61 },
      { rank: 4, dealDate: "2026-07-19", district: "서초구", locality: "서초동", buildingUse: "업무", amountKrw: "200000000000", areaM2: "20000", sharePct: 9.08 },
      { rank: 5, dealDate: "2026-07-20", district: "송파구", locality: "잠실동", buildingUse: "판매", amountKrw: "100000000000", areaM2: "15000", sharePct: 4.54 },
    ],
    districts: [{ district: "영등포구", transactionCount: 12, amountKrw: "2203495600000", areaM2: "250983.21", sharePct: 100 }],
  },
  quality: { sourceRowCount: 13, transactionCount: 12, uniquePayloadCount: 12, exactDuplicateRows: 1 },
  scope: { geography: "서울특별시", source: "국토교통부 실거래 공개시스템", population: "비주거용 부동산 실거래", areaRule: "개별 API 행 건물면적 > 3,300㎡", exclusions: ["취소 신고", "주거용", "동일 API payload 중복"], amountBasis: "신고 거래금액 · 원 단위 환산" },
};

const daily = {
  selectedDate: "2026-09-07", latestAvailableDate: "2026-09-07", lastCollectedAt: "2026-09-07T06:40:00Z", generatedAt: "2026-09-07T06:42:00Z", total: 3, returned: 3,
  articles: [
    { id: "doc-1", title: "서울 핵심권역 오피스 매각 입찰 본격화", publisher: "마켓인사이트", publishedAt: "2026-09-07T05:20:00Z", collectedAt: "2026-09-07T06:40:00Z", summary: "강남과 여의도 주요 오피스의 입찰 일정과 원매자 구도가 구체화됐습니다.", summaryMode: "BODY_EXTRACTIVE", summaryGeneratedAt: "2026-09-07T06:41:00Z", href: null, topics: [{ key: "SALE", label: "매각", status: "CONFIRMED", provenance: "APPROVED_CLASSIFICATION" }], documentPurpose: { code: "PROCESS_EVIDENCE", label: "절차·공고 근거" }, evidenceGrade: { code: "MEDIA_DIRECT", label: "직접 보도" } },
    { id: "doc-2", title: "기관투자자 국내 코어 자산 집행 재개", publisher: "부동산금융뉴스", publishedAt: "2026-09-07T03:10:00Z", collectedAt: "2026-09-07T06:35:00Z", summary: "상반기 선정된 위탁운용사의 첫 투자 검토가 확인됐습니다.", summaryMode: "BODY_EXTRACTIVE", summaryGeneratedAt: "2026-09-07T06:36:00Z", href: null, topics: [{ key: "EQUITY_INVESTMENT", label: "지분투자", status: "CANDIDATE", provenance: "PENDING_CLASSIFICATION" }], documentPurpose: { code: "MARKET_EVIDENCE", label: "시장동향 근거" }, evidenceGrade: { code: "MEDIA_DIRECT", label: "직접 보도" } },
    { id: "doc-3", title: "데이터센터 개발사업 본PF 약정 체결", publisher: "건설경제", publishedAt: "2026-09-07T01:40:00Z", collectedAt: "2026-09-07T06:30:00Z", summary: "수도권 데이터센터 개발사업이 본PF 조달을 마쳤습니다.", summaryMode: "BODY_EXTRACTIVE", summaryGeneratedAt: "2026-09-07T06:31:00Z", href: null, topics: [{ key: "PF", label: "프로젝트금융", status: "CONFIRMED", provenance: "APPROVED_CLASSIFICATION" }], documentPurpose: { code: "TRANSACTION_EVIDENCE", label: "거래·가격 근거" }, evidenceGrade: { code: "MEDIA_DIRECT", label: "직접 보도" } },
  ],
};

const keywords = {
  generatedAt: "2026-09-07T06:45:00Z", algorithmVersion: "KO_TITLE_PHRASE_DF_V1", computedAt: "2026-09-07T06:45:00Z", windowStart: "2026-08-10", windowEnd: "2026-09-07", latestDate: "2026-09-07",
  summary: { keywordCount: 3, observationCount: 46, qualifiedKeywordCount: 3, excludedMissingPublicationCount: 2 },
  keywords: [
    { keywordId: "kw-1", term: "데이터센터", termKind: "TOKEN", isCollectionBias: false, documentFrequency: 12, baselineDocumentFrequency: 3, burstScore: 4.0, trend: [{ date: "2026-09-05", documentFrequency: 3 }, { date: "2026-09-06", documentFrequency: 7 }, { date: "2026-09-07", documentFrequency: 12 }], cooccurrences: [{ term: "전력", documentFrequency: 8 }] },
    { keywordId: "kw-2", term: "매각 입찰", termKind: "PHRASE", isCollectionBias: false, documentFrequency: 9, baselineDocumentFrequency: 4, burstScore: 2.25, trend: [{ date: "2026-09-05", documentFrequency: 4 }, { date: "2026-09-06", documentFrequency: 6 }, { date: "2026-09-07", documentFrequency: 9 }], cooccurrences: [{ term: "우선협상대상자", documentFrequency: 5 }] },
    { keywordId: "kw-3", term: "기관자금", termKind: "TOKEN", isCollectionBias: false, documentFrequency: 6, baselineDocumentFrequency: 3, burstScore: 2.0, trend: [{ date: "2026-09-05", documentFrequency: 2 }, { date: "2026-09-06", documentFrequency: 4 }, { date: "2026-09-07", documentFrequency: 6 }], cooccurrences: [{ term: "위탁운용사", documentFrequency: 4 }] },
  ],
};

const evidence = (documentId, title, rank) => ({ targetKind: "DOCUMENT", targetId: documentId, documentId, documentVersionId: `${documentId}-v1`, title, sourceName: rank === 1 ? "마켓인사이트" : "부동산금융뉴스", publishedAt: "2026-09-07T05:20:00Z", canonicalUrl: null, role: rank === 1 ? "TRIGGER" : "SUPPORTING", rank });
const insights = {
  generatedAt: "2026-09-07T06:46:00Z", algorithmVersion: "EVIDENCE_LINKED_SIGNAL_V2", statusCounts: [{ status: "UNREVIEWED", count: 2 }, { status: "APPROVED", count: 1 }],
  signals: [
    { signalId: "sig-1", signalType: "PROCESS_STAGE_CHANGE", signalDate: "2026-09-07", title: "강남 오피스 매각이 입찰 단계로 진입", summary: "입찰 일정과 복수 원매자 참여가 서로 다른 두 출처에서 새로 확인됐습니다.", reviewStatus: "UNREVIEWED", severity: "HIGH", scores: { strength: 0.91, evidence: 0.86, sourceDiversity: 0.8, confidence: 0.88 }, syndicationDedupeStatus: "DEDUPED", evidence: [evidence("doc-1", "서울 핵심권역 오피스 매각 입찰 본격화", 1), evidence("doc-2", "기관투자자 국내 코어 자산 집행 재개", 2)] },
    { signalId: "sig-2", signalType: "CAPITAL_DEPLOYMENT", signalDate: "2026-09-07", title: "선정 운용사의 후속 집행 정황 확인", summary: "기관 출자 프로그램과 운용사의 투자 검토 문서가 연결돼 선정 이후 집행 가능성이 높아졌습니다.", reviewStatus: "UNREVIEWED", severity: "MEDIUM", scores: { strength: 0.78, evidence: 0.72, sourceDiversity: 0.7, confidence: 0.74 }, syndicationDedupeStatus: "DEDUPED", evidence: [evidence("doc-2", "기관투자자 국내 코어 자산 집행 재개", 1)] },
  ],
};

const categoryIndex = {
  groups: [
    { group: "EVENT_CATEGORY", label: "시장 변화", kind: "EVENT", items: [{ key: "SALE", label: "매각", itemCount: 16 }, { key: "PF", label: "PF", itemCount: 8 }, { key: "LEASE", label: "임대차", itemCount: 11 }] },
    { group: "DOCUMENT_PURPOSE", classificationScheme: "DOCUMENT_PURPOSE", label: "근거 목적", kind: "DOCUMENT", targetKinds: ["DOCUMENT"], countSemantics: "SERVING_TARGETS", items: [{ key: "TRANSACTION_EVIDENCE", label: "거래·가격 근거", itemCount: 142 }, { key: "MARKET_EVIDENCE", label: "시장동향 근거", itemCount: 86 }, { key: "PROCESS_EVIDENCE", label: "절차·공고 근거", itemCount: 39 }] },
    { group: "ASSET_CLASS", label: "자산 유형", kind: "ASSET", items: [{ key: "OFFICE", label: "오피스", itemCount: 74 }, { key: "LOGISTICS", label: "물류", itemCount: 31 }, { key: "DATA_CENTER", label: "데이터센터", itemCount: 18 }] },
  ], generatedAt: "2026-09-07T06:45:00Z", elapsedMs: 18, database: "turso-libsql",
};

const searchResult = {
  request: { q: "강남 오피스", kind: "ALL", category: "", classificationScheme: "", from: null, to: null, page: 1, pageSize: 50, includeTransactionsUnder1000Eok: false },
  results: [
    { kind: "EVENT", id: "evt-1", title: "강남권 A급 오피스 매각 입찰 진행", subtitle: "매각 · BID", summary: "티헤란로 권역 자산의 1차 입찰이 시작됐습니다.", date: "2026-09-06", status: "ACTIVE", confidence: 0.91, source: "canonical event", href: null, category: "SALE", categoryLabel: "매각", metadata: { assets: "역삼 프라임타워", participants: "매도자 A · 원매자 4곳" } },
    { kind: "DOCUMENT", id: "doc-1", title: "서울 핵심권역 오피스 매각 입찰 본격화", subtitle: "마켓인사이트 · ARTICLE", summary: "입찰 일정과 원매자 구도가 확인된 직접 보도입니다.", date: "2026-09-07", status: "ACCESSIBLE", confidence: null, source: "마켓인사이트", href: null, category: "ARTICLE", categoryLabel: "시장기사", metadata: { documentType: "ARTICLE", documentPurposeLabel: "절차·공고 근거", evidenceGradeLabel: "직접 보도" } },
    { kind: "ASSET", id: "asset-1", title: "역삼 프라임타워", subtitle: "오피스 · 서울 강남구", summary: "서울 강남구 테헤란로", date: "2026-09-06", status: "ACTIVE", confidence: null, source: "asset master", href: null, category: "OFFICE", categoryLabel: "오피스", metadata: { assetClass: "OFFICE", region: "서울 강남구" } },
  ],
  facets: { EVENT: 1, ASSET: 1, ORGANIZATION: 0, DOCUMENT: 1, LP_MANDATE: 0, SALE_PROCESS: 0 }, total: 3, elapsedMs: 42, generatedAt: "2026-09-07T06:45:00Z", database: "turso-libsql",
};

const macro = {
  generatedAt: "2026-09-07T06:45:00Z", availableFrom: "2026-06", availableThrough: "2026-09", completeThrough: "2026-08",
  series: [{ code: "BOK_BASE_RATE_MONTHLY", name: "한국은행 기준금리", group: "KOREA", source: "한국은행 ECOS", unit: "PERCENT", validFrom: "2000-01-01", sourceVintageAt: "2026-09-07T05:00:00Z", points: [{ month: "2026-06", value: 2.5, observationCount: 20, partial: false }, { month: "2026-07", value: 2.5, observationCount: 22, partial: false }, { month: "2026-08", value: 2.5, observationCount: 21, partial: false }, { month: "2026-09", value: 2.5, observationCount: 1, partial: true }] }],
};

function fixtureFor(url) {
  const pathname = new URL(url).pathname;
  if (pathname === "/api/market/pulse") return marketPulse;
  if (pathname === "/api/market/timeseries") return macro;
  if (pathname === "/api/articles/daily") return daily;
  if (pathname === "/api/operations/keywords") return keywords;
  if (pathname === "/api/operations/insights") return insights;
  if (pathname === "/api/index") return categoryIndex;
  if (pathname === "/api/search") return searchResult;
  if (pathname === "/api/contextual-search") return { request: {}, results: [], facets: {}, total: 0 };
  return {};
}

const secret = "local-visual-qa-only-secret-2026-09-07";
const subjectId = "11111111-1111-4111-8111-111111111111";
const issuedAt = Math.floor(Date.now() / 1000);
const payloadPart = Buffer.from(JSON.stringify({ sub: subjectId, iat: issuedAt, exp: issuedAt + 3600 })).toString("base64url");
const signingInput = `v1.${payloadPart}`;
const { createHmac } = await import("node:crypto");
const sessionToken = `${signingInput}.${createHmac("sha256", secret).update(signingInput).digest("base64url")}`;

const browser = await chromium.launch({ headless: true });
const report = { baseUrl, consoleErrors: [], pageErrors: [], desktop: {}, mobile: {}, passed: false };

async function preparePage(viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await context.addCookies([{ name: "cre_db_session", value: sessionToken, url: baseUrl, httpOnly: true, sameSite: "Lax" }]);
  const page = await context.newPage();
  page.on("console", (message) => message.type() === "error" && report.consoleErrors.push(message.text()));
  page.on("pageerror", (error) => report.pageErrors.push(error.message));
  await page.route("**/api/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixtureFor(route.request().url())) });
  });
  await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "최신기사를 주제별로 빠르게 확인" }).waitFor();
  await page.getByText("서울 핵심권역 오피스 매각 입찰 본격화").waitFor();
  return page;
}

async function capture(viewport, label) {
  const page = await preparePage(viewport);
  await page.screenshot({ path: path.join(outDir, `${label}-latest-articles.png`), fullPage: false });
  const articleMetrics = await page.evaluate(() => ({
    viewport: [window.innerWidth, window.innerHeight],
    scrollWidth: document.documentElement.scrollWidth,
    navItems: document.querySelectorAll(".workspace-nav > button").length,
    navPosition: getComputedStyle(document.querySelector(".workspace-nav")).position,
    articleCount: document.querySelectorAll(".daily-article-card").length,
    firstArticleTop: document.querySelector(".daily-article-card")?.getBoundingClientRect().top ?? null,
    navTop: document.querySelector(".workspace-nav")?.getBoundingClientRect().top ?? null,
    categories: [...document.querySelectorAll(".article-category-chips button")].map((button) => button.textContent?.trim()),
  }));

  await page.getByRole("button", { name: /시계열자료/ }).click();
  await page.getByRole("heading", { name: "실제 관측값을 시간의 흐름으로 확인" }).waitFor();
  await page.getByRole("heading", { name: /거래금액은 늘었지만 건수는 줄어/ }).waitFor();
  await page.screenshot({ path: path.join(outDir, `${label}-transaction-timeseries.png`), fullPage: false });
  await page.getByRole("button", { name: /금리·거시/ }).click();
  await page.getByRole("heading", { name: "금리의 방향을 한 화면에서" }).waitFor();
  await page.screenshot({ path: path.join(outDir, `${label}-rate-timeseries.png`), fullPage: false });
  const timeseriesMetrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    macroStrips: document.querySelectorAll(".macro-strip").length,
    switchItems: document.querySelectorAll(".timeseries-switch button").length,
  }));
  await page.context().close();
  return { ...articleMetrics, timeseries: timeseriesMetrics };
}

report.desktop = await capture({ width: 1440, height: 1000 }, "desktop");
report.mobile = await capture({ width: 390, height: 844 }, "mobile");
await browser.close();

report.passed = report.consoleErrors.length === 0
  && report.pageErrors.length === 0
  && report.desktop.scrollWidth <= report.desktop.viewport[0]
  && report.mobile.scrollWidth <= report.mobile.viewport[0]
  && report.desktop.timeseries.scrollWidth <= report.desktop.viewport[0]
  && report.mobile.timeseries.scrollWidth <= report.mobile.viewport[0]
  && report.desktop.navItems === 2
  && report.mobile.navItems === 2
  && report.mobile.navPosition === "fixed"
  && report.desktop.articleCount === 3
  && report.mobile.articleCount === 3
  && report.mobile.firstArticleTop < report.mobile.navTop
  && report.desktop.categories.some((label) => label.includes("거래"))
  && report.desktop.categories.some((label) => label.includes("자본·금융"))
  && report.desktop.timeseries.switchItems === 2
  && report.mobile.timeseries.switchItems === 2
  && report.desktop.timeseries.macroStrips > 0
  && report.mobile.timeseries.macroStrips > 0;

await fs.writeFile(path.join(outDir, "report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
if (!report.passed) process.exitCode = 1;
