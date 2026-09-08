"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { ContextTooltip } from "@/components/context-tooltip";
import { normalizeMacroTimeseries, type MacroSeriesGroup, type MacroTimeseriesPoint, type MacroTimeseriesResponse, type MacroTimeseriesSeries } from "@/lib/macro-timeseries-contract";

const REQUEST_TIMEOUT_MS = 10_000;
type RangeKey = "5Y" | "10Y" | "20Y" | "MAX";
const ranges: Array<{ key: RangeKey; label: string; months: number }> = [
  { key: "5Y", label: "5년", months: 60 },
  { key: "10Y", label: "10년", months: 120 },
  { key: "20Y", label: "20년", months: 240 },
  { key: "MAX", label: "전체", months: Number.POSITIVE_INFINITY },
];
const groups: Array<{ key: MacroSeriesGroup; eyebrow: string; title: string; note: string }> = [
  { key: "KOREA", eyebrow: "KOREA RATES", title: "한국 금리", note: "기준금리 · 단기조달 · 국고채 · 회사채" },
  { key: "US_POLICY", eyebrow: "US POLICY & FUNDING", title: "미국 정책·조달", note: "목표범위 · EFFR · SOFR" },
  { key: "US_TREASURY", eyebrow: "US TREASURY CURVE", title: "미국 국채", note: "2년 · 10년 · 30년 · 장단기차" },
];

const monthNumber = (value: string) => Number(value.slice(0, 4)) * 12 + Number(value.slice(5)) - 1;
const monthText = (value: number) => `${Math.floor(value / 12)}-${String(value % 12 + 1).padStart(2, "0")}`;
const monthsBetween = (from: string, through: string) => Array.from({ length: monthNumber(through) - monthNumber(from) + 1 }, (_, index) => monthText(monthNumber(from) + index));
const rate = (value: number | undefined, spread = false) => value === undefined ? "—" : `${value.toFixed(2)}${spread ? "%p" : "%"}`;
const bp = (value: number | undefined) => {
  if (value === undefined) return "—";
  const rounded = Math.round(value * 100);
  return `${rounded > 0 ? "+" : ""}${rounded}bp`;
};
const sourceUrl = (source: string) => {
  const key = source.toLowerCase();
  if (key.includes("ecos") || key.includes("한국은행")) return "https://ecos.bok.or.kr/";
  if (key.includes("new york fed") || key.includes("ny fed") || key.includes("뉴욕연방")) return "https://www.newyorkfed.org/markets/reference-rates";
  if (key.includes("treasury") || key.includes("미국 재무부")) return "https://home.treasury.gov/resource-center/data-chart-center/interest-rates";
  return undefined;
};

function visiblePath(points: MacroTimeseriesPoint[], months: string[], domain?: { low: number; high: number }) {
  const start = monthNumber(months[0]);
  const end = monthNumber(months.at(-1)!);
  const visible = points.filter((point) => monthNumber(point.month) >= start && monthNumber(point.month) <= end);
  const values = visible.map((point) => point.value);
  const low = domain?.low ?? (values.length ? Math.min(...values) : 0);
  const high = domain?.high ?? (values.length ? Math.max(...values) : 0);
  const span = high - low;
  const x = (month: string) => months.length === 1 ? 380 : 42 + (monthNumber(month) - start) / (months.length - 1) * 670;
  const y = (value: number) => span === 0 ? 38 : 66 - (value - low) / span * 54;
  const segments: MacroTimeseriesPoint[][] = [];
  visible.forEach((point) => {
    const current = segments.at(-1);
    if (!current || monthNumber(point.month) - monthNumber(current.at(-1)!.month) > 1) segments.push([point]);
    else current.push(point);
  });
  return { visible, low, high, x, y, singletons: segments.filter((segment) => segment.length === 1).map((segment) => segment[0]), paths: segments.filter((segment) => segment.length > 1).map((segment) => segment.map((point, index) => `${index ? "L" : "M"}${x(point.month).toFixed(2)},${y(point.value).toFixed(2)}`).join(" ")) };
}

