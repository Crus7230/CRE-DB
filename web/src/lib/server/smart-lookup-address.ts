import "server-only";

import type { LookupCard, LookupSource } from "@/lib/smart-lookup-contract";
import {
  LookupProviderError,
  type LookupContext,
  type ProviderCandidate,
  type ProviderResult,
} from "@/lib/server/smart-lookup-types";

const VWORLD_SEARCH_URL = "https://api.vworld.kr/req/search";
const BUILDING_REGISTER_BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService";
const BUILDING_REGISTER_SOURCE_URL = "https://www.data.go.kr/data/15134735/openapi.do";
const VWORLD_SOURCE_LABEL = "VWorld 주소검색 API";
const BUILDING_SOURCE_LABEL = "국토교통부 건축HUB 건축물대장";
const BUILDING_PAGE_SIZE = 100;
const MAX_BUILDING_ROWS = 200;
const MAX_ADDRESS_CANDIDATES = 20;

type JsonRecord = Record<string, unknown>;
type ProviderState = LookupSource["status"];

type ParcelIdentity = {
  pnu: string;
  legalDongCode: string;
  sigunguCd: string;
  bjdongCd: string;
  platGbCd: string;
  bun: string;
  ji: string;
};

type VworldSearchOutcome = {
  status: ProviderState;
  candidates: ProviderCandidate[];
  message?: string;
};

