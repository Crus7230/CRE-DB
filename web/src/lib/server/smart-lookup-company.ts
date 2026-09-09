import { createHash } from "node:crypto";
import { inflateRawSync } from "node:zlib";

import type { LookupCard, LookupSource, LookupSourceState } from "@/lib/smart-lookup-contract";
import {
  LookupProviderError,
  type LookupContext,
  type ProviderCandidate,
  type ProviderResult,
} from "@/lib/server/smart-lookup-types";

const DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml";
const DART_COMPANY_URL = "https://opendart.fss.or.kr/api/company.json";
const DART_DISCLOSURE_URL = "https://opendart.fss.or.kr/api/list.json";
const DART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do";
const KRX_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis/sto";

const DART_INDEX_TTL_MS = 6 * 60 * 60 * 1_000;
const DART_INDEX_STALE_MS = 24 * 60 * 60 * 1_000;
const KRX_ROWS_TTL_MS = 12 * 60 * 60 * 1_000;
const KRX_EMPTY_TTL_MS = 10 * 60 * 1_000;
const MAX_DART_CACHE_ENTRIES = 2;
const MAX_KRX_CACHE_ENTRIES = 24;
const MAX_CANDIDATES = 20;
const MAX_CORPORATIONS = 200_000;
const MAX_ZIP_ENTRIES = 64;
const MAX_UNCOMPRESSED_XML_BYTES = 64 * 1024 * 1024;
const MAX_KRX_ROWS = 20_000;
const KRX_LOOKBACK_BUSINESS_DAYS = 4;

const DART_CORP_SOURCE = { id: "dart-corp-codes", label: "OpenDART 기업 고유번호" } as const;
const DART_COMPANY_SOURCE = { id: "dart-company", label: "OpenDART 기업개황" } as const;
const DART_DISCLOSURE_SOURCE = { id: "dart-disclosures", label: "OpenDART 공시검색" } as const;
const KRX_SOURCE = { id: "krx-security", label: "KRX 종목 기본정보" } as const;

interface DartCorporation {
  corpCode: string;
  corpName: string;
  corpNameEng: string;
  stockCode: string;
  modifyDate: string;
  normalizedName: string;
  normalizedEnglishName: string;
}

interface DartIndexCacheEntry {
  corporations: DartCorporation[];
  loadedAtMs: number;
}

interface DartCompany {
  corpName: string;
  corpNameEng: string;
  stockName: string;
  stockCode: string;
  ceoName: string;
  corporationClass: string;
  address: string;
  industryCode: string;
  establishedDate: string;
  accountingMonth: string;
}

interface DartDisclosure {
  receiptNumber: string;
  receiptDate: string;
  reportName: string;
  filerName: string;
}

interface KrxRow {
  issueCode: string;
  shortCode: string;
  issueName: string;
  abbreviatedName: string;
  englishName: string;
  listingDate: string;
  marketName: string;
  securityGroup: string;
  sectorType: string;
  stockCertificateType: string;
  parValue: string;
  listedShares: string;
}

interface KrxCacheEntry {
  rows: KrxRow[];
  loadedAtMs: number;
}

interface DartLoadResult<T> {
  source: LookupSource;
  card?: LookupCard;
  data?: T;
}

class DartStatusError extends Error {
  constructor(readonly status: string) {
    super("dart_status");
    this.name = "DartStatusError";
  }
}

const dartIndexCache = new Map<string, DartIndexCacheEntry>();
const dartIndexFlights = new Map<string, Promise<DartIndexCacheEntry>>();
const krxRowsCache = new Map<string, KrxCacheEntry>();
const krxRowsFlights = new Map<string, Promise<KrxRow[]>>();

