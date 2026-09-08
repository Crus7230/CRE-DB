"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";
import {
  normalizePermitTimeseries,
  type PermitEventType,
  type PermitGroup,
  type PermitTimeseriesResponse,
} from "@/lib/permit-timeseries-contract";

const REQUEST_TIMEOUT_MS = 10_000;

const groups: Array<{ key: PermitGroup; label: string }> = [
  { key: "EVENT_TYPE", label: "진행 단계" },
  { key: "ASSET_TYPE", label: "자산 유형" },
  { key: "DISTRICT", label: "자치구" },
  { key: "CONSTRUCTION_ACTION", label: "공사 구분" },
];

const eventTypes: Array<{ key: PermitEventType; label: string }> = [
  { key: "PERMIT", label: "건축허가" },
  { key: "ACTUAL_START", label: "착공" },
  { key: "USE_APPROVAL", label: "사용승인" },
];

type Filters = {
  groupBy: PermitGroup;
  from: string;
  to: string;
  eventType: PermitEventType | "";
};

const initialFilters: Filters = {
  groupBy: "ASSET_TYPE",
  from: "",
  to: "",
  eventType: "PERMIT",
};

const number = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });
const area = (value: number) => value >= 100_000_000
  ? `${number.format(value / 100_000_000)}억㎡`
  : value >= 10_000
    ? `${number.format(value / 10_000)}만㎡`
    : `${number.format(value)}㎡`;

function queryString(filters: Filters) {
  const params = new URLSearchParams({ groupBy: filters.groupBy });
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.eventType) params.set("eventType", filters.eventType);
  return params.toString();
}

function PermitChart({ data }: { data: PermitTimeseriesResponse }) {
  const points = useMemo(() => {
    const byMonth = new Map<string, {
      permitCount: number;
      totalFloorAreaM2: number;
      missingAreaCount: number;
      invalidAreaCount: number;
    }>();
    for (const series of data.series) {
      for (const point of series.points) {
        const current = byMonth.get(point.month) ?? {
          permitCount: 0,
          totalFloorAreaM2: 0,
          missingAreaCount: 0,
          invalidAreaCount: 0,
        };
        current.permitCount += point.permitCount;
        current.totalFloorAreaM2 += point.totalFloorAreaM2;
        current.missingAreaCount += point.missingAreaCount;
        current.invalidAreaCount += point.invalidAreaCount;
        byMonth.set(point.month, current);
      }
    }
    return [...byMonth].sort(([left], [right]) => left.localeCompare(right));
  }, [data]);
  const maxCount = Math.max(0, ...points.map(([, point]) => point.permitCount));
  const hasValidArea = (point: (typeof points)[number][1]) => (
    point.permitCount > point.missingAreaCount + point.invalidAreaCount
  );
  const hasAnyValidArea = points.some(([, point]) => hasValidArea(point));
  const maxArea = Math.max(0, ...points.map(([, point]) => (
    hasValidArea(point) ? point.totalFloorAreaM2 : 0
  )));
  const plot = { left: 48, right: 582, top: 15, bottom: 134 };
  const slot = (plot.right - plot.left) / Math.max(points.length, 1);
  const barWidth = Math.max(2, Math.min(13, slot * 0.66));
  const x = (index: number) => plot.left + index * slot + slot / 2;
  const countY = (value: number) => maxCount === 0
    ? plot.bottom
    : plot.bottom - value / maxCount * (plot.bottom - plot.top);
  const areaY = (value: number) => maxArea === 0
    ? plot.bottom
    : plot.bottom - value / maxArea * (plot.bottom - plot.top);
  const areaPaths: string[] = [];
  let areaSegment: string[] = [];
  points.forEach(([, point], index) => {
    if (!hasValidArea(point)) {
      if (areaSegment.length) areaPaths.push(areaSegment.join(" "));
      areaSegment = [];
      return;
    }
    areaSegment.push(
      `${areaSegment.length === 0 ? "M" : "L"}${x(index).toFixed(2)},${areaY(point.totalFloorAreaM2).toFixed(2)}`,
    );
  });
  if (areaSegment.length) areaPaths.push(areaSegment.join(" "));

  return <section className="permit-chart" aria-labelledby="permit-chart-title">
    <header>
      <div><p className="eyebrow">MONTHLY OBSERVATIONS</p><h2 id="permit-chart-title">월별 기록과 연면적</h2></div>
      <div className="permit-chart-legend" aria-label="차트 범례"><span className="count">기록</span><span className="floor-area">연면적</span></div>
    </header>
    <svg viewBox="0 0 630 162" role="img" aria-label={`${data.selectedFrom}부터 ${data.selectedThrough}까지 월별 인허가 기록 막대와 연면적 선 그래프`}>
      <title>월별 인허가 기록 수와 연면적 합계</title>
      {[maxCount, maxCount / 2, 0].map((tick, index) => <g key={`${tick}-${index}`}>
        <line x1={plot.left} x2={plot.right} y1={countY(tick)} y2={countY(tick)} />
        <text x={plot.left - 7} y={countY(tick) + 3} textAnchor="end">{Math.round(tick).toLocaleString("ko-KR")}</text>
        <text x={plot.right + 7} y={countY(tick) + 3}>{hasAnyValidArea ? area(maxArea * (1 - index / 2)) : "—"}</text>
      </g>)}
      {maxCount === 0 && maxArea === 0 && <text className="permit-chart-empty" x="315" y="78" textAnchor="middle">선택 범위에 집계된 인허가 기록이 없습니다</text>}
      {points.map(([month, point], index) => {
        const x = plot.left + index * slot + (slot - barWidth) / 2;
        const height = Math.max(point.permitCount === 0 ? 0 : 1.5, plot.bottom - countY(point.permitCount));
        return <rect key={month} className={index === points.length - 1 ? "latest" : undefined} x={x} y={plot.bottom - height} width={barWidth} height={height}>
          <title>{month} · {point.permitCount.toLocaleString("ko-KR")}개 기록 · {hasValidArea(point) ? `연면적 ${area(point.totalFloorAreaM2)}` : "연면적 확인 불가"}</title>
        </rect>;
      })}
      {hasAnyValidArea && areaPaths.map((path, index) => <path key={`area-line-${index}`} className="permit-area-line" d={path}/>)}
      {hasAnyValidArea && points.map(([month, point], index) => hasValidArea(point) && <circle key={`area-${month}`} className="permit-area-point" cx={x(index)} cy={areaY(point.totalFloorAreaM2)} r={index === points.length - 1 ? 3 : 1.8}>
        <title>{month} 연면적 {area(point.totalFloorAreaM2)}</title>
      </circle>)}
      <text className="permit-chart-period" x={plot.left} y="156">{points[0]?.[0] ?? data.selectedFrom}</text>
      <text className="permit-chart-period" x={plot.right} y="156" textAnchor="end">{points.at(-1)?.[0] ?? data.selectedThrough}</text>
    </svg>
  </section>;
}

