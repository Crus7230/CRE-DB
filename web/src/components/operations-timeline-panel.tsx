"use client";

import { useEffect, useMemo, useState } from "react";
import { normalizeOperationsTimeline, type OperationsTimelineResponse, type TimelinePoint } from "@/lib/operations-timeline-contract";

const number = new Intl.NumberFormat("ko-KR");
const width = 900;
const height = 260;
const pad = 28;

function points(series: TimelinePoint[], key: "publicationCount" | "eventCount" | "ingestionCount", max: number) {
  if (!series.length) return "";
  return series.map((item, index) => {
    const x = pad + index * ((width - pad * 2) / Math.max(series.length - 1, 1));
    const y = height - pad - item[key] / Math.max(max, 1) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

export function OperationsTimelinePanel() {
  const [data, setData] = useState<OperationsTimelineResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/operations/timeline?windowDays=90", { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error("request failed"); return response.json(); })
      .then(normalizeOperationsTimeline).then(setData)
      .catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); });
    return () => controller.abort();
  }, []);

  const max = useMemo(() => data ? Math.max(1, ...data.series.flatMap((item) => [item.publicationCount, item.eventCount, item.ingestionCount])) : 1, [data]);

  if (error) return <div className="state-block error-state"><strong>시계열을 불러오지 못했습니다.</strong></div>;
  if (!data) return <div className="state-block"><span className="spinner"/><strong>시계열 집계 중</strong></div>;

  const publicationTotal = data.series.reduce((sum, item) => sum + item.publicationCount, 0);
  const eventTotal = data.series.reduce((sum, item) => sum + item.eventCount, 0);
  const ingestionTotal = data.series.reduce((sum, item) => sum + item.ingestionCount, 0);
  return <section className="timeline-panel">
    <section className="timeline-clock-cards" aria-label="시계열 시간축">
      <article><span className="clock-dot publication"/><div><strong>발행일 기준</strong><small>원문 published_at만 사용</small></div><b>{number.format(publicationTotal)}</b></article>
      <article><span className="clock-dot event"/><div><strong>사건일 기준</strong><small>canonical event_date_start</small></div><b>{number.format(eventTotal)}</b></article>
      <article><span className="clock-dot ingestion"/><div><strong>적재일 기준</strong><small>collected_at · 운영 clock</small></div><b>{number.format(ingestionTotal)}</b></article>
    </section>
    <section className="operations-notice timeline-warning"><strong>적재 급증은 시장 급증이 아닙니다</strong><p>backfill과 재수집은 적재일 계열만 증가시킵니다. 발행일 미상 {number.format(data.publicationUnknownCount)}건 · archive 문서 {number.format(data.archivedDocumentExcludedCount)}건은 publication 추이에서 제외합니다.</p></section>
    <section className="timeline-chart-card">
      <header><div><p className="eyebrow">90 DAY CLOCKS</p><h3>발행·사건·적재 흐름</h3></div><span>발행일 미상 {number.format(data.publicationUnknownCount)}건</span></header>
      <svg role="img" aria-label="90일 시계열 차트" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <line x1={pad} y1={height-pad} x2={width-pad} y2={height-pad} className="chart-axis"/>
        <polyline points={points(data.series,"publicationCount",max)} className="timeline-line publication"/>
        <polyline points={points(data.series,"eventCount",max)} className="timeline-line event"/>
        <polyline points={points(data.series,"ingestionCount",max)} className="timeline-line ingestion"/>
      </svg>
      <footer><span>{data.series[0]?.date ?? "-"}</span><span>일 최대 {number.format(max)}</span><span>{data.series.at(-1)?.date ?? "-"}</span></footer>
    </section>
  </section>;
}