type RegisterOutcome = {
  status: ProviderState;
  rows: JsonRecord[];
  totalCount: number;
  truncated: boolean;
  message?: string;
};

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | null {
  if (typeof value === "string") {
    const normalized = value.trim();
    return normalized || null;
  }
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function plainText(value: unknown): string | null {
  const raw = text(value);
  if (!raw) return null;
  return raw
    .replace(/<[^>]*>/gu, "")
    .replace(/&nbsp;/giu, " ")
    .replace(/&amp;/giu, "&")
    .replace(/&lt;/giu, "<")
    .replace(/&gt;/giu, ">")
    .replace(/&quot;/giu, "\"")
    .replace(/&#39;/giu, "'")
    .replace(/\s+/gu, " ")
    .trim() || null;
}

function deriveParcelIdentity(pnuValue: unknown): ParcelIdentity | null {
  const pnu = text(pnuValue);
  if (!pnu || !/^\d{19}$/u.test(pnu)) return null;
  const parcelType = pnu[10];
  // PNU digit 11 is 1 for ordinary land and 2 for mountain land, whereas
  // Building HUB platGbCd uses 0 and 1 respectively.
  const platGbCd = parcelType === "1" ? "0" : parcelType === "2" ? "1" : null;
  if (platGbCd === null) return null;
  return {
    pnu,
    legalDongCode: pnu.slice(0, 10),
    sigunguCd: pnu.slice(0, 5),
    bjdongCd: pnu.slice(5, 10),
    platGbCd,
    bun: pnu.slice(11, 15),
    ji: pnu.slice(15, 19),
  };
}

function checkedAt(context: LookupContext) {
  return context.now().toISOString();
}

function source(
  id: string,
  label: string,
  status: ProviderState,
  context: LookupContext,
  message?: string,
  asOf?: string,
): LookupSource {
  return {
    id,
    label,
    status,
    checkedAt: checkedAt(context),
    ...(message ? { message } : {}),
    ...(asOf ? { asOf } : {}),
  };
}

function failureState(error: unknown): { status: "timeout" | "error"; message: string } {
  if (error instanceof LookupProviderError && error.code === "timeout") {
    return { status: "timeout", message: "주소 원천 응답 시간이 초과되었습니다." };
  }
  return { status: "error", message: "주소 원천 연결을 확인하지 못했습니다." };
}

function vworldErrorState(response: JsonRecord): { status: ProviderState; message: string } {
  const error = isRecord(response.error) ? response.error : {};
  const code = `${text(error.code) ?? ""} ${text(error.level) ?? ""}`.toUpperCase();
  if (/KEY|AUTH|PERMISSION|DENIED|DOMAIN/u.test(code)) {
    return { status: "unconfigured", message: "VWorld API 키 또는 등록 도메인 승인이 필요합니다." };
  }
  return { status: "error", message: "VWorld 주소검색 API가 오류를 반환했습니다." };
}

function parseVworldCandidates(payload: unknown): VworldSearchOutcome {
  if (!isRecord(payload) || !isRecord(payload.response)) {
    return { status: "error", candidates: [], message: "VWorld 응답 형식을 확인할 수 없습니다." };
  }
  const response = payload.response;
  const status = text(response.status)?.toUpperCase();
  if (status === "NOT_FOUND") return { status: "empty", candidates: [] };
  if (status !== "OK") {
    const failure = vworldErrorState(response);
    return { ...failure, candidates: [] };
  }
  if (!isRecord(response.result) || !Array.isArray(response.result.items)) {
    return { status: "error", candidates: [], message: "VWorld 주소 후보 형식이 올바르지 않습니다." };
  }

  const candidates: ProviderCandidate[] = [];
  for (const itemValue of response.result.items) {
    if (!isRecord(itemValue)) continue;
    const parcel = deriveParcelIdentity(itemValue.id);
    if (!parcel) continue;
    const address = isRecord(itemValue.address) ? itemValue.address : {};
    const roadAddress = plainText(address.road);
    const parcelAddress = plainText(address.parcel);
    const itemTitle = plainText(itemValue.title);
    const title = roadAddress ?? parcelAddress ?? itemTitle;
    if (!title) continue;
    const subtitleAddress = [parcelAddress, roadAddress]
      .find((candidate) => candidate && candidate !== title);
    candidates.push({
      kind: "address",
      title,
      subtitle: [subtitleAddress, `PNU ${parcel.pnu}`].filter(Boolean).join(" · "),
      sourceLabel: VWORLD_SOURCE_LABEL,
      identity: {
        ...parcel,
        ...(roadAddress ? { roadAddress } : {}),
        ...(parcelAddress ? { parcelAddress } : {}),
        ...(isRecord(itemValue.point) && text(itemValue.point.x) ? { longitude: text(itemValue.point.x) as string } : {}),
        ...(isRecord(itemValue.point) && text(itemValue.point.y) ? { latitude: text(itemValue.point.y) as string } : {}),
      },
    });
  }
  return candidates.length
    ? { status: "ok", candidates }
    : { status: "empty", candidates: [] };
}

function vworldSearchUrl(query: string, category: "road" | "parcel", key: string) {
  const url = new URL(VWORLD_SEARCH_URL);
  url.searchParams.set("service", "search");
  url.searchParams.set("request", "search");
  url.searchParams.set("version", "2.0");
  url.searchParams.set("crs", "EPSG:4326");
  url.searchParams.set("size", String(MAX_ADDRESS_CANDIDATES));
  url.searchParams.set("page", "1");
  url.searchParams.set("query", query);
  url.searchParams.set("type", "address");
  url.searchParams.set("category", category);
  url.searchParams.set("format", "json");
  url.searchParams.set("errorformat", "json");
  url.searchParams.set("key", key);
  return url.toString();
}

async function searchVworldCategory(
  query: string,
  category: "road" | "parcel",
  context: LookupContext,
): Promise<VworldSearchOutcome> {
  try {
    const payload = await context.requestJson(
      vworldSearchUrl(query, category, context.credentials.vworldKey as string),
      { cache: "no-store" },
    );
    return parseVworldCandidates(payload);
  } catch (error) {
    const failure = failureState(error);
    return { ...failure, candidates: [] };
  }
}

function aggregateSearchStatus(outcomes: VworldSearchOutcome[]): ProviderState {
  if (outcomes.some((outcome) => outcome.status === "ok")) return "ok";
  if (outcomes.every((outcome) => outcome.status === "empty")) return "empty";
  if (outcomes.some((outcome) => outcome.status === "unconfigured")) return "unconfigured";
  if (outcomes.some((outcome) => outcome.status === "timeout")) return "timeout";
  return "error";
}

export async function searchAddresses(query: string, context: LookupContext): Promise<ProviderResult> {
  const normalizedQuery = query.trim();
  if (!context.credentials.vworldKey) {
    return {
      candidates: [],
      cards: [],
      sources: [source(
        "vworld-address",
        VWORLD_SOURCE_LABEL,
        "unconfigured",
        context,
        "VWorld 주소검색 API 구성이 필요합니다.",
      )],
      message: "주소검색 원천이 구성되지 않았습니다.",
    };
  }
  if (!normalizedQuery) {
    return {
      candidates: [],
      cards: [],
      sources: [source("vworld-address", VWORLD_SOURCE_LABEL, "empty", context)],
      message: "검색할 주소를 입력해 주세요.",
    };
  }

  const outcomes = await Promise.all([
    searchVworldCategory(normalizedQuery, "road", context),
    searchVworldCategory(normalizedQuery, "parcel", context),
  ]);
  const deduplicated = new Map<string, ProviderCandidate>();
  for (const outcome of outcomes) {
    for (const candidate of outcome.candidates) {
      const pnu = candidate.identity.pnu;
      if (!deduplicated.has(pnu)) deduplicated.set(pnu, candidate);
    }
  }
  const candidates = [...deduplicated.values()].slice(0, MAX_ADDRESS_CANDIDATES);
  const failedOutcomes = outcomes.filter((outcome) => outcome.status !== "ok" && outcome.status !== "empty");
  const partialFailure = candidates.length > 0 && failedOutcomes.length > 0;
  const status = partialFailure
    ? aggregateSearchStatus(failedOutcomes)
    : candidates.length ? "ok" : aggregateSearchStatus(outcomes);
  const limited = deduplicated.size > MAX_ADDRESS_CANDIDATES;
  const message = partialFailure
    ? "일부 주소 유형 조회가 실패했지만 확인된 후보는 표시합니다."
    : limited
      ? `상위 ${MAX_ADDRESS_CANDIDATES}개 필지 후보를 표시합니다.`
      : candidates.length === 0 && status === "empty"
        ? "일치하는 도로명·지번 주소가 없습니다."
        : outcomes.find((outcome) => outcome.message)?.message;
  return {
    candidates,
    cards: [],
    sources: [source("vworld-address", VWORLD_SOURCE_LABEL, status, context, message)],
    ...(message ? { message } : {}),
  };
}

function validateSelectedIdentity(identity: Record<string, string>): ParcelIdentity | null {
  const derived = deriveParcelIdentity(identity.pnu);
  if (!derived) return null;
  for (const key of ["legalDongCode", "sigunguCd", "bjdongCd", "platGbCd", "bun", "ji"] as const) {
    if (identity[key] !== derived[key]) return null;
  }
  return derived;
}

function decodedServiceKey(key: string) {
  try {
    return decodeURIComponent(key);
  } catch {
    return key;
  }
}

function registerUrl(
  operation: "getBrRecapTitleInfo" | "getBrTitleInfo",
  parcel: ParcelIdentity,
  key: string,
  pageNo: number,
) {
  const url = new URL(`${BUILDING_REGISTER_BASE_URL}/${operation}`);
  url.searchParams.set("serviceKey", decodedServiceKey(key));
  url.searchParams.set("sigunguCd", parcel.sigunguCd);
  url.searchParams.set("bjdongCd", parcel.bjdongCd);
  url.searchParams.set("platGbCd", parcel.platGbCd);
  url.searchParams.set("bun", parcel.bun);
  url.searchParams.set("ji", parcel.ji);
  url.searchParams.set("numOfRows", String(BUILDING_PAGE_SIZE));
  url.searchParams.set("pageNo", String(pageNo));
  url.searchParams.set("_type", "json");
  return url.toString();
}

function approvalFailure(code: string, message: string) {
  return /^(20|30|31)$/u.test(code)
    || /SERVICE_ACCESS_DENIED|PERMISSION_DENIED|KEY_IS_(?:NULL|NOT_REGISTERED)|DEADLINE_HAS_EXPIRED/u.test(message);
}

function responseFailure(code: string, message: string): Pick<RegisterOutcome, "status" | "message"> | null {
  if (code === "00" || code === "0000") return null;
  const normalizedMessage = message.toUpperCase();
  if (approvalFailure(code, normalizedMessage)) {
    return {
      status: "unconfigured",
      message: "건축물대장 API 활용신청 또는 인증키 승인이 필요합니다.",
    };
  }
  if (code === "05" || normalizedMessage.includes("SERVICETIMEOUT")) {
    return { status: "timeout", message: "건축물대장 원천 응답 시간이 초과되었습니다." };
  }
  return { status: "error", message: "건축물대장 API가 오류를 반환했습니다." };
}

function parseRegisterPage(payload: unknown): {
  rows: JsonRecord[];
  totalCount: number;
  failure: Pick<RegisterOutcome, "status" | "message"> | null;
} | null {
  if (!isRecord(payload) || !isRecord(payload.response)) return null;
  const response = payload.response;
  const header = isRecord(response.header) ? response.header : null;
  const body = isRecord(response.body) ? response.body : null;
  if (!header) return null;
  const code = text(header.resultCode) ?? "";
  const message = text(header.resultMsg) ?? "";
  const failure = responseFailure(code, message);
  if (failure) return { rows: [], totalCount: 0, failure };
  if (!body) return null;

  const itemsContainer = body.items;
  let rawItems: unknown[] = [];
  if (isRecord(itemsContainer)) {
    const item = itemsContainer.item;
    rawItems = Array.isArray(item) ? item : isRecord(item) ? [item] : [];
  } else if (Array.isArray(itemsContainer)) {
    rawItems = itemsContainer;
  }
  const rows = rawItems.filter(isRecord);
  const rawTotal = text(body.totalCount);
  const parsedTotal = rawTotal === null ? Number.NaN : Number(rawTotal);
  const totalCount = Number.isFinite(parsedTotal) && parsedTotal >= 0 ? Math.trunc(parsedTotal) : rows.length;
  return { rows, totalCount, failure: null };
}

async function loadRegisterRows(
  operation: "getBrRecapTitleInfo" | "getBrTitleInfo",
  parcel: ParcelIdentity,
  context: LookupContext,
): Promise<RegisterOutcome> {
  const rows: JsonRecord[] = [];
  let totalCount = 0;
  try {
    for (let pageNo = 1; rows.length < MAX_BUILDING_ROWS; pageNo += 1) {
      const payload = await context.requestJson(
        registerUrl(operation, parcel, context.credentials.publicDataKey as string, pageNo),
        { cache: "no-store" },
      );
      const page = parseRegisterPage(payload);
      if (!page) {
        return { status: "error", rows: [], totalCount: 0, truncated: false, message: "건축물대장 응답 형식을 확인할 수 없습니다." };
      }
      if (page.failure) {
        return { ...page.failure, rows: [], totalCount: 0, truncated: false };
      }
      totalCount = Math.max(totalCount, page.totalCount);
      rows.push(...page.rows.slice(0, MAX_BUILDING_ROWS - rows.length));
      if (page.rows.length < BUILDING_PAGE_SIZE || rows.length >= page.totalCount) break;
    }
  } catch (error) {
    const failure = failureState(error);
    return {
      ...failure,
      rows: [],
      totalCount: 0,
      truncated: false,
      message: failure.status === "timeout"
        ? "건축물대장 원천 응답 시간이 초과되었습니다."
        : "건축물대장 원천 연결을 확인하지 못했습니다.",
    };
  }
  return {
    status: rows.length ? "ok" : "empty",
    rows,
    totalCount,
    truncated: totalCount > rows.length,
  };
}

const numberFormat = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });

function finiteNumber(value: unknown): number | null {
  const raw = text(value);
  if (raw === null) return null;
  const parsed = Number(raw.replace(/,/gu, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function area(value: unknown) {
  const parsed = finiteNumber(value);
  return parsed === null ? "정보 없음" : `${numberFormat.format(parsed)}㎡`;
}

function ratio(value: unknown) {
  const parsed = finiteNumber(value);
  return parsed === null ? "정보 없음" : `${numberFormat.format(parsed)}%`;
}

function date(value: unknown): string {
  const raw = text(value);
  if (!raw) return "정보 없음";
  const digits = raw.replace(/[^0-9]/gu, "");
  if (!/^\d{8}$/u.test(digits) || digits === "00000000") return "정보 없음";
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
}

function floors(row: JsonRecord) {
  const ground = finiteNumber(row.grndFlrCnt);
  const underground = finiteNumber(row.ugrndFlrCnt);
  const labels = [
    ground === null ? null : `지상 ${numberFormat.format(ground)}층`,
    underground === null ? null : `지하 ${numberFormat.format(underground)}층`,
  ].filter((value): value is string => value !== null);
  return labels.length ? labels.join(" · ") : "정보 없음";
}

function asOf(row: JsonRecord) {
  const normalized = date(row.crtnDay);
  return normalized === "정보 없음" ? undefined : normalized;
}

function cardId(prefix: string, row: JsonRecord, index: number) {
  const external = text(row.mgmBldrgstPk);
  return `${prefix}:${external ?? index + 1}`;
}

function buildingTitle(row: JsonRecord, fallback: string) {
  const parts = [plainText(row.bldNm), plainText(row.dongNm)]
    .filter((value, index, values): value is string => Boolean(value) && values.indexOf(value) === index);
  return parts.length ? parts.join(" · ") : fallback;
}

function buildingCard(
  row: JsonRecord,
  parcel: ParcelIdentity,
  index: number,
  kind: "recap" | "title",
  multipleTitles: boolean,
): LookupCard {
  const roadAddress = plainText(row.newPlatPlc);
  const lotAddress = plainText(row.platPlc);
  const recordType = kind === "recap" ? "총괄표제부" : "표제부";
  const updateDate = asOf(row);
  return {
    id: cardId(`building-${kind}`, row, index),
    presentation: "building",
    title: buildingTitle(row, kind === "recap" ? "대지 총괄표제부" : `건축물 ${index + 1}`),
    sourceLabel: BUILDING_SOURCE_LABEL,
    subtitle: roadAddress ?? lotAddress ?? `PNU ${parcel.pnu}`,
    fields: [
      { label: "대장 구분", value: recordType },
      { label: "PNU", value: parcel.pnu },
      { label: "법정동코드", value: parcel.legalDongCode },
      { label: "지번 주소", value: lotAddress ?? "정보 없음" },
      { label: "도로명 주소", value: roadAddress ?? "정보 없음" },
      { label: "주용도", value: plainText(row.mainPurpsCdNm) ?? plainText(row.etcPurps) ?? "정보 없음" },
      { label: "연면적", value: area(row.totArea) },
      { label: "대지면적", value: area(row.platArea) },
      { label: "층수", value: floors(row) },
      { label: "사용승인일", value: date(row.useAprDay) },
      { label: "건폐율", value: ratio(row.bcRat) },
      { label: "용적률", value: ratio(row.vlRat) },
    ],
    links: [{ label: "공식 원천", url: BUILDING_REGISTER_SOURCE_URL }],
    note: kind === "title" && multipleTitles
      ? "같은 필지에서 반환된 각 동을 별도 카드로 표시하며 대표 건물을 임의로 확정하지 않습니다."
      : "건축물대장 공개 항목이며 소유자·전유부 개인정보는 조회하지 않습니다.",
    ...(updateDate ? { asOf: updateDate } : {}),
  };
}

function aggregateRegisterStatus(outcomes: RegisterOutcome[]): ProviderState {
  if (outcomes.some((outcome) => outcome.status === "ok")) return "ok";
  if (outcomes.every((outcome) => outcome.status === "empty")) return "empty";
  if (outcomes.some((outcome) => outcome.status === "unconfigured")) return "unconfigured";
  if (outcomes.some((outcome) => outcome.status === "timeout")) return "timeout";
  return "error";
}

export async function loadAddress(
  identity: Record<string, string>,
  context: LookupContext,
): Promise<ProviderResult> {
  const parcel = validateSelectedIdentity(identity);
  if (!parcel) {
    return {
      candidates: [],
      cards: [],
      sources: [source("vworld-address", VWORLD_SOURCE_LABEL, "error", context, "선택한 필지 식별자를 검증하지 못했습니다.")],
      message: "주소 후보를 다시 선택해 주세요.",
    };
  }

  const selectedSource = source(
    "vworld-address",
    VWORLD_SOURCE_LABEL,
    "ok",
    context,
    `선택 PNU ${parcel.pnu}`,
  );
  if (!context.credentials.publicDataKey) {
    return {
      candidates: [],
      cards: [],
      sources: [
        selectedSource,
        source(
          "data-go-kr-building-register",
          BUILDING_SOURCE_LABEL,
          "unconfigured",
          context,
          "건축물대장 API 구성이 필요합니다.",
        ),
      ],
      message: "주소는 확인했지만 건축물대장 원천이 구성되지 않았습니다.",
    };
  }

  const [recap, titles] = await Promise.all([
    loadRegisterRows("getBrRecapTitleInfo", parcel, context),
    loadRegisterRows("getBrTitleInfo", parcel, context),
  ]);
  const cards = [
    ...recap.rows.map((row, index) => buildingCard(row, parcel, index, "recap", false)),
    ...titles.rows.map((row, index) => buildingCard(row, parcel, index, "title", titles.rows.length > 1)),
  ];
  const latestAsOf = cards.map((card) => card.asOf).filter((value): value is string => Boolean(value)).sort().at(-1);
  const truncated = recap.truncated || titles.truncated;
  const failedOutcomes = [recap, titles].filter((outcome) => outcome.status !== "ok" && outcome.status !== "empty");
  const partialFailure = cards.length > 0 && failedOutcomes.length > 0;
  const status = partialFailure
    ? aggregateRegisterStatus(failedOutcomes)
    : aggregateRegisterStatus([recap, titles]);
  const registerMessage = truncated
    ? `건축물대장 ${recap.totalCount + titles.totalCount}건 중 ${cards.length}건을 안전 한도 내에서 표시합니다.`
    : partialFailure
      ? "일부 건축물대장 조회가 실패했지만 확인된 공개 항목은 표시합니다."
      : titles.rows.length > 1
        ? `같은 필지의 동별 표제부 ${titles.rows.length}건을 모두 별도 카드로 표시합니다.`
        : cards.length === 0 && status === "empty"
          ? "선택한 필지에 공개된 표제부·총괄표제부가 없습니다."
          : [recap, titles].find((outcome) => outcome.message)?.message;
  return {
    candidates: [],
    cards,
    sources: [
      selectedSource,
      source(
        "data-go-kr-building-register",
        BUILDING_SOURCE_LABEL,
        status,
        context,
        registerMessage,
        latestAsOf,
      ),
    ],
    ...(registerMessage ? { message: registerMessage } : {}),
  };
}