function MacroStrip({ series, months, selectedMonth, onSelectMonth, domain }: { series: MacroTimeseriesSeries; months: string[]; selectedMonth: string; onSelectMonth: (month: string) => void; domain?: { low: number; high: number } }) {
  const chart = useMemo(() => visiblePath(series.points, months, domain), [series.points, months, domain]);
  const selected = series.points.find((point) => point.month === selectedMonth);
  const previousMonth = monthText(monthNumber(selectedMonth) - 1);
  const previous = series.points.find((point) => point.month === previousMonth);
  const selectedX = chart.x(selectedMonth);
  const spread = series.code === "US_TREASURY_10Y_MINUS_2Y";
  const benchmarkPoints = chart.visible.filter((point) => point.month <= selectedMonth).slice(-12);
  const benchmark = benchmarkPoints.length ? benchmarkPoints.reduce((sum, point) => sum + point.value, 0) / benchmarkPoints.length : undefined;
  const benchmarkY = benchmark === undefined ? undefined : chart.y(benchmark);
  const benchmarkDelta = selected && benchmark !== undefined ? selected.value - benchmark : undefined;
  const benchmarkLabel = benchmarkPoints.length
    ? `최근 ${benchmarkPoints.length}개 관측 평균`
    : "관측 평균 없음";
  return <article className={`macro-strip macro-series-row group-${series.group.toLowerCase()}`} data-testid="macro-strip" data-selected-month={selectedMonth}>
    <header className="macro-series-identity"><strong>{series.name}</strong><ContextTooltip label="공식 출처" detail={`${series.source} · 원천 갱신 ${series.sourceVintageAt.slice(0, 10)}`} href={sourceUrl(series.source)} align="start"><small>{series.source}</small></ContextTooltip></header>
    <div className="macro-series-chart">
      <div className="macro-strip-scale" aria-hidden="true"><span>최고 {rate(chart.high, spread)}</span><span>최저 {rate(chart.low, spread)}</span></div>
      <svg viewBox="0 0 720 76" preserveAspectRatio="none" tabIndex={0} role="slider" aria-label={`${series.name} 공통 조회 월`} aria-valuemin={0} aria-valuemax={months.length - 1} aria-valuenow={Math.max(0, months.indexOf(selectedMonth))} aria-valuetext={`${selectedMonth} · ${rate(selected?.value, spread)}`} onPointerMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        const ratio = box.width ? Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) : 0;
        const plotRatio = Math.max(0, Math.min(1, (ratio * 720 - 42) / 670));
        onSelectMonth(months[Math.round(plotRatio * (months.length - 1))]);
      }} onKeyDown={(event) => {
        const index = months.indexOf(selectedMonth);
        if (event.key === "ArrowLeft" && index > 0) { event.preventDefault(); onSelectMonth(months[index - 1]); }
        if (event.key === "ArrowRight" && index < months.length - 1) { event.preventDefault(); onSelectMonth(months[index + 1]); }
      }}>
        <line className="macro-guide" x1="42" y1="12" x2="712" y2="12"/><line className="macro-guide" x1="42" y1="39" x2="712" y2="39"/><line className="macro-guide" x1="42" y1="66" x2="712" y2="66"/>
        {spread && chart.low <= 0 && chart.high >= 0 && <line className="macro-zero-line" x1="42" y1={chart.y(0)} x2="712" y2={chart.y(0)}/>}
        {benchmarkY !== undefined && <line className="macro-benchmark-line" x1="42" y1={benchmarkY} x2="712" y2={benchmarkY}/>}
        {chart.paths.map((path, index) => <path key={index} className="macro-line" d={path}/>) }
        {chart.singletons.map((point) => <circle key={point.month} className="macro-isolated-point" cx={chart.x(point.month)} cy={chart.y(point.value)} r="2.5"/>)}
        <line className="macro-crosshair" x1={selectedX} y1="4" x2={selectedX} y2="72"/>
        {selected && <circle className={selected.partial ? "macro-point partial" : "macro-point"} cx={selectedX} cy={chart.y(selected.value)} r="3.5"/>}
      </svg>
      <footer><span>{months[0]}</span><span>점선: {benchmarkLabel}</span><span>{months.at(-1)}</span></footer>
    </div>
    <div className="macro-strip-value" aria-label={`${series.name} ${selectedMonth} 상세값`}><time dateTime={selectedMonth}>{selectedMonth}</time><ContextTooltip label={`${series.name} · ${selectedMonth}`} detail={selected ? `${selected.partial ? "부분월" : "완료월"} 관측 · 원천 관측 ${selected.observationCount}개${spread ? " · 10년물 금리에서 2년물 금리를 차감한 %p" : " · 금리 수준 %"}` : "해당 월의 공식 관측값이 없습니다."} align="end"><b>{rate(selected?.value, spread)}</b></ContextTooltip><span className={!selected || !previous ? "neutral" : selected.value >= previous.value ? "up" : "down"}>{!selected ? "해당 월 관측 없음" : previous ? `전월 대비 ${bp(selected.value - previous.value)}` : "전월 관측 없음"}</span><ContextTooltip label={benchmarkLabel} detail="선택 월까지 현재 조회 구간에 존재하는 완료월 관측치 중 최근 최대 12개의 단순평균입니다. 결측월은 0이나 보간값으로 채우지 않으므로 12개월 달력 평균과 다를 수 있습니다." align="end"><small>{benchmark === undefined ? "관측 평균 없음" : `${benchmarkLabel} ${rate(benchmark, spread)} · 평균 대비 ${bp(benchmarkDelta)}`}</small></ContextTooltip></div>
  </article>;
}

