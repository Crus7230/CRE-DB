"use client";

import { useEffect, useMemo, useState } from "react";
import { KeywordAnalyticsPanel } from "@/components/keyword-analytics-panel";
import { InsightSignalsPanel } from "@/components/insight-signals-panel";
import { ModelInterpretationsPanel } from "@/components/model-interpretations-panel";
import { OperationsTimelinePanel } from "@/components/operations-timeline-panel";
import { normalizeOperationsOverview, type OperationsOverviewResponse, type SourceHealthItem } from "@/lib/operations-insights-contract";

const number = new Intl.NumberFormat("ko-KR");
const dateTime = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" });

function formatDate(value: string | null) {
  if (!value) return "기록 없음";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "시각 확인 필요" : dateTime.format(parsed);
}

function onboardingLabel(item: SourceHealthItem) {
  if (item.onboarding === "DISABLED") return "비활성";
  if (item.onboarding === "NOT_ONBOARDED") return "미온보딩";
  return "온보딩";
}

function slaLabel(item: SourceHealthItem) {
  if (item.freshness === "NO_SLA") return "SLA 미정";
  if (item.freshness === "NEVER_SUCCEEDED") return "성공 이력 없음";
  if (item.freshness === "OVERDUE") return "기한 초과";
  if (item.freshness === "DUE") return "수집 예정";
  return "정상 주기";
}

function executionLabel(value: SourceHealthItem["latestExecution"]) {
  const labels: Record<SourceHealthItem["latestExecution"], string> = {
    NONE: "최근 실행 없음", QUEUED: "대기", RUNNING: "실행 중", COMPLETED: "완료",
    PARTIAL: "부분 완료", FAILED: "실패", CANCELLED: "취소",
  };
  return labels[value];
}

function outcomeLabel(value: SourceHealthItem["dataOutcome"]) {
  return value === "NEW_DATA" ? "신규·갱신" : value === "ZERO_RESULT" ? "정상 0건" : value === "REUSED_ONLY" ? "재발견" : "결과 미상";
}

