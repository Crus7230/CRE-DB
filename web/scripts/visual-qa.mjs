import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const outDir = path.resolve("../artifacts");
const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:3001";
const smokeEmail = process.env.DASHBOARD_SMOKE_EMAIL?.trim().toLowerCase();
if (!smokeEmail) throw new Error("DASHBOARD_SMOKE_EMAIL is required and must already be approved");
await fs.mkdir(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const report = {
  baseUrl,
  desktop: {},
  mobile: {},
  consoleErrors: [],
  pageErrors: [],
  passed: false,
};

function attachDiagnostics(page) {
  page.on("console", (message) => message.type() === "error" && report.consoleErrors.push(message.text()));
  page.on("pageerror", (error) => report.pageErrors.push(error.message));
}

async function authenticate(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  if (new URL(page.url()).pathname === "/") return;
  await page.getByLabel("본인 이메일 주소").fill(smokeEmail);
  await page.getByRole("button", { name: "대시보드 열기" }).click();
  await page.waitForURL((url) => url.pathname === "/", { timeout: 30_000 });
}

async function waitForNews(page) {
  await page.locator(".daily-article-row").first().waitFor({ timeout: 30_000 });
}

async function openPrimaryTab(page, name) {
  await page.getByRole("tab", { name }).click();
}

const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
attachDiagnostics(desktop);
await authenticate(desktop);
await waitForNews(desktop);
const firstArticleTitle = await desktop.locator(".daily-article-row h2").first().textContent();
await desktop.screenshot({ path: path.join(outDir, "cre-dashboard-news-desktop.png"), fullPage: false });

report.desktop.news = await desktop.evaluate(() => {
  const masthead = document.querySelector(".dashboard-masthead");
  const firstRow = document.querySelector(".daily-article-row");
  const title = firstRow?.querySelector("h2");
  const metadata = firstRow?.querySelector("footer");
  const broadButtons = [...document.querySelectorAll(".topic-rail > nav > button")].slice(1);
  const broadCount = broadButtons.reduce((sum, button) => sum + Number(button.querySelector(":scope > b")?.textContent ?? 0), 0);
  return {
    viewport: [window.innerWidth, window.innerHeight],
    scrollWidth: document.documentElement.scrollWidth,
    mastheadHeight: masthead?.getBoundingClientRect().height,
    primaryTabCount: document.querySelectorAll(".primary-tabs [role='tab']").length,
    firstRowVisible: Boolean(firstRow && firstRow.getBoundingClientRect().top < window.innerHeight),
    articleRows: document.querySelectorAll(".daily-article-row").length,
    titleFontSize: title ? Number.parseFloat(getComputedStyle(title).fontSize) : 0,
    metadataFontSize: metadata ? Number.parseFloat(getComputedStyle(metadata).fontSize) : 0,
    broadCount,
  };
});

await openPrimaryTab(desktop, /시계열자료/);
await desktop.locator(".market-pulse-trend").waitFor({ timeout: 30_000 });
await desktop.screenshot({ path: path.join(outDir, "cre-dashboard-transactions-desktop.png"), fullPage: false });
report.desktop.transactions = await desktop.evaluate(() => ({
  scope: document.querySelector(".market-pulse-scope")?.textContent?.trim(),
  heading: document.querySelector(".market-pulse-call h2")?.textContent?.trim(),
  lagNotice: document.querySelector(".transaction-lag-note")?.textContent?.trim(),
  metricCount: document.querySelectorAll(".market-pulse-metrics > article").length,
  chartVisible: Boolean(document.querySelector(".market-pulse-trend")),
  technicalPayloadCopy: /canonical|payload/iu.test(document.querySelector(".quantitative-market-pulse")?.textContent ?? ""),
}));

await desktop.getByRole("tab", { name: /금리·거시/ }).click();
await desktop.locator(".macro-series-row").first().waitFor({ timeout: 30_000 });
await desktop.screenshot({ path: path.join(outDir, "cre-dashboard-rates-desktop.png"), fullPage: false });
report.desktop.rates = await desktop.evaluate(() => ({
  seriesRows: document.querySelectorAll(".macro-series-row").length,
  commonMonth: document.querySelector(".macro-asof strong")?.textContent?.trim(),
  rangeButtons: document.querySelectorAll(".macro-range button").length,
  selectedMonthRows: [...document.querySelectorAll(".macro-strip-value time")].filter((item) => item.textContent?.trim() === document.querySelector(".macro-asof strong")?.textContent?.trim()).length,
  commonScaleCopy: document.querySelector(".macro-method")?.textContent?.trim(),
  hasSignedRoundedZero: (document.querySelector(".macro-dashboard")?.textContent ?? "").includes("+0bp"),
}));

await openPrimaryTab(desktop, /최신기사/);
await desktop.locator(".daily-article-row").first().waitFor();
report.desktop.newsPreserved = await desktop.locator(".daily-article-row h2").first().textContent() === firstArticleTitle;
const articleOpener = desktop.locator(".article-open").first();
await articleOpener.click();
await desktop.getByRole("dialog", { name: "문서 상세" }).waitFor();
report.desktop.drawer = await desktop.evaluate(() => {
  const drawer = document.querySelector("[role='dialog'][aria-label='문서 상세']");
  const text = drawer?.textContent ?? "";
  return {
    visible: Boolean(drawer),
    rawTechnicalLabels: /\b(?:SNIPPET|REVIEW_READY|EXCERPT_ALLOWED)\b/u.test(text),
    hasHumanRightsLabel: text.includes("제한 발췌 허용") || !text.includes("권리상태:"),
  };
});
await desktop.keyboard.press("Escape");
await desktop.getByRole("dialog", { name: "문서 상세" }).waitFor({ state: "detached" });
report.desktop.drawer.openerFocusRestored = await articleOpener.evaluate((element) => document.activeElement === element);

const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
attachDiagnostics(mobile);
await authenticate(mobile);
await waitForNews(mobile);
await mobile.screenshot({ path: path.join(outDir, "cre-dashboard-news-mobile.png"), fullPage: false });
report.mobile.news = await mobile.evaluate(() => {
  const masthead = document.querySelector(".dashboard-masthead");
  const firstRow = document.querySelector(".daily-article-row");
  const title = firstRow?.querySelector("h2");
  const metadata = firstRow?.querySelector("footer");
  return {
    viewport: [window.innerWidth, window.innerHeight],
    scrollWidth: document.documentElement.scrollWidth,
    mastheadHeight: masthead?.getBoundingClientRect().height,
    primaryTabCount: document.querySelectorAll(".primary-tabs [role='tab']").length,
    firstRowVisible: Boolean(firstRow && firstRow.getBoundingClientRect().top < window.innerHeight),
    titleFontSize: title ? Number.parseFloat(getComputedStyle(title).fontSize) : 0,
    metadataFontSize: metadata ? Number.parseFloat(getComputedStyle(metadata).fontSize) : 0,
  };
});

await openPrimaryTab(mobile, /시계열자료/);
await mobile.locator(".market-pulse-trend").waitFor({ timeout: 30_000 });
await mobile.screenshot({ path: path.join(outDir, "cre-dashboard-transactions-mobile.png"), fullPage: false });
await mobile.getByRole("tab", { name: /금리·거시/ }).click();
await mobile.locator(".macro-series-row").first().waitFor({ timeout: 30_000 });
report.mobile.timeseries = await mobile.evaluate(() => ({
  scrollWidth: document.documentElement.scrollWidth,
  seriesRows: document.querySelectorAll(".macro-series-row").length,
  chartWidth: document.querySelector(".macro-series-chart")?.getBoundingClientRect().width,
}));

await browser.close();
report.passed =
  report.consoleErrors.length === 0 &&
  report.pageErrors.length === 0 &&
  report.desktop.news.scrollWidth <= report.desktop.news.viewport[0] &&
  report.mobile.news.scrollWidth <= report.mobile.news.viewport[0] &&
  report.mobile.timeseries.scrollWidth <= report.mobile.news.viewport[0] &&
  report.desktop.news.mastheadHeight === 56 &&
  report.mobile.news.mastheadHeight === 56 &&
  report.desktop.news.primaryTabCount === 2 &&
  report.mobile.news.primaryTabCount === 2 &&
  report.desktop.news.firstRowVisible === true &&
  report.mobile.news.firstRowVisible === true &&
  report.desktop.news.titleFontSize >= 15 &&
  report.desktop.news.metadataFontSize >= 12 &&
  report.mobile.news.titleFontSize >= 15 &&
  report.mobile.news.metadataFontSize >= 12 &&
  report.desktop.news.broadCount === report.desktop.news.articleRows &&
  report.desktop.transactions.metricCount === 4 &&
  report.desktop.transactions.chartVisible === true &&
  report.desktop.transactions.scope?.includes("서울특별시 한정") &&
  /\d{4}년 \d{1,2}월 신고 거래 현황/u.test(report.desktop.transactions.heading ?? "") &&
  report.desktop.transactions.lagNotice?.includes("신고 지연·정정") &&
  report.desktop.transactions.technicalPayloadCopy === false &&
  report.desktop.rates.seriesRows === 13 &&
  report.desktop.rates.rangeButtons === 4 &&
  report.desktop.rates.selectedMonthRows === report.desktop.rates.seriesRows &&
  report.desktop.rates.commonScaleCopy?.includes("동일한 세로 눈금") &&
  report.desktop.rates.hasSignedRoundedZero === false &&
  report.desktop.newsPreserved === true &&
  report.desktop.drawer.visible === true &&
  report.desktop.drawer.rawTechnicalLabels === false &&
  report.desktop.drawer.hasHumanRightsLabel === true &&
  report.desktop.drawer.openerFocusRestored === true &&
  report.mobile.timeseries.seriesRows === 13 &&
  Number(report.mobile.timeseries.chartWidth) > 0;

await fs.writeFile(path.join(outDir, "cre-dashboard-visual-qa.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
if (!report.passed) process.exitCode = 1;
