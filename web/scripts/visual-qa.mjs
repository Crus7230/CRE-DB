import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const outDir = path.resolve("../artifacts");
const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:3001";
const smokeEmail = process.env.DASHBOARD_SMOKE_EMAIL?.trim().toLowerCase();
if (!smokeEmail) throw new Error("DASHBOARD_SMOKE_EMAIL is required and must already be approved");
await fs.mkdir(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const report = { baseUrl, desktop: {}, mobile: {}, consoleErrors: [], pageErrors: [], passed: false };

function attachDiagnostics(page) {
  page.on("console", (message) => message.type() === "error" && report.consoleErrors.push(message.text()));
  page.on("pageerror", (error) => report.pageErrors.push(error.message));
}

async function authenticate(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("본인 이메일 주소").fill(smokeEmail);
  await page.getByRole("button", { name: "대시보드 열기" }).click();
  await page.waitForURL((url) => url.pathname === "/", { timeout: 30000 });
}

async function waitForSearch(page) {
  await page.getByText("Supabase 검색 중").waitFor({ state: "hidden", timeout: 30000 });
}

async function openIndex(page) {
  await page.getByRole("button", { name: /DB 색인/ }).click();
  await page.getByRole("heading", { name: "DB 카테고리 색인" }).waitFor();
  await page.locator(".index-group").first().waitFor({ timeout: 30000 });
}

async function openIndexedCategory(page, groupName, key) {
  const group = page.locator(".index-group").filter({ has: page.getByRole("heading", { name: groupName }) });
  await group.getByRole("button", { name: new RegExp(key) }).click();
  await page.getByRole("heading", { name: "카테고리별 데이터 테이블" }).waitFor();
  await waitForSearch(page);
  await page.locator(".data-table tbody tr").first().waitFor({ timeout: 30000 });
}

const desktop = await browser.newPage({ viewport: { width: 1536, height: 960 }, deviceScaleFactor: 1 });
attachDiagnostics(desktop);
await authenticate(desktop);
await waitForSearch(desktop);
await openIndex(desktop);
await desktop.screenshot({ path: path.join(outDir, "market-explorer-index-desktop.png"), fullPage: false });
await openIndexedCategory(desktop, "매각 절차 상태", "CLOSED");
const desktopTableRows = await desktop.locator(".data-table tbody tr").count();
const firstDesktopTitle = await desktop.locator(".table-title strong").first().textContent();
await desktop.screenshot({ path: path.join(outDir, "market-explorer-table-desktop.png"), fullPage: false });
await desktop.locator(".table-title").first().click();
await desktop.getByRole("dialog", { name: "검색 결과 상세" }).waitFor();
report.desktop = await desktop.evaluate(() => ({
  viewport: [window.innerWidth, window.innerHeight],
  scrollWidth: document.documentElement.scrollWidth,
  bodyWidth: document.body.getBoundingClientRect().width,
  databaseStatus: document.querySelector(".db-status")?.textContent?.trim(),
  indexGroups: document.querySelectorAll(".index-group").length,
  activeCategory: document.querySelector(".active-category")?.textContent?.trim(),
  drawerVisible: Boolean(document.querySelector('[role="dialog"]')),
  workspaceColumns: getComputedStyle(document.querySelector(".workspace")).gridTemplateColumns,
}));
report.desktop.tableRows = desktopTableRows;
report.desktop.firstTitle = firstDesktopTitle?.trim();
await desktop.screenshot({ path: path.join(outDir, "market-explorer-detail-desktop.png"), fullPage: false });

const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
attachDiagnostics(mobile);
await authenticate(mobile);
await waitForSearch(mobile);
await openIndex(mobile);
await mobile.screenshot({ path: path.join(outDir, "market-explorer-index-mobile.png"), fullPage: false });
await openIndexedCategory(mobile, "문서 유형", "BID_NOTICE");
const mobileRows = await mobile.locator(".data-table tbody tr").count();
await mobile.screenshot({ path: path.join(outDir, "market-explorer-table-mobile.png"), fullPage: false });
await mobile.locator(".table-title").first().click();
await mobile.getByRole("dialog", { name: "검색 결과 상세" }).waitFor();
report.mobile = await mobile.evaluate(() => {
  const drawer = document.querySelector(".detail-drawer");
  const tableWrap = document.querySelector(".data-table-wrap");
  return {
    viewport: [window.innerWidth, window.innerHeight],
    scrollWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.getBoundingClientRect().width,
    tableRows: document.querySelectorAll(".data-table tbody tr").length,
    tableScrollable: tableWrap ? tableWrap.scrollWidth > tableWrap.clientWidth : false,
    drawerVisible: Boolean(drawer),
    drawerHeight: drawer?.getBoundingClientRect().height,
    activeCategory: document.querySelector(".active-category")?.textContent?.trim(),
  };
});
report.mobile.tableRows = mobileRows;
await mobile.screenshot({ path: path.join(outDir, "market-explorer-detail-mobile.png"), fullPage: false });

await browser.close();
report.passed =
  report.consoleErrors.length === 0 &&
  report.pageErrors.length === 0 &&
  report.desktop.scrollWidth <= report.desktop.viewport[0] &&
  report.mobile.scrollWidth <= report.mobile.viewport[0] &&
  report.desktop.tableRows === 11 &&
  report.mobile.tableRows === 9 &&
  report.mobile.tableScrollable === true &&
  report.desktop.drawerVisible === true &&
  report.mobile.drawerVisible === true;

await fs.writeFile(path.join(outDir, "market-explorer-visual-qa.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
if (!report.passed) process.exitCode = 1;