function GroupSummary({ data }: { data: PermitTimeseriesResponse }) {
  const rows = useMemo(() => data.series.map((series) => ({
    key: series.key,
    label: series.label,
    permitCount: series.points.reduce((sum, point) => sum + point.permitCount, 0),
    totalFloorAreaM2: series.points.reduce((sum, point) => sum + point.totalFloorAreaM2, 0),
    missingAreaCount: series.points.reduce((sum, point) => sum + point.missingAreaCount, 0),
    invalidAreaCount: series.points.reduce((sum, point) => sum + point.invalidAreaCount, 0),
  })).sort((left, right) => right.permitCount - left.permitCount || left.label.localeCompare(right.label, "ko")), [data]);
  return <section className="permit-breakdown" aria-labelledby="permit-breakdown-title">
    <header><div><p className="eyebrow">BREAKDOWN</p><h2 id="permit-breakdown-title">{groups.find((item) => item.key === data.groupBy)?.label}별 합계</h2></div><span>{rows.length}개 구분</span></header>
    <div className="permit-breakdown-table"><table>
      <thead><tr><th>구분</th><th>기록</th><th>비중</th><th>연면적</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.key}><th>{row.label}</th><td>{row.permitCount.toLocaleString("ko-KR")}</td><td>{data.quality.permitCount === 0 ? "—" : `${(row.permitCount / data.quality.permitCount * 100).toFixed(1)}%`}</td><td>{row.permitCount > row.missingAreaCount + row.invalidAreaCount ? area(row.totalFloorAreaM2) : "—"}</td></tr>)}</tbody>
    </table></div>
  </section>;
}

