import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuantitativeMarketPulse } from "@/components/quantitative-market-pulse";

const metric = (value: number, previousValue: number | null, yearAgoValue: number | null, momPct: number | null, yoyPct: number | null, ytdValue: number | null, priorYtdValue: number | null, ytdYoyPct: number | null) => ({ value, previousValue, yearAgoValue, momPct, yoyPct, ytdValue, priorYtdValue, ytdYoyPct });
const trend = Array.from({ length: 19 }, (_, index) => {
  const month = new Date(Date.UTC(2025, index, 1));
  const period = `${month.getUTCFullYear()}-${String(month.getUTCMonth() + 1).padStart(2, "0")}`;
  if (index === 17) return { period, transactionCount: 14, amountKrw: "1835841880000", areaM2: "176661.22", sourceRowCount: 14, uniquePayloadCount: 14 };
  if (index === 18) return { period, transactionCount: 12, amountKrw: "2203495600000", areaM2: "250983.21", sourceRowCount: 13, uniquePayloadCount: 12 };
  return { period, transactionCount: 0, amountKrw: "0", areaM2: "0", sourceRowCount: 0, uniquePayloadCount: 0 };
});
const payload = {
  generatedAt: "2026-08-31T02:00:00.000Z", asOfPeriod: "2026-07",
  call: { headline: "신고 거래금액 증가 · 고유 신고행 감소 — 대형 신고행 중심 반등", detail: "신고 거래금액 +20.0% · 고유 신고행 -14.3% · 신고행당 평균 40.0%", caution: "면적당 금액은 동일자산 가격지수가 아닙니다." },
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
  scope: { geography: "서울특별시", source: "국토교통부 실거래 공개시스템", population: "비주거용 부동산 실거래", areaRule: "개별 API 행 건물면적 > 3,300㎡", exclusions: ["취소 신고", "주거용", "동일 API payload 중복"], amountBasis: "신고 거래금액 · 원 단위 환산 · 보수적 canonical payload 행 기준" },
};

const mockFetch = (body: unknown, ok = true) => vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok, json: async () => body }));
afterEach(() => vi.unstubAllGlobals());

describe("QuantitativeMarketPulse", () => {
  it("renders consistent deduplicated counts, a neutral period label, and an accessible table caption", async () => {
    mockFetch(payload);
    render(<QuantitativeMarketPulse />);

    expect(await screen.findByRole("heading", { name: "2026년 7월 신고 거래 현황" })).toBeInTheDocument();
    expect(screen.getByText("최근월은 신고 지연·정정으로 변동될 수 있습니다.")).toBeInTheDocument();
    expect(screen.getByText("서울특별시 한정")).toBeInTheDocument();
    expect(screen.getByText("개별 API 행 건물면적 > 3,300㎡")).toBeInTheDocument();
    expect(screen.getByText("금액: 원 · 면적: ㎡ · 개수: 고유 신고행")).toBeInTheDocument();
    const amountCard = screen.getAllByText("거래금액")[0].closest("article") as HTMLElement;
    expect(within(amountCard).getByText("2.2조 원")).toBeInTheDocument();
    expect(screen.getByText("최근 19개 완료월")).toBeInTheDocument();
    expect(screen.getAllByText(/12개 완료월 평균/).length).toBeGreaterThan(0);
    expect(document.querySelectorAll(".market-pulse-bar")).toHaveLength(19);
    expect(screen.getByText("전월 대비 ↑ +20.0%")).toBeInTheDocument();
    expect(screen.getByText("전년 동월 대비 ↑ +22.8%")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "최근 6개 완료월 신고 거래금액·고유 신고행·면적" })).toBeInTheDocument();
    expect(screen.getByText("전체 19개 완료월 표")).toBeInTheDocument();
    expect(screen.getByText("원천 신고 13행 · 동일 내용 중복 1행 제외 · 분석 12행")).toBeInTheDocument();
    const amountTrigger = within(amountCard).getByText("2.2조 원").closest("[data-context-info]") as HTMLElement;
    expect(document.getElementById(amountTrigger.getAttribute("aria-describedby")!)).toHaveTextContent("거래금액 합계");
    const sourceTrigger = screen.getByText("국토교통부 실거래 공개시스템").closest("[data-context-info]") as HTMLElement;
    const sourceTooltip = document.getElementById(sourceTrigger.getAttribute("aria-describedby")!);
    expect(within(sourceTooltip as HTMLElement).getByRole("link", { name: /공식 출처 열기/ })).toHaveAttribute("href", "https://rt.molit.go.kr/");
  });

  it("does not present a partial January-to-reference-month sum as YTD", async () => {
    const incomplete = structuredClone(payload);
    incomplete.trend = incomplete.trend.slice(-2);
    incomplete.call.detail = "비교 불가 · 검증 완료 2개월만 표시";
    incomplete.metrics.amount = metric(2203495600000, 1835841880000, null, 20.03, null, null, null, null);
    incomplete.metrics.count = metric(12, 14, null, -14.29, null, null, null, null);
    incomplete.metrics.area = metric(250983.21, 176661.22, null, 42.07, null, null, null, null);
    mockFetch(incomplete);
    render(<QuantitativeMarketPulse />);

    expect(await screen.findByText("최근 2개 완료월")).toBeInTheDocument();
    expect(screen.getAllByText(/최근 2개 완료월 평균/).length).toBeGreaterThan(0);
    expect(screen.getByRole("table", { name: "최근 2개 완료월 신고 거래금액·고유 신고행·면적" })).toBeInTheDocument();
    expect(screen.getAllByText("연초 이후 누계 — · 완료월 부족")).toHaveLength(3);
    expect(screen.queryByText(/연초 이후 누계 7\.5조 원/)).not.toBeInTheDocument();
  });

  it("shows the independent error state for malformed payloads and inconsistent empty concentration", async () => {
    mockFetch({ ...payload, generatedAt: "not-iso", concentration: { topGroups: [], districts: [] } });
    render(<QuantitativeMarketPulse />);
    expect(await screen.findByRole("alert")).toHaveTextContent("거래 시계열을 불러오지 못했습니다");
  });

  it("renders a truthful no-transaction reference month without NaN or false concentration", async () => {
    const zero = structuredClone(payload);
    zero.call = { ...zero.call, headline: "전월 비교 불가 — 기준월 고유 신고행 없음" };
    zero.trend[18] = { period: "2026-07", transactionCount: 0, amountKrw: "0", areaM2: "0", sourceRowCount: 0, uniquePayloadCount: 0 };
    zero.metrics.amount = metric(0, 10, 5, -100, -100, 0, 5, -100);
    zero.metrics.count = metric(0, 1, 1, -100, -100, 0, 1, -100);
    zero.metrics.area = metric(0, 10, 5, -100, -100, 0, 5, -100);
    zero.metrics.averageTicket = { value: null, previousValue: 10, yearAgoValue: 5, momPct: null, yoyPct: null } as never;
    zero.metrics.unitAmount = { value: null, previousValue: 1, yearAgoValue: 1, momPct: null, yoyPct: null } as never;
    zero.concentration = { topGroups: [], districts: [] };
    zero.quality = { sourceRowCount: 0, transactionCount: 0, uniquePayloadCount: 0, exactDuplicateRows: 0 };
    mockFetch(zero);
    render(<QuantitativeMarketPulse />);
    expect(await screen.findByRole("heading", { name: "2026년 7월 신고 거래 현황" })).toBeInTheDocument();
    expect(screen.getAllByText("기준월 고유 신고행 없음").length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent("NaN");
  });
});