export function MacroTimeseriesWorkspace() {
  const [data, setData] = useState<MacroTimeseriesResponse | null>(null);
  const [error, setError] = useState<"TIMEOUT" | "REQUEST" | null>(null);
  const [range, setRange] = useState<RangeKey>("10Y");
  const [selectedMonth, setSelectedMonth] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
    fetch("/api/market/timeseries", { signal: controller.signal, credentials: "same-origin" })
      .then((response) => { if (!response.ok) throw new Error("request failed"); return response.json(); })
      .then((value) => normalizeMacroTimeseries(value))
      .then((value) => { if (!disposed) { setData(value); setSelectedMonth(value.completeThrough); setError(null); } })
      .catch((reason: unknown) => {
        if (disposed) return;
        if (timedOut) setError("TIMEOUT");
        else if (!(reason instanceof DOMException && reason.name === "AbortError")) setError("REQUEST");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [retryKey]);

  const visibleMonths = useMemo(() => {
    if (!data) return [];
    const selectedRange = ranges.find((item) => item.key === range)!;
    const end = monthNumber(data.completeThrough);
    const start = Number.isFinite(selectedRange.months) ? Math.max(monthNumber(data.availableFrom), end - selectedRange.months + 1) : monthNumber(data.availableFrom);
    return monthsBetween(monthText(start), data.completeThrough);
  }, [data, range]);

  if (error) return <section className="macro-dashboard macro-state error" role="alert"><strong>{error === "TIMEOUT" ? "금리 시계열 조회 시간이 초과되었습니다." : "금리 시계열을 불러오지 못했습니다."}</strong><p>공식 시계열 연결을 확인한 뒤 다시 시도해 주세요.</p><button type="button" onClick={() => setRetryKey((value) => value + 1)}><RefreshCw aria-hidden="true" size={14}/>다시 조회</button></section>;
  if (!data || !visibleMonths.length) return <section className="macro-dashboard macro-state" role="status">공식 금리 시계열을 불러오는 중입니다.</section>;

  const safeSelectedMonth = visibleMonths.includes(selectedMonth) ? selectedMonth : data.completeThrough;
  const selectedIndex = Math.max(0, visibleMonths.indexOf(safeSelectedMonth));
  return <section className="macro-dashboard domain-workspace" aria-labelledby="macro-dashboard-title">
    <header className="macro-heading">
      <div><p className="eyebrow">MACRO RATE MONITOR</p><h1 id="macro-dashboard-title">금리의 방향을 한 화면에서</h1><p>동일 그룹 공통 축 · 결측월 무보간 · 완료월 기준</p></div>
      <div className="macro-asof"><span>공통 선택 월</span><strong aria-live="polite">{safeSelectedMonth}</strong><small>공식값 또는 일별값 월평균</small></div>
    </header>

    <section className="macro-controls" aria-label="시계열 조회 범위와 공통 월">
      <div className="macro-range" role="group" aria-label="조회 기간">{ranges.map((item) => <button key={item.key} type="button" aria-pressed={range === item.key} onClick={() => { setRange(item.key); setSelectedMonth(data.completeThrough); }}>{item.label}</button>)}</div>
      <label><span>{visibleMonths[0]}</span><input type="range" aria-label="공통 조회 월" aria-valuetext={safeSelectedMonth} min="0" max={visibleMonths.length - 1} value={selectedIndex} onChange={(event) => setSelectedMonth(visibleMonths[Number(event.target.value)])}/><span>{data.completeThrough}</span></label>
      <div className="macro-method"><b>그룹 공통 축</b><span>같은 그룹은 동일한 세로 눈금 · 스프레드 0%p 기준선</span><small>정확한 값과 전월 bp 변화는 카드 우측 표시</small></div>
    </section>

    <div className="macro-groups">{groups.map((group) => {
      const items = data.series.filter((series) => series.group === group.key);
      const rangeStart = monthNumber(visibleMonths[0]);
      const rangeEnd = monthNumber(visibleMonths.at(-1)!);
      const levelValues = items.filter((series) => series.code !== "US_TREASURY_10Y_MINUS_2Y").flatMap((series) => series.points.filter((point) => monthNumber(point.month) >= rangeStart && monthNumber(point.month) <= rangeEnd).map((point) => point.value));
      const sharedDomain = levelValues.length ? { low: Math.min(...levelValues), high: Math.max(...levelValues) } : undefined;
      return <section className={`macro-group group-${group.key.toLowerCase()}`} key={group.key} aria-labelledby={`macro-${group.key}`}>
        <header><div><p className="eyebrow">{group.eyebrow}</p><h2 id={`macro-${group.key}`}>{group.title}</h2></div><span>{group.note}</span></header>
        <div className="macro-series-list">{items.map((series) => {
          const isSpread = series.code === "US_TREASURY_10Y_MINUS_2Y";
          const spreadValues = isSpread ? series.points.filter((point) => monthNumber(point.month) >= rangeStart && monthNumber(point.month) <= rangeEnd).map((point) => point.value) : [];
          const domain = isSpread ? { low: Math.min(0, ...spreadValues), high: Math.max(0, ...spreadValues) } : sharedDomain;
          return <MacroStrip key={series.code} series={series} months={visibleMonths} selectedMonth={safeSelectedMonth} onSelectMonth={setSelectedMonth} domain={domain}/>;
        })}</div>
      </section>;
    })}</div>

    <footer className="macro-lineage"><div><b>기준</b><span>ECOS 월별 공표값 · NY Fed/미 재무부 일별값의 월평균</span></div><div><b>범위</b><span>{data.availableFrom}~{data.completeThrough} 완료월 · 원천 최신 {data.availableThrough}</span></div><p>미발행·휴일·원천 결측은 보간하지 않습니다. 부분월은 기본 그래프에서 제외합니다.</p></footer>
  </section>;
}