export function OperationsInsightsWorkspace({ onOpenDocument = () => undefined }: { onOpenDocument?: (documentId: string, title: string) => void }) {
  const [data, setData] = useState<OperationsOverviewResponse | null>(null);
  const [error, setError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [view, setView] = useState<"SOURCE" | "QUALITY" | "TIMELINE" | "KEYWORDS" | "INSIGHTS" | "MODEL">("SOURCE");
  const overviewRequired = view === "SOURCE" || view === "QUALITY";

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => setError(false));
    fetch("/api/operations/overview", { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error("request failed"); return response.json(); })
      .then(normalizeOperationsOverview)
      .then(setData)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true);
      });
    return () => controller.abort();
  }, [retryKey]);

  const executionSummary = useMemo(() => data?.runStatusCounts.map((item) => `${item.status} ${number.format(item.count)}`).join(" · ") ?? "", [data]);

  return <section className="operations-workspace domain-workspace">
    <header className="workspace-hero operations-hero">
      <div><p className="eyebrow">OPERATIONS & INSIGHTS</p><h2>적재 상태부터 시장 신호까지 한 화면에서 점검</h2><p>수집 운영과 시장 변화를 분리해 보고, 모든 분석 결과를 원문 근거까지 추적합니다.</p></div>
      <div className="hero-stat"><span>기준 시각</span><strong>{data ? formatDate(data.asOfAt) : "불러오는 중"}</strong><small>{data?.policyVersion ?? "SOURCE HEALTH"}</small></div>
    </header>

    <nav className="operations-subtabs" aria-label="운영·인사이트 분석 화면">
      <button type="button" aria-pressed={view === "SOURCE"} onClick={() => setView("SOURCE")}><strong>적재상태</strong><span>source·job·run 최신성</span></button>
      <button type="button" aria-pressed={view === "QUALITY"} onClick={() => setView("QUALITY")}><strong>분류·검토</strong><span>coverage·review·evidence</span></button>
      <button type="button" aria-pressed={view === "TIMELINE"} onClick={() => setView("TIMELINE")}><strong>시계열</strong><span>발행·사건·적재 clock</span></button>
      <button type="button" aria-pressed={view === "KEYWORDS"} onClick={() => setView("KEYWORDS")}><strong>키워드</strong><span>급상승·연관어</span></button>
      <button type="button" aria-pressed={view === "INSIGHTS"} onClick={() => setView("INSIGHTS")}><strong>인사이트 신호</strong><span>검토상태·원문근거</span></button>
      <button type="button" aria-pressed={view === "MODEL"} onClick={() => setView("MODEL")}><strong>모델 해석</strong><span>version·review·lineage</span></button>
    </nav>

    {overviewRequired && !data && !error && <div className="state-block"><span className="spinner"/><strong>운영 현황 조회 중</strong></div>}
    {overviewRequired && error && <div className="state-block error-state"><strong>운영 현황을 불러오지 못했습니다.</strong><button type="button" onClick={() => setRetryKey((value) => value + 1)}>다시 조회</button></div>}

    {data && view === "SOURCE" && <>
      <section className="operations-kpis" aria-label="운영 핵심 지표">
        <article><span>전체 source</span><strong>{number.format(data.summary.sourceCount)}</strong><small>온보딩 {number.format(data.summary.onboardedSourceCount)} · 미온보딩 {number.format(data.summary.notOnboardedSourceCount)}</small></article>
        <article><span>고유 문서</span><strong>{number.format(data.summary.distinctDocumentCount)}</strong><small>document ID 기준</small></article>
        <article><span>문서 version</span><strong>{number.format(data.summary.documentVersionCount)}</strong><small>수정·재수집 별도</small></article>
        <article><span>수집 run</span><strong>{number.format(data.summary.runCount)}</strong><small>{executionSummary || "실행 이력 없음"}</small></article>
      </section>

      <section className="operations-notice"><strong>상태 해석 기준</strong><p>source SLA가 데이터 계약으로 등록되지 않은 경우 임의로 지연 판정을 하지 않고 ‘SLA 미정’으로 표시합니다. 발행일과 적재일은 시계열 단계에서 분리됩니다.</p></section>

      <section className="source-health-section">
        <header><div><p className="eyebrow">SOURCE HEALTH</p><h3>소스별 적재상태</h3></div><span>{number.format(data.sources.length)}개 source</span></header>
        <div className="source-health-table-wrap">
          <table className="source-health-table">
            <thead><tr><th>Source</th><th>온보딩</th><th>SLA 최신성</th><th>최근 실행</th><th>데이터 결과</th><th>고유 문서</th><th>Version</th><th>최근 성공</th></tr></thead>
            <tbody>{data.sources.map((item) => <tr key={item.sourceCode}>
              <td><strong>{item.sourceName}</strong><small>{item.sourceCode} · {item.sourceKind}</small></td>
              <td><span className={`axis-pill ${item.onboarding.toLowerCase()}`}>{onboardingLabel(item)}</span><small>활성 job {number.format(item.activeJobCount)}</small></td>
              <td><span className="axis-pill no-sla">{slaLabel(item)}</span><small>{item.slaMode}</small></td>
              <td><span className={`axis-pill execution-${item.latestExecution.toLowerCase()}`}>{executionLabel(item.latestExecution)}</span><small>run {number.format(item.runCount)}</small></td>
              <td><span className="axis-pill outcome">{outcomeLabel(item.dataOutcome)}</span><small>발견 {item.latestDiscoveredCount === null ? "-" : number.format(item.latestDiscoveredCount)}</small></td>
              <td>{number.format(item.distinctDocumentCount)}</td><td>{number.format(item.documentVersionCount)}</td><td>{formatDate(item.latestSuccessfulAt)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>
    </>}

    {data && view === "QUALITY" && <>
      <section className="operations-kpis" aria-label="분류 품질 핵심 지표">
        <article><span>Current assignment</span><strong>{number.format(data.classificationQuality.currentAssignmentCount)}</strong><small>serving target 기준</small></article>
        <article><span>Superseded</span><strong>{number.format(data.classificationQuality.supersededAssignmentCount)}</strong><small>삭제하지 않은 이력</small></article>
        <article><span>Primary 누락</span><strong>{number.format(data.classificationQuality.schemes.reduce((sum, item) => sum + item.primaryMissingCount, 0))}</strong><small>scheme별 분모 합계</small></article>
        <article><span>Primary 충돌</span><strong>{number.format(data.classificationQuality.schemes.reduce((sum, item) => sum + item.primaryConflictCount, 0))}</strong><small>동일 target 복수 primary</small></article>
      </section>
      <section className="operations-notice"><strong>검토 상태 해석</strong><p><b>APPROVED는 자동 승인 포함</b> 상태입니다. review status, evidence status, confidence를 각각 보며 confidence 1.0을 사람 검토 확률로 해석하지 않습니다.</p></section>
      <section className="quality-layout">
        <div className="scheme-quality-list">
          <header><div><p className="eyebrow">CLASSIFICATION COVERAGE</p><h3>Scheme별 분류 품질</h3></div><span>effective serving target</span></header>
          {data.classificationQuality.schemes.map((item) => {
            const coverage = item.eligibleTargetCount ? Math.round(item.assignedTargetCount / item.eligibleTargetCount * 100) : 0;
            return <article key={item.schemeCode} className="scheme-quality-card">
              <div><strong>{item.schemeName}</strong><small>{item.schemeCode} · {item.cardinality} · v{item.vocabularyVersion}</small></div>
              <div className="coverage-meter"><span style={{ width: `${Math.min(coverage, 100)}%` }}/></div>
              <strong className="coverage-ratio">{number.format(item.assignedTargetCount)} / {number.format(item.eligibleTargetCount)}</strong>
              <dl><div><dt>승인 target</dt><dd>{number.format(item.approvedTargetCount)}</dd></div><div><dt>미검토·대기</dt><dd>{number.format(item.pendingTargetCount)}</dd></div><div><dt>Primary 누락</dt><dd>{number.format(item.primaryMissingCount)}</dd></div><div><dt>충돌</dt><dd>{number.format(item.primaryConflictCount)}</dd></div></dl>
            </article>;
          })}
        </div>
        <aside className="quality-axes">
          <section><p className="eyebrow">REVIEW STATUS</p><h3>검토 상태</h3>{data.classificationQuality.reviewStatusCounts.map((item) => <div key={item.status}><span>{item.status}</span><strong>{number.format(item.count)}</strong></div>)}</section>
          <section><p className="eyebrow">EVIDENCE STATUS</p><h3>근거 상태</h3>{data.classificationQuality.evidenceStatusCounts.map((item) => <div key={item.status}><span>{item.status}</span><strong>{number.format(item.count)}</strong></div>)}</section>
        </aside>
      </section>
    </>}
    {view === "TIMELINE" && <OperationsTimelinePanel/>}
    {view === "KEYWORDS" && <KeywordAnalyticsPanel/>}
    {view === "INSIGHTS" && <InsightSignalsPanel onOpenDocument={onOpenDocument}/>}
    {view === "MODEL" && <ModelInterpretationsPanel onOpenDocument={onOpenDocument}/>}
  </section>;
}
