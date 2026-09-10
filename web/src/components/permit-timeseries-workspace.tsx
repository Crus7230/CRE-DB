"use client";

import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";
import {
  normalizePermitTimeseries,
  type PermitEventType,
  type PermitGroup,
  type PermitTimeseriesResponse,
} from "@/lib/permit-timeseries-contract";
import styles from "./permit-timeseries-workspace.module.css";

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
const exactAreaNumber = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });
const exactArea = (value: number) => `${exactAreaNumber.format(value)}㎡`;

type PermitAggregate = {
  permitCount: number;
  totalFloorAreaM2: number;
  missingAreaCount: number;
  invalidAreaCount: number;
};

const validAreaRecordCount = (point: PermitAggregate) => Math.max(
  0,
  point.permitCount - point.missingAreaCount - point.invalidAreaCount,
);
const hasValidArea = (point: PermitAggregate) => validAreaRecordCount(point) > 0;
const percent = (part: number, total: number) => total === 0
  ? "—"
  : `${(part / total * 100).toFixed(1)}%`;

function queryString(filters: Filters) {
  const params = new URLSearchParams({ groupBy: filters.groupBy });
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.eventType) params.set("eventType", filters.eventType);
  return params.toString();
}

function PermitChart({ data }: { data: PermitTimeseriesResponse }) {
  const [hoveredMonth, setHoveredMonth] = useState<string | null>(null);
  const [focusedMonth, setFocusedMonth] = useState<string | null>(null);
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const [rovingMonth, setRovingMonth] = useState<string | null>(null);
  const monthTargets = useRef(new Map<string, SVGRectElement>());
  const points = useMemo(() => {
    const byMonth = new Map<string, PermitAggregate>();
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

  const activeMonth = hoveredMonth ?? focusedMonth ?? selectedMonth;
  const activeIndex = points.findIndex(([month]) => month === activeMonth);
  const activePoint = activeIndex < 0 ? null : points[activeIndex];
  const selectedPoint = points.find(([month]) => month === selectedMonth) ?? null;
  const tabbableMonth = rovingMonth && points.some(([month]) => month === rovingMonth)
    ? rovingMonth
    : points.at(-1)?.[0] ?? null;
  const groupLabel = groups.find((item) => item.key === data.groupBy)?.label ?? "그룹";
  const eventLabel = eventTypes.find((item) => item.key === data.filters.eventType)?.label ?? "전체 단계";
  const selectedRows = useMemo(() => {
    if (!selectedMonth) return [];
    return data.series.flatMap((series) => {
      const monthPoints = series.points.filter((point) => point.month === selectedMonth);
      if (monthPoints.length === 0) return [];
      const aggregate = monthPoints.reduce<PermitAggregate>((current, point) => ({
        permitCount: current.permitCount + point.permitCount,
        totalFloorAreaM2: current.totalFloorAreaM2 + point.totalFloorAreaM2,
        missingAreaCount: current.missingAreaCount + point.missingAreaCount,
        invalidAreaCount: current.invalidAreaCount + point.invalidAreaCount,
      }), { permitCount: 0, totalFloorAreaM2: 0, missingAreaCount: 0, invalidAreaCount: 0 });
      return [{ key: series.key, label: series.label, ...aggregate }];
    }).sort((left, right) => right.permitCount - left.permitCount || left.label.localeCompare(right.label, "ko"));
  }, [data.series, selectedMonth]);
  const chooseMonth = (month: string) => {
    setRovingMonth(month);
    setSelectedMonth((current) => current === month ? null : month);
  };
  const clearMonthSelection = () => {
    const month = selectedMonth;
    setSelectedMonth(null);
    setHoveredMonth(null);
    if (!month) return;
    setRovingMonth(month);
    monthTargets.current.get(month)?.focus();
  };
  const focusMonthAt = (index: number) => {
    const month = points[Math.max(0, Math.min(points.length - 1, index))]?.[0];
    if (!month) return;
    setRovingMonth(month);
    monthTargets.current.get(month)?.focus();
  };
  const monthAriaLabel = (month: string, point: PermitAggregate) => {
    const quality = [
      point.missingAreaCount > 0 ? `면적 누락 ${point.missingAreaCount.toLocaleString("ko-KR")}건` : null,
      point.invalidAreaCount > 0 ? `면적 오류 ${point.invalidAreaCount.toLocaleString("ko-KR")}건` : null,
    ].filter(Boolean).join(", ");
    return `${month}, 기록 ${point.permitCount.toLocaleString("ko-KR")}건, ${hasValidArea(point) ? `연면적 ${exactArea(point.totalFloorAreaM2)}` : "연면적 확인 불가"}${quality ? `, ${quality}` : ""}. 선택 월 집계 보기`;
  };

  return <section
    className={`permit-chart ${styles.chartCard}`}
    aria-labelledby="permit-chart-title"
    onKeyDown={(event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      clearMonthSelection();
    }}
  >
    <header>
      <div><p className="eyebrow">MONTHLY OBSERVATIONS</p><h2 id="permit-chart-title">월별 기록과 연면적</h2></div>
      <div className="permit-chart-legend" aria-label="차트 범례"><span className="count">기록</span><span className="floor-area">연면적</span></div>
    </header>
    <div className={styles.chartViewport}>
      <svg viewBox="0 0 630 162" role="group" aria-labelledby="permit-chart-svg-title permit-chart-svg-description">
        <title id="permit-chart-svg-title">월별 인허가 기록 수와 연면적 합계</title>
        <desc id="permit-chart-svg-description">{data.selectedFrom}부터 {data.selectedThrough}까지의 집계입니다. 각 월의 전체 세로 영역을 선택하면 현재 필터 기준 그룹별 월 집계를 확인할 수 있습니다.</desc>
        {selectedPoint && <rect
          data-permit-month-selection={selectedPoint[0]}
          className={styles.monthSelection}
          x={plot.left + points.findIndex(([month]) => month === selectedPoint[0]) * slot + 0.75}
          y={plot.top}
          width={Math.max(0, slot - 1.5)}
          height={plot.bottom - plot.top}
          rx="2"
          style={{ fill: "rgb(35 124 105 / 12%)" }}
        />}
        {[maxCount, maxCount / 2, 0].map((tick, index) => <g key={`${tick}-${index}`}>
          <line x1={plot.left} x2={plot.right} y1={countY(tick)} y2={countY(tick)} />
          <text x={plot.left - 7} y={countY(tick) + 3} textAnchor="end">{Math.round(tick).toLocaleString("ko-KR")}</text>
          <text x={plot.right + 7} y={countY(tick) + 3}>{hasAnyValidArea ? area(maxArea * (1 - index / 2)) : "—"}</text>
        </g>)}
        {maxCount === 0 && maxArea === 0 && <text className="permit-chart-empty" x="315" y="78" textAnchor="middle">선택 범위에 집계된 인허가 기록이 없습니다</text>}
        {points.map(([month, point], index) => {
          const barX = plot.left + index * slot + (slot - barWidth) / 2;
          const height = Math.max(point.permitCount === 0 ? 0 : 1.5, plot.bottom - countY(point.permitCount));
          return <rect key={month} className={index === points.length - 1 ? "latest" : undefined} x={barX} y={plot.bottom - height} width={barWidth} height={height}/>;
        })}
        {hasAnyValidArea && areaPaths.map((path, index) => <path key={`area-line-${index}`} className="permit-area-line" d={path}/>)}
        {hasAnyValidArea && points.map(([month, point], index) => hasValidArea(point) && <circle key={`area-${month}`} className="permit-area-point" cx={x(index)} cy={areaY(point.totalFloorAreaM2)} r={index === points.length - 1 ? 3 : 1.8}/>)}
        <text className="permit-chart-period" x={plot.left} y="156">{points[0]?.[0] ?? data.selectedFrom}</text>
        <text className="permit-chart-period" x={plot.right} y="156" textAnchor="end">{points.at(-1)?.[0] ?? data.selectedThrough}</text>
        {points.map(([month, point], index) => <rect
          key={`target-${month}`}
          className={styles.monthHitTarget}
          data-month={month}
          role="button"
          tabIndex={tabbableMonth === month ? 0 : -1}
          aria-label={monthAriaLabel(month, point)}
          aria-pressed={selectedMonth === month}
          aria-controls={selectedMonth === month ? "permit-selected-month-panel" : undefined}
          ref={(node) => {
            if (node) monthTargets.current.set(month, node);
            else monthTargets.current.delete(month);
          }}
          x={plot.left + index * slot}
          y={plot.top}
          width={slot}
          height={plot.bottom - plot.top}
          style={{ fill: "transparent" }}
          onPointerEnter={() => setHoveredMonth(month)}
          onPointerLeave={() => setHoveredMonth((current) => current === month ? null : current)}
          onFocus={() => {
            setRovingMonth(month);
            setFocusedMonth(month);
          }}
          onBlur={() => setFocusedMonth((current) => current === month ? null : current)}
          onClick={() => chooseMonth(month)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              chooseMonth(month);
            } else if (event.key === "ArrowLeft") {
              event.preventDefault();
              focusMonthAt(index - 1);
            } else if (event.key === "ArrowRight") {
              event.preventDefault();
              focusMonthAt(index + 1);
            } else if (event.key === "Home") {
              event.preventDefault();
              focusMonthAt(0);
            } else if (event.key === "End") {
              event.preventDefault();
              focusMonthAt(points.length - 1);
            }
          }}
        />)}
      </svg>
      {activePoint && <div
        className={styles.monthTooltip}
        role="tooltip"
        style={{ left: `clamp(8px, calc(${x(activeIndex) / 630 * 100}% - 110px), calc(100% - 228px))` }}
      >
        <strong>{activePoint[0]}</strong>
        <span><b>기록</b>{activePoint[1].permitCount.toLocaleString("ko-KR")}건</span>
        <span><b>연면적</b>{hasValidArea(activePoint[1]) ? exactArea(activePoint[1].totalFloorAreaM2) : "확인 불가"}</span>
        {activePoint[1].missingAreaCount > 0 && <span><b>면적 누락</b>{activePoint[1].missingAreaCount.toLocaleString("ko-KR")}건</span>}
        {activePoint[1].invalidAreaCount > 0 && <span><b>면적 오류</b>{activePoint[1].invalidAreaCount.toLocaleString("ko-KR")}건</span>}
        {data.filters.eventType === null && <small>전체 단계 합계는 단계 간 중복 가능한 누적면적입니다.</small>}
      </div>}
    </div>
    {selectedPoint && <section id="permit-selected-month-panel" className={styles.selectedMonthPanel} aria-labelledby="permit-selected-month-title">
      <header className={styles.selectedMonthHeader}>
        <div><p className="eyebrow">SELECTED MONTH</p><h3 id="permit-selected-month-title">{selectedPoint[0]} 선택 월 집계</h3></div>
        <button type="button" onClick={clearMonthSelection}>{selectedPoint[0]} 선택 해제</button>
      </header>
      <p className={styles.aggregationGrain}>현재 필터(기준 단계: {eventLabel}, 묶어보기: {groupLabel})의 선택 월 × {groupLabel} 집계입니다. 나머지 차원은 합산되며 개별 건축물·사업 기록이 아닙니다.{data.filters.eventType === null ? " 전체 단계 연면적은 단계 간 중복 가능한 누적면적입니다." : ""}</p>
      <div className={styles.selectedMonthTotals} aria-label={`${selectedPoint[0]} 선택 월 품질 합계`}>
        <span><b>기록</b>{selectedPoint[1].permitCount.toLocaleString("ko-KR")}건</span>
        <span><b>연면적</b>{hasValidArea(selectedPoint[1]) ? exactArea(selectedPoint[1].totalFloorAreaM2) : "확인 불가"}</span>
        <span><b>면적 유효</b>{validAreaRecordCount(selectedPoint[1]).toLocaleString("ko-KR")}건</span>
        <span><b>누락</b>{selectedPoint[1].missingAreaCount.toLocaleString("ko-KR")}건</span>
        <span><b>오류</b>{selectedPoint[1].invalidAreaCount.toLocaleString("ko-KR")}건</span>
      </div>
      <div className={styles.selectedMonthTableWrap}>
        <table aria-label={`${selectedPoint[0]} 선택 월 ${groupLabel}별 집계`}>
          <thead><tr><th>{groupLabel}</th><th>기록</th><th>기록 비중</th><th>연면적</th><th>면적 비중</th><th>누락</th><th>오류</th></tr></thead>
          <tbody>{selectedRows.map((row) => <tr key={row.key}>
            <th>{row.label}</th>
            <td>{row.permitCount.toLocaleString("ko-KR")}</td>
            <td>{percent(row.permitCount, selectedPoint[1].permitCount)}</td>
            <td>{hasValidArea(row) ? exactArea(row.totalFloorAreaM2) : "확인 불가"}</td>
            <td>{hasValidArea(row) && selectedPoint[1].totalFloorAreaM2 > 0 ? percent(row.totalFloorAreaM2, selectedPoint[1].totalFloorAreaM2) : "—"}</td>
            <td>{row.missingAreaCount.toLocaleString("ko-KR")}</td>
            <td>{row.invalidAreaCount.toLocaleString("ko-KR")}</td>
          </tr>)}</tbody>
          <tfoot><tr><th>합계</th><td>{selectedPoint[1].permitCount.toLocaleString("ko-KR")}</td><td>{selectedPoint[1].permitCount === 0 ? "—" : "100.0%"}</td><td>{hasValidArea(selectedPoint[1]) ? exactArea(selectedPoint[1].totalFloorAreaM2) : "확인 불가"}</td><td>{hasValidArea(selectedPoint[1]) && selectedPoint[1].totalFloorAreaM2 > 0 ? "100.0%" : "—"}</td><td>{selectedPoint[1].missingAreaCount.toLocaleString("ko-KR")}</td><td>{selectedPoint[1].invalidAreaCount.toLocaleString("ko-KR")}</td></tr></tfoot>
        </table>
      </div>
    </section>}
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
      <div className={`permit-data-grid ${styles.dataGrid}`}><PermitChart data={data}/><GroupSummary data={data}/></div>
      <footer className="permit-method">
        <div><b>범위</b><span>서울특별시 · 분석 범위 포함(IN_SCOPE) · 검토 후보 제외 · 완료 스냅샷</span><small>각 행은 고유 건축물이나 사업의 수가 아니라 원천 인허가 이벤트 기록입니다. 전국 건축시장 결론으로 확대 해석하지 않습니다.</small></div>
        <div><b>출처</b><span>{data.source.label} · 원천 기준일 {data.sourceAsOfDate}</span><small>실제 허가·착공·사용승인일이 1900년 이후이며 현재일을 넘지 않는 기록 · 면적 누락·오류는 연면적 합계에서 제외</small></div>
      </footer>
    </>}
  </section>;
}
