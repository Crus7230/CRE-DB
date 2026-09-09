import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const base = process.env.BASE_URL ?? 'http://127.0.0.1:3006';
const email = process.env.DASHBOARD_SMOKE_EMAIL;
if (!email) throw new Error('An already approved DASHBOARD_SMOKE_EMAIL is required');
const out = path.resolve('../artifacts/smart-lookup');
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const report = { cases: [], errors: [] };
page.on('pageerror', error => report.errors.push(error.message));
try {
  await page.goto(`${base}/login`);
  await page.getByLabel('본인 이메일 주소').fill(email);
  await page.getByRole('button', { name: '대시보드 열기', exact: true }).click();
  await page.waitForURL(`${base}/`, { timeout: 30000 });
  await page.getByRole('tab', { name: /스마트 조회/ }).click();
  await page.screenshot({ path: path.join(out, 'initial-desktop.png') });
  for (const item of [
    { name: 'address', query: '서울특별시 중구 세종대로 110', title: '세종대로 110' },
    { name: 'company', query: '005930', title: '삼성전자' },
  ]) {
    await page.getByLabel('주소·회사명·종목코드', { exact: true }).fill(item.query);
    let started = Date.now();
    const pending = page.waitForResponse(r => r.url().endsWith('/api/lookup') && r.request().method() === 'POST', { timeout: 60000 });
    await page.getByRole('button', { name: '조회', exact: true }).click();
    const response = await pending;
    const search = await response.json();
    const record = { name: item.name, status: response.status(), searchMs: Date.now() - started, searchStage: search.stage, sources: search.sources, candidates: search.candidates?.map(c => ({ title: c.title, subtitle: c.subtitle })) };
    report.cases.push(record);
    await page.screenshot({ path: path.join(out, `${item.name}-candidates.png`), fullPage: true });
    if (search.stage !== 'candidates') throw new Error(`${item.name}: expected candidates, got ${search.stage}`);
    const candidate = page.getByRole('button', { name: new RegExp(item.title) }).last();
    started = Date.now();
    const detailPending = page.waitForResponse(r => r.url().endsWith('/api/lookup') && r.request().method() === 'POST', { timeout: 60000 });
    await candidate.click();
    const detail = await (await detailPending).json();
    record.detailMs = Date.now() - started;
    record.detailStage = detail.stage;
    record.detailSources = detail.sources;
    record.cards = detail.cards;
    await page.getByRole('region', { name: '상세 조회 자료' }).waitFor({ timeout: 10000 });
    await page.screenshot({ path: path.join(out, `${item.name}-desktop.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(out, `${item.name}-mobile.png`), fullPage: true });
    record.mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    await page.setViewportSize({ width: 1440, height: 1000 });
    if (detail.stage !== 'detail' || record.mobileOverflow) throw new Error(`${item.name}: detail/overflow check failed`);
  }
  report.passed = report.errors.length === 0;
} catch (error) {
  report.passed = false;
  report.errors.push(error.message);
  await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true });
} finally {
  await fs.writeFile(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  await browser.close();
}
if (!report.passed) process.exitCode = 1;