function credentialFingerprint(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function checkedAt(now: Date): string {
  return now.toISOString();
}

function source(
  definition: { id: string; label: string },
  status: LookupSourceState,
  now: Date,
  message?: string,
  asOf?: string,
): LookupSource {
  return {
    ...definition,
    status,
    ...(message ? { message } : {}),
    checkedAt: checkedAt(now),
    ...(asOf ? { asOf } : {}),
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function asString(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
}

function normalizeCompanyName(value: string): string {
  return value
    .normalize("NFKC")
    .toLocaleLowerCase("ko-KR")
    .replace(/주식회사|유한회사|\(주\)|㈜/gu, "")
    .replace(/[^0-9a-z가-힣]/giu, "");
}

function decodeXmlText(value: string): string {
  return value
    .replace(/^<!\[CDATA\[([\s\S]*)\]\]>$/u, "$1")
    .replace(/&#x([0-9a-f]+);/giu, (_, hexadecimal: string) => {
      const point = Number.parseInt(hexadecimal, 16);
      return Number.isFinite(point) && point >= 0 && point <= 0x10ffff ? String.fromCodePoint(point) : "";
    })
    .replace(/&#([0-9]+);/gu, (_, decimal: string) => {
      const point = Number.parseInt(decimal, 10);
      return Number.isFinite(point) && point >= 0 && point <= 0x10ffff ? String.fromCodePoint(point) : "";
    })
    .replace(/&lt;/gu, "<")
    .replace(/&gt;/gu, ">")
    .replace(/&quot;/gu, "\"")
    .replace(/&apos;/gu, "'")
    .replace(/&amp;/gu, "&")
    .trim();
}

function extractXmlValue(block: string, tag: string): string {
  const match = new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`, "u").exec(block);
  return match ? decodeXmlText(match[1]) : "";
}

function findEndOfCentralDirectory(buffer: Buffer): number {
  const minimumOffset = Math.max(0, buffer.length - 65_557);
  for (let offset = buffer.length - 22; offset >= minimumOffset; offset -= 1) {
    if (buffer.readUInt32LE(offset) === 0x06054b50) return offset;
  }
  throw new LookupProviderError("invalid_response");
}

function extractXmlFromZip(bytes: Uint8Array): string {
  const buffer = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (buffer.length < 22) throw new LookupProviderError("invalid_response");

  const eocdOffset = findEndOfCentralDirectory(buffer);
  const diskNumber = buffer.readUInt16LE(eocdOffset + 4);
  const centralDirectoryDisk = buffer.readUInt16LE(eocdOffset + 6);
  const entryCount = buffer.readUInt16LE(eocdOffset + 10);
  const centralDirectorySize = buffer.readUInt32LE(eocdOffset + 12);
  const centralDirectoryOffset = buffer.readUInt32LE(eocdOffset + 16);
  if (
    diskNumber !== 0
    || centralDirectoryDisk !== 0
    || entryCount < 1
    || entryCount > MAX_ZIP_ENTRIES
    || centralDirectoryOffset + centralDirectorySize > buffer.length
  ) {
    throw new LookupProviderError("invalid_response");
  }

  let cursor = centralDirectoryOffset;
  let selected:
    | { name: string; flags: number; compression: number; compressedSize: number; uncompressedSize: number; localOffset: number }
    | undefined;

  for (let index = 0; index < entryCount; index += 1) {
    if (cursor + 46 > buffer.length || buffer.readUInt32LE(cursor) !== 0x02014b50) {
      throw new LookupProviderError("invalid_response");
    }
    const flags = buffer.readUInt16LE(cursor + 8);
    const compression = buffer.readUInt16LE(cursor + 10);
    const compressedSize = buffer.readUInt32LE(cursor + 20);
    const uncompressedSize = buffer.readUInt32LE(cursor + 24);
    const nameLength = buffer.readUInt16LE(cursor + 28);
    const extraLength = buffer.readUInt16LE(cursor + 30);
    const commentLength = buffer.readUInt16LE(cursor + 32);
    const localOffset = buffer.readUInt32LE(cursor + 42);
    const nextCursor = cursor + 46 + nameLength + extraLength + commentLength;
    if (nextCursor > buffer.length) throw new LookupProviderError("invalid_response");
    const name = buffer.subarray(cursor + 46, cursor + 46 + nameLength).toString("utf8");
    if (/\.xml$/iu.test(name) && (!selected || /(^|\/)CORPCODE\.xml$/iu.test(name))) {
      selected = { name, flags, compression, compressedSize, uncompressedSize, localOffset };
    }
    cursor = nextCursor;
  }

  if (
    !selected
    || (selected.flags & 0x0001) !== 0
    || ![0, 8].includes(selected.compression)
    || selected.uncompressedSize < 1
    || selected.uncompressedSize > MAX_UNCOMPRESSED_XML_BYTES
    || selected.localOffset + 30 > buffer.length
    || buffer.readUInt32LE(selected.localOffset) !== 0x04034b50
  ) {
    throw new LookupProviderError("invalid_response");
  }

  const localNameLength = buffer.readUInt16LE(selected.localOffset + 26);
  const localExtraLength = buffer.readUInt16LE(selected.localOffset + 28);
  const dataOffset = selected.localOffset + 30 + localNameLength + localExtraLength;
  const dataEnd = dataOffset + selected.compressedSize;
  if (dataOffset > buffer.length || dataEnd > buffer.length) throw new LookupProviderError("invalid_response");
  const compressed = buffer.subarray(dataOffset, dataEnd);

  let xmlBuffer: Buffer;
  try {
    xmlBuffer = selected.compression === 0
      ? Buffer.from(compressed)
      : inflateRawSync(compressed, { maxOutputLength: MAX_UNCOMPRESSED_XML_BYTES });
  } catch {
    throw new LookupProviderError("invalid_response");
  }
  if (xmlBuffer.length !== selected.uncompressedSize || xmlBuffer.length > MAX_UNCOMPRESSED_XML_BYTES) {
    throw new LookupProviderError("invalid_response");
  }
  return xmlBuffer.toString("utf8");
}

function parseDartStatusFromBytes(bytes: Uint8Array): string | null {
  const preview = Buffer.from(bytes.buffer, bytes.byteOffset, Math.min(bytes.byteLength, 4_096)).toString("utf8");
  return /<status>\s*([0-9]{3})\s*<\/status>/u.exec(preview)?.[1] ?? null;
}

function parseDartCorporations(bytes: Uint8Array): { corporations: DartCorporation[] } {
  if (bytes.length < 4 || Buffer.from(bytes.buffer, bytes.byteOffset, 4).readUInt32LE(0) !== 0x04034b50) {
    const status = parseDartStatusFromBytes(bytes);
    if (status) throw new DartStatusError(status);
    throw new LookupProviderError("invalid_response");
  }

  const xml = extractXmlFromZip(bytes);
  const corporations = new Map<string, DartCorporation>();
  const listPattern = /<list>([\s\S]*?)<\/list>/gu;
  let match: RegExpExecArray | null;
  while ((match = listPattern.exec(xml))) {
    if (corporations.size >= MAX_CORPORATIONS) throw new LookupProviderError("too_large");
    const corpCode = extractXmlValue(match[1], "corp_code");
    const corpName = extractXmlValue(match[1], "corp_name");
    const corpNameEng = extractXmlValue(match[1], "corp_eng_name");
    const stockCode = extractXmlValue(match[1], "stock_code");
    const modifyDate = extractXmlValue(match[1], "modify_date");
    if (!/^[0-9]{8}$/u.test(corpCode) || !corpName || (stockCode && !/^[0-9]{6}$/u.test(stockCode))) continue;
    const corporation: DartCorporation = {
      corpCode,
      corpName,
      corpNameEng,
      stockCode,
      modifyDate: /^[0-9]{8}$/u.test(modifyDate) ? modifyDate : "",
      normalizedName: normalizeCompanyName(corpName),
      normalizedEnglishName: normalizeCompanyName(corpNameEng),
    };
    corporations.set(corpCode, corporation);
  }
  if (corporations.size === 0) throw new LookupProviderError("invalid_response");
  return { corporations: [...corporations.values()] };
}

function enforceBoundedCache<T>(cache: Map<string, T>, maximum: number): void {
  while (cache.size > maximum) {
    const oldestKey = cache.keys().next().value as string | undefined;
    if (!oldestKey) break;
    cache.delete(oldestKey);
  }
}

async function refreshDartIndex(key: string, context: LookupContext, nowMs: number): Promise<DartIndexCacheEntry> {
  const url = new URL(DART_CORP_CODE_URL);
  url.searchParams.set("crtfc_key", key);
  const bytes = await context.requestBytes(url.toString(), { headers: { Accept: "application/zip, application/octet-stream" } });
  const parsed = parseDartCorporations(bytes);
  return { ...parsed, loadedAtMs: nowMs };
}

async function getDartIndex(
  key: string,
  context: LookupContext,
  now: Date,
): Promise<{ entry: DartIndexCacheEntry; stale: boolean; refreshError?: unknown }> {
  const cacheKey = credentialFingerprint(key);
  const cached = dartIndexCache.get(cacheKey);
  const age = cached ? now.getTime() - cached.loadedAtMs : Number.POSITIVE_INFINITY;
  if (cached && age >= 0 && age < DART_INDEX_TTL_MS) {
    dartIndexCache.delete(cacheKey);
    dartIndexCache.set(cacheKey, cached);
    return { entry: cached, stale: false };
  }

  let flight = dartIndexFlights.get(cacheKey);
  if (!flight) {
    flight = refreshDartIndex(key, context, now.getTime());
    dartIndexFlights.set(cacheKey, flight);
  }
  try {
    const entry = await flight;
    dartIndexCache.delete(cacheKey);
    dartIndexCache.set(cacheKey, entry);
    enforceBoundedCache(dartIndexCache, MAX_DART_CACHE_ENTRIES);
    return { entry, stale: false };
  } catch (error) {
    if (cached && age >= 0 && age <= DART_INDEX_STALE_MS) {
      return { entry: cached, stale: true, refreshError: error };
    }
    throw error;
  } finally {
    if (dartIndexFlights.get(cacheKey) === flight) dartIndexFlights.delete(cacheKey);
  }
}

function dashedDate(value: string): string {
  return /^\d{8}$/u.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value;
}

function candidateScore(corporation: DartCorporation, rawQuery: string, normalizedQuery: string): number | null {
  const numericQuery = rawQuery.replace(/\s+/gu, "");
  if (numericQuery === corporation.corpCode || (corporation.stockCode && numericQuery === corporation.stockCode)) return 0;
  if (!normalizedQuery) return null;
  if (corporation.normalizedName === normalizedQuery) return 1;
  if (corporation.normalizedEnglishName && corporation.normalizedEnglishName === normalizedQuery) return 2;
  if (corporation.normalizedName.startsWith(normalizedQuery)) return 3;
  if (corporation.normalizedEnglishName.startsWith(normalizedQuery)) return 4;
  if (corporation.normalizedName.includes(normalizedQuery)) return 5;
  if (corporation.normalizedEnglishName.includes(normalizedQuery)) return 6;
  return null;
}

function toCandidate(corporation: DartCorporation): ProviderCandidate {
  const subtitleParts = [
    corporation.stockCode ? `종목 ${corporation.stockCode}` : "비상장·기타법인",
    `DART ${corporation.corpCode}`,
    corporation.modifyDate ? `목록 갱신 ${dashedDate(corporation.modifyDate)}` : "",
  ].filter(Boolean);
  return {
    kind: "company",
    title: corporation.corpName,
    subtitle: subtitleParts.join(" · "),
    sourceLabel: DART_CORP_SOURCE.label,
    identity: {
      corpCode: corporation.corpCode,
      corpName: corporation.corpName,
      ...(corporation.corpNameEng ? { corpNameEng: corporation.corpNameEng } : {}),
      ...(corporation.stockCode ? { stockCode: corporation.stockCode } : {}),
      ...(corporation.modifyDate ? { modifyDate: corporation.modifyDate } : {}),
    },
  };
}

function safeDartSourceError(
  definition: { id: string; label: string },
  error: unknown,
  now: Date,
): LookupSource {
  if (error instanceof LookupProviderError && error.code === "timeout") {
    return source(definition, "timeout", now, `${definition.label} 응답 시간이 초과되었습니다.`);
  }
  if (error instanceof LookupProviderError && error.code === "configuration") {
    return source(definition, "unconfigured", now, `${definition.label} 연결 설정을 확인해 주세요.`);
  }
  if (error instanceof DartStatusError) {
    if (error.status === "013") return source(definition, "empty", now, "조회된 자료가 없습니다.");
    if (["010", "011", "012", "901"].includes(error.status)) {
      return source(definition, "error", now, "OpenDART 인증 또는 접근 상태를 확인해 주세요.");
    }
    if (error.status === "020") return source(definition, "error", now, "OpenDART 요청 한도 상태를 확인해 주세요.");
    if (error.status === "800") return source(definition, "error", now, "OpenDART 점검 또는 서비스 상태를 확인해 주세요.");
  }
  return source(definition, "error", now, `${definition.label}을 불러오지 못했습니다.`);
}

export async function searchCompanies(query: string, context: LookupContext): Promise<ProviderResult> {
  const now = context.now();
  const key = context.credentials.dartKey?.trim();
  if (!key) {
    return {
      candidates: [],
      cards: [],
      sources: [source(DART_CORP_SOURCE, "unconfigured", now, "OpenDART API 키가 설정되지 않았습니다.")],
      message: "OpenDART API 키가 설정되면 회사 후보를 검색할 수 있습니다.",
    };
  }

  const rawQuery = query.trim().slice(0, 100);
  const normalizedQuery = normalizeCompanyName(rawQuery);
  if (!rawQuery || (!normalizedQuery && !/^\d{6,8}$/u.test(rawQuery))) {
    return {
      candidates: [],
      cards: [],
      sources: [source(DART_CORP_SOURCE, "empty", now, "검색할 회사명이나 종목코드를 입력해 주세요.")],
      message: "검색할 회사명이나 종목코드를 입력해 주세요.",
    };
  }

  try {
    const index = await getDartIndex(key, context, now);
    const ranked = index.entry.corporations
      .map((corporation) => ({ corporation, score: candidateScore(corporation, rawQuery, normalizedQuery) }))
      .filter((item): item is { corporation: DartCorporation; score: number } => item.score !== null)
      .sort((left, right) => (
        left.score - right.score
        || Number(Boolean(right.corporation.stockCode)) - Number(Boolean(left.corporation.stockCode))
        || left.corporation.corpName.localeCompare(right.corporation.corpName, "ko-KR")
        || left.corporation.corpCode.localeCompare(right.corporation.corpCode)
      ));
    const candidates = ranked.slice(0, MAX_CANDIDATES).map(({ corporation }) => toCandidate(corporation));
    const indexCheckedAt = new Date(index.entry.loadedAtMs);
    const lookupSource = index.stale
      ? source(DART_CORP_SOURCE, "error", indexCheckedAt, "공식 최신 목록을 갱신하지 못해 이전 수신 목록을 사용했습니다.")
      : source(DART_CORP_SOURCE, candidates.length > 0 ? "ok" : "empty", indexCheckedAt, candidates.length > 0 ? undefined : "일치하는 회사가 없습니다.");

    return {
      candidates,
      cards: [],
      sources: [lookupSource],
      ...(candidates.length === 0
        ? { message: "OpenDART 고유번호 목록에서 일치하는 회사를 찾지 못했습니다." }
        : ranked.length > 1
          ? { message: "동명이거나 유사한 회사가 있으면 종목코드와 DART 고유번호로 선택해 주세요." }
          : {}),
    };
  } catch (error) {
    return {
      candidates: [],
      cards: [],
      sources: [safeDartSourceError(DART_CORP_SOURCE, error, now)],
      message: "회사 후보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
    };
  }
}

function buildDartUrl(base: string, key: string, parameters: Record<string, string>): string {
  const url = new URL(base);
  url.searchParams.set("crtfc_key", key);
  for (const [name, value] of Object.entries(parameters)) url.searchParams.set(name, value);
  return url.toString();
}

function parseDartResponse(value: unknown): Record<string, unknown> {
  const record = asRecord(value);
  if (!record) throw new LookupProviderError("invalid_response");
  const status = asString(record.status);
  if (status !== "000") throw new DartStatusError(status || "unknown");
  return record;
}

function corporationClassLabel(value: string): string {
  return ({ Y: "유가증권시장", K: "코스닥시장", N: "코넥스시장", E: "기타법인" } as Record<string, string>)[value] ?? value;
}

function optionalFields(fields: Array<{ label: string; value: string }>): Array<{ label: string; value: string }> {
  return fields.filter((field) => field.value.length > 0);
}

async function loadDartCompany(corpCode: string, key: string, context: LookupContext, now: Date): Promise<DartLoadResult<DartCompany>> {
  try {
    const response = parseDartResponse(await context.requestJson(buildDartUrl(DART_COMPANY_URL, key, { corp_code: corpCode })));
    const data: DartCompany = {
      corpName: asString(response.corp_name),
      corpNameEng: asString(response.corp_name_eng),
      stockName: asString(response.stock_name),
      stockCode: asString(response.stock_code),
      ceoName: asString(response.ceo_nm),
      corporationClass: asString(response.corp_cls),
      address: asString(response.adres),
      industryCode: asString(response.induty_code),
      establishedDate: asString(response.est_dt),
      accountingMonth: asString(response.acc_mt),
    };
    if (!data.corpName) throw new LookupProviderError("invalid_response");
    return {
      data,
      source: source(DART_COMPANY_SOURCE, "ok", now),
      card: {
        id: `dart-company-${corpCode}`,
        presentation: "company",
        title: data.corpName,
        sourceLabel: DART_COMPANY_SOURCE.label,
        ...(data.corpNameEng || data.stockName ? { subtitle: data.corpNameEng || data.stockName } : {}),
        fields: optionalFields([
          { label: "법인 구분", value: corporationClassLabel(data.corporationClass) },
          { label: "종목코드", value: data.stockCode },
          { label: "대표자", value: data.ceoName },
          { label: "업종코드", value: data.industryCode },
          { label: "설립일", value: dashedDate(data.establishedDate) },
          { label: "결산월", value: data.accountingMonth ? `${data.accountingMonth}월` : "" },
          { label: "주소", value: data.address },
        ]),
        note: "OpenDART 기업개황의 조회 시점 정보입니다.",
      },
    };
  } catch (error) {
    return { source: safeDartSourceError(DART_COMPANY_SOURCE, error, now) };
  }
}

function seoulDateParts(date: Date): { year: number; month: number; day: number } {
  const shifted = new Date(date.getTime() + 9 * 60 * 60 * 1_000);
  return { year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate() };
}

function formatDateParts(parts: { year: number; month: number; day: number }): string {
  return `${parts.year.toString().padStart(4, "0")}${parts.month.toString().padStart(2, "0")}${parts.day.toString().padStart(2, "0")}`;
}

function recentDisclosureRange(now: Date): { begin: string; end: string } {
  const current = seoulDateParts(now);
  const endDate = new Date(Date.UTC(current.year, current.month - 1, current.day));
  const beginDate = new Date(endDate);
  beginDate.setUTCFullYear(beginDate.getUTCFullYear() - 1);
  return {
    begin: formatDateParts({ year: beginDate.getUTCFullYear(), month: beginDate.getUTCMonth() + 1, day: beginDate.getUTCDate() }),
    end: formatDateParts(current),
  };
}

async function loadDartDisclosures(corpCode: string, key: string, context: LookupContext, now: Date): Promise<DartLoadResult<DartDisclosure[]>> {
  const range = recentDisclosureRange(now);
  try {
    const response = parseDartResponse(await context.requestJson(buildDartUrl(DART_DISCLOSURE_URL, key, {
      corp_code: corpCode,
      bgn_de: range.begin,
      end_de: range.end,
      sort: "date",
      sort_mth: "desc",
      page_no: "1",
      page_count: "10",
    })));
    if (!Array.isArray(response.list)) throw new LookupProviderError("invalid_response");
    const disclosures = response.list.slice(0, 10).map((item): DartDisclosure | null => {
      const record = asRecord(item);
      if (!record) return null;
      const receiptNumber = asString(record.rcept_no);
      const receiptDate = asString(record.rcept_dt);
      const reportName = asString(record.report_nm);
      if (!/^[0-9]{8,20}$/u.test(receiptNumber) || !/^\d{8}$/u.test(receiptDate) || !reportName) return null;
      return { receiptNumber, receiptDate, reportName, filerName: asString(record.flr_nm) };
    }).filter((item): item is DartDisclosure => item !== null);
    if (disclosures.length === 0) {
      return { data: [], source: source(DART_DISCLOSURE_SOURCE, "empty", now, "최근 1년 공시가 없습니다.", dashedDate(range.end)) };
    }
    const links = disclosures.map((disclosure) => {
      const url = new URL(DART_VIEWER_URL);
      url.searchParams.set("rcpNo", disclosure.receiptNumber);
      return { label: `${dashedDate(disclosure.receiptDate)} · ${disclosure.reportName}`, url: url.toString() };
    });
    return {
      data: disclosures,
      source: source(DART_DISCLOSURE_SOURCE, "ok", now, undefined, dashedDate(disclosures[0].receiptDate)),
      card: {
        id: `dart-disclosures-${corpCode}`,
        presentation: "disclosures",
        title: "최근 1년 공시",
        sourceLabel: DART_DISCLOSURE_SOURCE.label,
        fields: disclosures.map((disclosure) => ({
          label: dashedDate(disclosure.receiptDate),
          value: disclosure.filerName ? `${disclosure.reportName} · ${disclosure.filerName}` : disclosure.reportName,
        })),
        links,
        note: "최신순 최대 10건이며, 링크는 DART 공시 원문으로 연결됩니다.",
        asOf: dashedDate(disclosures[0].receiptDate),
      },
    };
  } catch (error) {
    return { source: safeDartSourceError(DART_DISCLOSURE_SOURCE, error, now) };
  }
}

function previousKrxBusinessDates(now: Date): string[] {
  const current = seoulDateParts(now);
  const cursor = new Date(Date.UTC(current.year, current.month - 1, current.day));
  const dates: string[] = [];
  cursor.setUTCDate(cursor.getUTCDate() - 1);
  while (dates.length < KRX_LOOKBACK_BUSINESS_DAYS) {
    const weekday = cursor.getUTCDay();
    if (weekday !== 0 && weekday !== 6) {
      dates.push(formatDateParts({ year: cursor.getUTCFullYear(), month: cursor.getUTCMonth() + 1, day: cursor.getUTCDate() }));
    }
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  return dates;
}

function krxApiId(corporationClass: string): string | null {
  return ({ Y: "stk_isu_base_info", K: "ksq_isu_base_info", N: "knx_isu_base_info" } as Record<string, string>)[corporationClass] ?? null;
}

function parseKrxRows(value: unknown): KrxRow[] {
  const record = asRecord(value);
  if (!record || !Array.isArray(record.OutBlock_1) || record.OutBlock_1.length > MAX_KRX_ROWS) {
    throw new LookupProviderError("invalid_response");
  }
  return record.OutBlock_1.map((item): KrxRow => {
    const row = asRecord(item);
    if (!row) throw new LookupProviderError("invalid_response");
    const parsed = {
      issueCode: asString(row.ISU_CD),
      shortCode: asString(row.ISU_SRT_CD),
      issueName: asString(row.ISU_NM),
      abbreviatedName: asString(row.ISU_ABBRV),
      englishName: asString(row.ISU_ENG_NM),
      listingDate: asString(row.LIST_DD),
      marketName: asString(row.MKT_TP_NM),
      securityGroup: asString(row.SECUGRP_NM),
      sectorType: asString(row.SECT_TP_NM),
      stockCertificateType: asString(row.KIND_STKCERT_TP_NM),
      parValue: asString(row.PARVAL),
      listedShares: asString(row.LIST_SHRS),
    };
    if (!parsed.shortCode) throw new LookupProviderError("invalid_response");
    return parsed;
  });
}

async function requestKrxRows(apiId: string, date: string, key: string, context: LookupContext): Promise<KrxRow[]> {
  const url = new URL(`${KRX_BASE_URL}/${apiId}`);
  url.searchParams.set("basDd", date);
  return parseKrxRows(await context.requestJson(url.toString(), {
    headers: { Accept: "application/json", AUTH_KEY: key },
  }));
}

async function getKrxRows(apiId: string, date: string, key: string, context: LookupContext, now: Date): Promise<KrxRow[]> {
  const cacheKey = credentialFingerprint(`${credentialFingerprint(key)}:${apiId}:${date}`);
  const cached = krxRowsCache.get(cacheKey);
  const ttl = cached?.rows.length ? KRX_ROWS_TTL_MS : KRX_EMPTY_TTL_MS;
  const age = cached ? now.getTime() - cached.loadedAtMs : Number.POSITIVE_INFINITY;
  if (cached && age >= 0 && age < ttl) {
    krxRowsCache.delete(cacheKey);
    krxRowsCache.set(cacheKey, cached);
    return cached.rows;
  }

  let flight = krxRowsFlights.get(cacheKey);
  if (!flight) {
    flight = requestKrxRows(apiId, date, key, context);
    krxRowsFlights.set(cacheKey, flight);
  }
  try {
    const rows = await flight;
    krxRowsCache.delete(cacheKey);
    krxRowsCache.set(cacheKey, { rows, loadedAtMs: now.getTime() });
    enforceBoundedCache(krxRowsCache, MAX_KRX_CACHE_ENTRIES);
    return rows;
  } finally {
    if (krxRowsFlights.get(cacheKey) === flight) krxRowsFlights.delete(cacheKey);
  }
}

function formatKrxAmount(value: string, suffix: string): string {
  if (!/^-?\d+(?:\.\d+)?$/u.test(value)) return value;
  const number = Number(value);
  return Number.isSafeInteger(number) ? `${number.toLocaleString("ko-KR")}${suffix}` : `${value}${suffix}`;
}

function safeKrxSourceError(error: unknown, now: Date): LookupSource {
  if (error instanceof LookupProviderError && error.code === "timeout") {
    return source(KRX_SOURCE, "timeout", now, "KRX 종목 기본정보 응답 시간이 초과되었습니다.");
  }
  if (error instanceof LookupProviderError && error.code === "configuration") {
    return source(KRX_SOURCE, "unconfigured", now, "KRX 연결 설정을 확인해 주세요.");
  }
  return source(KRX_SOURCE, "error", now, "KRX 종목 기본정보 서비스 승인 또는 연결 상태를 확인해 주세요.");
}

async function loadKrxCompany(
  stockCode: string,
  corporationClass: string,
  context: LookupContext,
  now: Date,
): Promise<DartLoadResult<KrxRow>> {
  const key = context.credentials.krxKey?.trim();
  if (!key) return { source: source(KRX_SOURCE, "unconfigured", now, "KRX API 키가 설정되지 않았습니다.") };
  if (!stockCode) return { source: source(KRX_SOURCE, "empty", now, "상장 종목코드가 없어 KRX 조회 대상이 아닙니다.") };
  const apiId = krxApiId(corporationClass);
  if (!apiId) {
    return { source: source(KRX_SOURCE, "empty", now, "상장 시장 구분을 확인하지 못해 KRX 조회를 생략했습니다.") };
  }

  const dates = previousKrxBusinessDates(now);
  try {
    for (let index = 0; index < dates.length; index += 1) {
      const date = dates[index];
      const rows = await getKrxRows(apiId, date, key, context, now);
      if (rows.length === 0) continue;
      const row = rows.find((candidate) => candidate.shortCode.replace(/\D/gu, "") === stockCode.replace(/\D/gu, ""));
      if (!row) {
        return {
          source: source(
            KRX_SOURCE,
            "empty",
            now,
            "KRX 시장 자료는 수신됐지만 선택한 종목의 기본정보는 포함되지 않았습니다.",
            dashedDate(date),
          ),
        };
      }
      const fallbackMessage = index > 0
        ? "서비스 승인 응답 확인 · 최근 기준일 자료가 없어 직전 수신일 자료를 표시합니다."
        : "서비스 승인 응답 확인";
      return {
        data: row,
        source: source(KRX_SOURCE, "ok", now, fallbackMessage, dashedDate(date)),
        card: {
          id: `krx-security-${stockCode}`,
          presentation: "security",
          title: row.abbreviatedName || row.issueName || stockCode,
          sourceLabel: KRX_SOURCE.label,
          ...(row.englishName ? { subtitle: row.englishName } : {}),
          fields: optionalFields([
            { label: "시장", value: row.marketName },
            { label: "종목코드", value: row.shortCode },
            { label: "표준코드", value: row.issueCode },
            { label: "상장일", value: dashedDate(row.listingDate) },
            { label: "증권 구분", value: row.securityGroup },
            { label: "소속 구분", value: row.sectorType },
            { label: "주권 종류", value: row.stockCertificateType },
            { label: "액면가", value: formatKrxAmount(row.parValue, "원") },
            { label: "상장 주식수", value: formatKrxAmount(row.listedShares, "주") },
          ]),
          note: "실시간 주가가 아닌 기준일 종목 기본정보입니다.",
          asOf: dashedDate(date),
        },
      };
    }
    return {
      source: source(KRX_SOURCE, "empty", now, "최근 기준일의 KRX 종목 기본정보가 수신되지 않았습니다."),
    };
  } catch (error) {
    return { source: safeKrxSourceError(error, now) };
  }
}

export async function loadCompany(identity: Record<string, string>, context: LookupContext): Promise<ProviderResult> {
  const now = context.now();
  const corpCode = identity.corpCode?.trim() ?? "";
  const dartKey = context.credentials.dartKey?.trim();
  if (!/^\d{8}$/u.test(corpCode)) {
    return {
      candidates: [],
      cards: [],
      sources: [
        source(DART_COMPANY_SOURCE, "error", now, "선택한 회사 식별정보가 올바르지 않습니다."),
        source(DART_DISCLOSURE_SOURCE, "error", now, "선택한 회사 식별정보가 올바르지 않습니다."),
        source(KRX_SOURCE, "empty", now, "회사 식별정보를 확인하지 못해 KRX 조회를 생략했습니다."),
      ],
      message: "회사를 다시 검색해 선택해 주세요.",
    };
  }
  if (!dartKey) {
    return {
      candidates: [],
      cards: [],
      sources: [
        source(DART_COMPANY_SOURCE, "unconfigured", now, "OpenDART API 키가 설정되지 않았습니다."),
        source(DART_DISCLOSURE_SOURCE, "unconfigured", now, "OpenDART API 키가 설정되지 않았습니다."),
        context.credentials.krxKey?.trim()
          ? source(KRX_SOURCE, "error", now, "상장 시장 구분을 확인하지 못해 KRX 조회를 생략했습니다.")
          : source(KRX_SOURCE, "unconfigured", now, "KRX API 키가 설정되지 않았습니다."),
      ],
      message: "공식 기업정보 연결 설정을 확인해 주세요.",
    };
  }

  const [company, disclosures] = await Promise.all([
    loadDartCompany(corpCode, dartKey, context, now),
    loadDartDisclosures(corpCode, dartKey, context, now),
  ]);
  const stockCode = company.data?.stockCode || identity.stockCode?.trim() || "";
  const krx = await loadKrxCompany(stockCode, company.data?.corporationClass ?? "", context, now);
  const cards = [company.card, disclosures.card, krx.card].filter((card): card is LookupCard => Boolean(card));
  const sources = [company.source, disclosures.source, krx.source];
  return {
    candidates: [],
    cards,
    sources,
    ...(cards.length === 0 ? { message: "공식 출처에서 표시할 기업정보를 불러오지 못했습니다." } : {}),
  };
}