export function PermitTimeseriesWorkspace() {
  const [draft, setDraft] = useState<Filters>(initialFilters);
  const [applied, setApplied] = useState<Filters>(initialFilters);
  const [data, setData] = useState<PermitTimeseriesResponse | null>(null);
  const [error, setError] = useState<"TIMEOUT" | "REQUEST" | null>(null);
  const [formError, setFormError] = useState("");
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
        const response = await fetch(`/api/market/permits?${queryString(applied)}`, {
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("request failed");
        const normalized = normalizePermitTimeseries(await response.json());
        if (!disposed) setData(normalized);
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
  }, [applied, retryKey]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (draft.from && draft.to && draft.from > draft.to) {
      setFormError("시작월은 종료월보다 늦을 수 없습니다.");
      return;
    }
    setFormError("");
    setData(null);
    setError(null);
    setApplied({ ...draft });
  };

  const chooseGroup = (groupBy: PermitGroup) => {
    const next = { ...draft, groupBy };
    setDraft(next);
    setData(null);
    setError(null);
    setApplied(next);
    setFormError("");
  };

  const reset = () => {
    setDraft(initialFilters);
    setData(null);
    setError(null);
    setApplied(initialFilters);
    setFormError("");
  };

  const retry = () => {
    setData(null);
    setError(null);
    setRetryKey((value) => value + 1);
  };

  const validAreaRecordCount = data
    ? Math.max(0, data.quality.permitCount - data.quality.missingAreaCount - data.quality.invalidAreaCount)
    : 0;

  return <section className="permit-workspace" aria-labelledby="permit-title">
    <header className="permit-heading">
      <div><p className="eyebrow">SEOUL BUILDING PIPELINE</p><h1 id="permit-title">서울 건축 인허가 흐름</h1><p>완료된 원천 스냅샷에서 실제 허가·착공·사용승인일이 확인된 기록만 월별로 집계합니다.</p></div>
      <div className="permit-scope"><strong>서울특별시</strong><span>완료 스냅샷</span><span>실제 허가·착공·사용승인일</span></div>
    </header>

    <form className="permit-controls" onSubmit={submit} aria-label="인허가 시계열 필터">
      <fieldset><legend>묶어보기</legend><div className="permit-group-switch">{groups.map((group) => <button key={group.key} type="button" aria-pressed={draft.groupBy === group.key} onClick={() => chooseGroup(group.key)}>{group.label}</button>)}</div></fieldset>
      <div className="permit-period-control"><span>기간 <small>미입력 시 최근 60개월</small></span><label>시작월<input aria-label="인허가 시작월" type="month" value={draft.from} onChange={(event) => setDraft((current) => ({ ...current, from: event.target.value }))}/></label><i aria-hidden="true">–</i><label>종료월<input aria-label="인허가 종료월" type="month" value={draft.to} onChange={(event) => setDraft((current) => ({ ...current, to: event.target.value }))}/></label></div>
      <label className="permit-event-control">기준 단계<select value={draft.eventType} onChange={(event) => setDraft((current) => ({ ...current, eventType: event.target.value as Filters["eventType"] }))}><option value="">전체 단계</option>{eventTypes.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
      <div className="permit-control-actions"><button type="submit">적용</button><button type="button" className="secondary" onClick={reset}><RotateCcw aria-hidden="true" size={13}/>초기화</button></div>
      {formError && <p role="alert">{formError}</p>}
    </form>

    {error && <section className="permit-state" role="alert"><strong>{error === "TIMEOUT" ? "인허가 조회 시간이 초과되었습니다." : "인허가 시계열을 불러오지 못했습니다."}</strong><span>필터를 확인하거나 잠시 뒤 다시 조회해 주세요.</span><button type="button" onClick={retry}><RefreshCw aria-hidden="true" size={14}/>다시 조회</button></section>}
    {!data && !error && <section className="permit-state" role="status">서울 인허가 관측값을 불러오는 중입니다.</section>}
    {data && <>
      <div className="permit-selection" aria-label="현재 인허가 조회 조건">
        <span><b>기간</b>{data.selectedFrom}–{data.selectedThrough}</span>
        <span><b>기준 단계</b>{eventTypes.find((item) => item.key === data.filters.eventType)?.label ?? "전체"}</span>
        <span><b>집계</b>{groups.find((item) => item.key === data.groupBy)?.label}</span>
        <span><b>원천 기준일</b>{data.sourceAsOfDate}</span>
      </div>
      <p className="permit-lag-note">최근월은 수집 진행에 따라 변동될 수 있습니다.</p>
      <section className="permit-kpis" aria-label="인허가 선택 범위 합계">
        <article><span>인허가 기록</span><strong>{data.quality.permitCount.toLocaleString("ko-KR")}</strong><small>허가·착공·사용승인 원천 기록</small></article>
        <article><span>연면적 합계</span><strong>{validAreaRecordCount > 0 ? area(data.quality.totalFloorAreaM2) : "—"}</strong><small>{validAreaRecordCount > 0 ? (data.filters.eventType === null ? "단계 간 중복 가능한 누적면적" : `${eventTypes.find((item) => item.key === data.filters.eventType)?.label} 유효 면적 합계`) : "유효 면적 기록 없음"}</small></article>
        <article><span>면적 누락</span><strong>{data.quality.missingAreaCount.toLocaleString("ko-KR")}</strong><small>원천 면적 없음</small></article>
        <article><span>면적 오류</span><strong>{data.quality.invalidAreaCount.toLocaleString("ko-KR")}</strong><small>합계에서 제외</small></article>
      </section>
      <div className="permit-data-grid"><PermitChart data={data}/><GroupSummary data={data}/></div>
      <footer className="permit-method">
        <div><b>범위</b><span>서울특별시 · 분석 범위 포함(IN_SCOPE) · 검토 후보 제외 · 완료 스냅샷</span><small>각 행은 고유 건축물이나 사업의 수가 아니라 원천 인허가 이벤트 기록입니다. 전국 건축시장 결론으로 확대 해석하지 않습니다.</small></div>
        <div><b>출처</b><span>{data.source.label} · 원천 기준일 {data.sourceAsOfDate}</span><small>실제 허가·착공·사용승인일이 1900년 이후이며 현재일을 넘지 않는 기록 · 면적 누락·오류는 연면적 합계에서 제외</small></div>
      </footer>
    </>}
  </section>;
}
