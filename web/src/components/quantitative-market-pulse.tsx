"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { ContextTooltip } from "@/components/context-tooltip";
import { normalizeQuantitativeMarketPulse, type QuantitativeMarketPulse as Pulse } from "@/lib/quantitative-market-pulse-contract";

const REQUEST_TIMEOUT_MS = 10_000;
const number = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });
const compact = (value: number, maximumFractionDigits = 1) => new Intl.NumberFormat("ko-KR", { maximumFractionDigits }).format(value);
const signedPct = (value: number | null) => value === null ? "—" : `${value > 0 ? "↑ " : value < 0 ? "↓ " : "→ "}${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
const oneDecimal = (value: number) => (Math.round((value + Number.EPSILON) * 10) / 10).toFixed(1);
const krw = (value: number | null) => value === null ? "—" : value >= 1_000_000_000_000 ? `${compact(value / 1_000_000_000_000, 2)}조 원` : `${Math.round(value / 100_000_000).toLocaleString("ko-KR")}억 원`;
const area = (value: number | null) => value === null ? "—" : value >= 10_000 ? `${compact(value / 10_000)}만㎡` : `${number.format(value)}㎡`;
const trillion = (value: number) => `${compact(value / 1_000_000_000_000, 1)}조`;
const pulseSourceUrl = (source: string) => source.includes("국토교통부") || source.includes("실거래") ? "https://rt.molit.go.kr/" : undefined;
const periodLabel = (period: string) => {
  const [year, month] = period.split("-");
  return `${year}년 ${Number(month)}월 신고 거래 현황`;
};
const plainAmountBasis = (value: string) => value
  .replaceAll("canonical payload", "중복 제외 신고")
  .replaceAll("payload", "신고 내용");
const plainExclusion = (value: string) => value
  .replaceAll("동일 API payload 중복", "동일 내용 중복")
  .replaceAll("payload", "신고 내용");

function TrendChart({ pulse }: { pulse: Pulse }) {
  const points = pulse.trend;
  const values = points.map((point) => Number(point.amountKrw));
  const maxValue = Math.max(0, ...values);
  const plot = { left: 54, right: 590, top: 12, bottom: 146 };
  const plotWidth = plot.right - plot.left;
  const plotHeight = plot.bottom - plot.top;
  const slot = plotWidth / Math.max(points.length, 1);
  const barWidth = Math.max(4, Math.min(18, slot * 0.62));
  const y = (value: number) => maxValue === 0 ? plot.bottom : plot.bottom - value / maxValue * plotHeight;
  const recent = values.slice(-12);
  const average = recent.reduce((sum, value) => sum + value, 0) / Math.max(recent.length, 1);
  const averageLabel = `최근 ${recent.length}개 완료월 평균`;
  const averageY = y(average);
  const ticks = maxValue === 0 ? [0] : [maxValue, maxValue / 2, 0];
  return <div className="market-pulse-trend">
    <header><div><p className="eyebrow">최근 {points.length}개 완료월</p><h3>서울 대형 비주거 신고 거래금액</h3></div><span>단위: 조 원 · 점선 {averageLabel} {trillion(average)} 원 · {pulse.asOfPeriod} 기준</span></header>
    <svg viewBox="0 0 600 176" role="img" aria-label={`${points[0]?.period}부터 ${points.at(-1)?.period}까지 완료월별 거래금액 막대그래프, ${averageLabel} ${trillion(average)}`}>
      <title>완료월별 거래금액과 {averageLabel}</title>
      {ticks.map((tick) => <g key={tick}><line className="market-pulse-gridline" x1={plot.left} y1={y(tick)} x2={plot.right} y2={y(tick)}/><text className="market-pulse-axis" x={plot.left - 7} y={y(tick) + 3} textAnchor="end">{trillion(tick)}</text></g>)}
      <line className="market-pulse-average" x1={plot.left} y1={averageY} x2={plot.right} y2={averageY}/>
      {maxValue === 0 && <text className="market-pulse-empty" x={(plot.left + plot.right) / 2} y={(plot.top + plot.bottom) / 2} textAnchor="middle">관측기간 내 적격 고유 신고행 없음</text>}
      {points.map((point, index) => {
        const value = values[index];
        const x = plot.left + index * slot + (slot - barWidth) / 2;
        const height = Math.max(value === 0 ? 0 : 1.5, plot.bottom - y(value));
        return <rect key={point.period} className={index === points.length - 1 ? "market-pulse-bar latest" : "market-pulse-bar"} x={x} y={plot.bottom - height} width={barWidth} height={height}><title>{point.period} · {krw(value)} · 고유 신고행 {point.transactionCount}건</title></rect>;
      })}
      <text className="market-pulse-period-label" x={plot.left} y="169">{points[0]?.period}</text>
      <text className="market-pulse-period-label" x={plot.right} y="169" textAnchor="end">{points.at(-1)?.period}</text>
    </svg>
    <div className="market-pulse-table-wrap"><table><caption>최근 {Math.min(6, points.length)}개 완료월 신고 거래금액·고유 신고행·면적</caption><thead><tr><th>월</th><th>신고 거래금액</th><th>고유 신고행</th><th>면적</th></tr></thead><tbody>{points.slice(-6).reverse().map((point) => <tr key={point.period}><th>{point.period}</th><td>{krw(Number(point.amountKrw))}</td><td>{point.transactionCount}건</td><td>{area(Number(point.areaM2))}</td></tr>)}</tbody></table></div>
    <details className="market-pulse-full-table"><summary>전체 {points.length}개 완료월 표</summary><div className="market-pulse-table-wrap"><table><caption>전체 완료월 신고 거래금액·고유 신고행·면적</caption><thead><tr><th>월</th><th>신고 거래금액</th><th>고유 신고행</th><th>면적</th></tr></thead><tbody>{points.slice().reverse().map((point) => <tr key={point.period}><th>{point.period}</th><td>{krw(Number(point.amountKrw))}</td><td>{point.transactionCount}건</td><td>{area(Number(point.areaM2))}</td></tr>)}</tbody></table></div></details>
  </div>;
}

function Comparison({ mom, yoy }: { mom: number | null; yoy: number | null }) {
  const className = (value: number | null) => value === null || value === 0 ? "neutral" : value < 0 ? "down" : "up";
  return <div className="market-pulse-comparison"><span className={className(mom)}>전월 대비 {signedPct(mom)}</span><span className={className(yoy)}>전년 동월 대비 {signedPct(yoy)}</span></div>;
}

function MiniTrend({ pulse }: { pulse: Pulse }) {
  const values = pulse.trend.slice(-12).map((point) => Number(point.amountKrw));
  const maxValue = Math.max(1, ...values);
  const points = values.map((value, index) => `${values.length === 1 ? 0 : index * 240 / (values.length - 1)},${52 - value * 44 / maxValue}`).join(" ");
  return <svg className="market-pulse-mini-trend" viewBox="0 0 240 56" role="img" aria-label={`최근 ${values.length}개 관측월 거래금액 추이`} preserveAspectRatio="none"><polyline points={points}/></svg>;
}

export function QuantitativeMarketPulse({ variant = "full" }: { variant?: "full" | "summary" }) {
  const [pulse, setPulse] = useState<Pulse | null>(null);
  const [error, setError] = useState<"TIMEOUT" | "REQUEST" | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
    void (async () => {
      try {
        const response = await fetch("/api/market/pulse", { signal: controller.signal, credentials: "same-origin" });
        if (!response.ok) throw new Error("request failed");
        const data = normalizeQuantitativeMarketPulse(await response.json());
        if (!disposed) {
          setPulse(data);
          setError(null);
        }
      } catch (reason) {
        if (disposed) return;
        if (timedOut) setError("TIMEOUT");
        else if (!(reason instanceof DOMException && reason.name === "AbortError")) setError("REQUEST");
      } finally {
        window.clearTimeout(timeout);
      }
    })();
    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [retryKey]);

  const topThreeShare = useMemo(() => pulse?.concentration.topGroups.slice(0, 3).reduce((sum, item) => sum + item.sharePct, 0) ?? 0, [pulse]);
  if (error) return <section className="quantitative-market-pulse error" role="alert"><b>{error === "TIMEOUT" ? "거래 시계열 조회 시간이 초과되었습니다." : "거래 시계열을 불러오지 못했습니다."}</b><span>서울 거래 데이터 연결을 확인한 뒤 다시 시도해 주세요.</span><button type="button" onClick={() => setRetryKey((value) => value + 1)}><RefreshCw aria-hidden="true" size={14}/>다시 조회</button></section>;
  if (!pulse) return <section className="quantitative-market-pulse loading" role="status">서울 CRE 시장 수치를 계산하는 중입니다.</section>;

  const { amount, count, area: areaMetric, averageTicket, unitAmount } = pulse.metrics;
  if (variant === "summary") return <section className="quantitative-market-pulse summary" aria-labelledby="market-pulse-summary-title">
    <header className="market-pulse-summary-call">
      <div><p className="eyebrow">MARKET PULSE · {pulse.asOfPeriod}</p><h2 id="market-pulse-summary-title">{periodLabel(pulse.asOfPeriod)}</h2><p>{pulse.call.detail}</p><small className="transaction-lag-note">최근월은 신고 지연·정정으로 변동될 수 있습니다.</small></div>
      <MiniTrend pulse={pulse}/>
    </header>
    <div className="market-pulse-summary-metrics">
      <article><span>거래금액</span><strong>{krw(amount.value)}</strong><Comparison mom={amount.momPct} yoy={amount.yoyPct}/></article>
      <article><span>고유 신고행</span><strong>{number.format(count.value)}건</strong><Comparison mom={count.momPct} yoy={count.yoyPct}/></article>
      <article><span>거래면적</span><strong>{area(areaMetric.value)}</strong><Comparison mom={areaMetric.momPct} yoy={areaMetric.yoyPct}/></article>
      <article><span>신고행당 평균</span><strong>{krw(averageTicket.value)}</strong><Comparison mom={averageTicket.momPct} yoy={averageTicket.yoyPct}/></article>
    </div>
    <footer className="market-pulse-summary-foot"><span>금액 상위 3개 신고행 비중 <b>{count.value === 0 ? "—" : `${oneDecimal(topThreeShare)}%`}</b></span><small>{pulse.call.caution}</small></footer>
  </section>;

  return <section className="quantitative-market-pulse transaction-dashboard" aria-labelledby="market-pulse-title">
    <header className="market-pulse-call">
      <div><p className="eyebrow">SEOUL CRE MARKET PULSE · {pulse.asOfPeriod}</p><h2 id="market-pulse-title">{periodLabel(pulse.asOfPeriod)}</h2><p>{pulse.call.detail}</p><small className="transaction-lag-note">최근월은 신고 지연·정정으로 변동될 수 있습니다.</small></div>
      <div className="market-pulse-scope" aria-label="거래 시계열 범위">
        <strong>서울특별시 한정</strong>
        <span>{pulse.scope.population}</span>
        <span>{pulse.scope.areaRule}</span>
        <small>금액: 원 · 면적: ㎡ · 개수: 고유 신고행</small>
      </div>
    </header>

    <div className="market-pulse-metrics">
      <article className="primary"><span>거래금액</span><ContextTooltip label={`신고 거래금액 · ${pulse.asOfPeriod}`} detail="서울 비주거·집합건물 신고행 중 면적 기준을 통과하고 동일 내용 중복을 제외한 신고 거래금액 합계입니다." align="start"><strong>{krw(amount.value)}</strong></ContextTooltip><Comparison mom={amount.momPct} yoy={amount.yoyPct}/><small>연초 이후 누계 {amount.ytdValue === null ? "— · 완료월 부족" : `${krw(amount.ytdValue)} · 전년 동기 대비 ${signedPct(amount.ytdYoyPct)}`}</small></article>
      <article><span>고유 신고행</span><ContextTooltip label={`고유 신고행 · ${pulse.asOfPeriod}`} detail="경제적 거래 ID가 아니라 내용이 완전히 같은 중복을 제외한 신고행 수입니다. 실제 거래 건수와 다를 수 있습니다." align="end"><strong>{number.format(count.value)}건</strong></ContextTooltip><Comparison mom={count.momPct} yoy={count.yoyPct}/><small>연초 이후 누계 {count.ytdValue === null ? "— · 완료월 부족" : `${number.format(count.ytdValue)}건 · 전년 동기 대비 ${signedPct(count.ytdYoyPct)}`}</small></article>
      <article><span>거래면적</span><ContextTooltip label={`거래면적 · ${pulse.asOfPeriod}`} detail="분석 모집단에 포함된 고유 신고행의 건축물 거래면적 합계입니다." align="start"><strong>{area(areaMetric.value)}</strong></ContextTooltip><Comparison mom={areaMetric.momPct} yoy={areaMetric.yoyPct}/><small>연초 이후 누계 {areaMetric.ytdValue === null ? "— · 완료월 부족" : `${area(areaMetric.ytdValue)} · 전년 동기 대비 ${signedPct(areaMetric.ytdYoyPct)}`}</small></article>
      <article><span>신고행당 평균</span><ContextTooltip label={`신고행당 평균 · ${pulse.asOfPeriod}`} detail="기준월 신고 거래금액 합계를 고유 신고행 수로 나눈 산술평균입니다. 동일자산 가격지수가 아닙니다." align="end"><strong>{krw(averageTicket.value)}</strong></ContextTooltip><Comparison mom={averageTicket.momPct} yoy={averageTicket.yoyPct}/><small>면적당 {unitAmount.value === null ? "—" : `${Math.round(unitAmount.value / 10_000).toLocaleString("ko-KR")}만 원/㎡`} · 전월 대비 {signedPct(unitAmount.momPct)}</small></article>
    </div>

    <div className="market-pulse-grid">
      <TrendChart pulse={pulse}/>
      <aside className="market-pulse-drivers" aria-label="기준월 거래 기여 근거">
        <section><header><p className="eyebrow">WHAT DROVE IT</p><h3>금액 기여 권역</h3></header>{pulse.concentration.districts.length === 0 ? <p>기준월 고유 신고행 없음</p> : <ol>{pulse.concentration.districts.slice(0, 5).map((item) => <li key={item.district}><p>{item.district} · {oneDecimal(item.sharePct)}% · {krw(Number(item.amountKrw))}</p><span style={{ width: `${item.sharePct}%` }}/></li>)}</ol>}</section>
        <section><header><p className="eyebrow">TOP REPORTED ROWS</p><h3>상위 고유 신고행</h3></header>{pulse.concentration.topGroups.length === 0 ? <p>기준월 고유 신고행 없음</p> : <ol>{pulse.concentration.topGroups.map((item) => <li key={`${item.rank}-${item.dealDate}-${item.district}`}><p>{item.rank}. {item.district} {item.locality} · {krw(Number(item.amountKrw))} · {item.sharePct.toFixed(1)}%</p><small>{item.dealDate} · {item.buildingUse} · {area(Number(item.areaM2))}</small></li>)}</ol>}</section>
      </aside>
    </div>

    <footer className="market-pulse-method">
      <div><b>분석 모집단</b><span>{pulse.scope.geography} · {pulse.scope.population} · {pulse.scope.areaRule}</span><small><ContextTooltip label="분석 원천" detail={`${pulse.scope.source} · ${pulse.asOfPeriod} 완료월 기준 · ${plainAmountBasis(pulse.scope.amountBasis)}`} href={pulseSourceUrl(pulse.scope.source)} align="start">{pulse.scope.source}</ContextTooltip> · {plainAmountBasis(pulse.scope.amountBasis)}</small></div>
      <div><b>중복·품질</b><span><ContextTooltip label="중복 제거 품질" detail="원천 신고 내용이 완전히 같은 행만 제외하며, 주소·금액이 비슷하다는 이유만으로 별도 신고를 합치지 않습니다." align="start">원천 신고 {pulse.quality.sourceRowCount}행 · 동일 내용 중복 {pulse.quality.exactDuplicateRows}행 제외 · 분석 {pulse.quality.uniquePayloadCount}행</ContextTooltip></span><small>제외: {pulse.scope.exclusions.map(plainExclusion).join(" · ")}</small></div>
      <p>{pulse.call.caution}</p>
    </footer>
  </section>;
}
