"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  FileCheck2,
  XCircle,
} from "lucide-react";
import type {
  InstitutionalAssessmentStepStatus,
  InstitutionalAssessmentVerdict,
  InstitutionalCapitalResponse,
  InstitutionalSelectionAssessment,
} from "@/lib/intelligence-contract";

const statusLabels: Record<string, string> = {
  PLANNED: "계획",
  OPEN: "모집 중",
  SCREENING: "심사 중",
  SHORTLISTED: "shortlist",
  SELECTED: "선정 완료",
  COMMITTED: "약정",
  CANCELLED: "취소",
  CLOSED: "종료",
  UNKNOWN: "후속 확인 중",
};

const evidenceLabels: Record<string, string> = {
  MANUAL_VERIFIED: "검토 승인",
  SOURCE_CLAIM: "원문 claim",
  UNSOURCED: "근거 미연결",
};

const stepStatusLabels: Record<InstitutionalAssessmentStepStatus, string> = {
  CONFIRMED: "확인",
  SUPPORTED: "부분 확인",
  MISSING: "미확인",
  CONFLICT: "충돌",
};

function amountText(value: unknown, currency: unknown) {
  if (!value) return "금액 미공개";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return `${String(value)} ${String(currency ?? "")}`;
  if (currency !== "KRW") return `${amount.toLocaleString("ko-KR")} ${String(currency ?? "")}`;
  if (amount >= 1e12) return `${(amount / 1e12).toFixed(1)}조원`;
  return `${Math.round(amount / 1e8).toLocaleString("ko-KR")}억원`;
}

function capitalNarrative(item: InstitutionalCapitalResponse["items"][number]): string {
  const signals = [
    `공식 선정 ${item.officialSelectionCount}건`,
    `집행 기반 유추 ${item.inferredSelectionCount}건`,
    `입찰 참여 ${item.bidParticipationCount}건`,
    `검토 필요 ${item.reviewRequiredCount}건`,
  ].join(" · ");
  return `${item.lpName}의 ${item.scope} 범위 ${item.mandateName}은 ${statusLabels[item.status] ?? item.status} 단계입니다. ${signals}이며, 실제 집행 연결은 ${item.deploymentCount}건입니다.`;
}

function StepIcon({ status }: { status: InstitutionalAssessmentStepStatus }) {
  if (status === "CONFIRMED") return <CheckCircle2 aria-hidden="true" />;
  if (status === "SUPPORTED") return <AlertTriangle aria-hidden="true" />;
  if (status === "CONFLICT") return <XCircle aria-hidden="true" />;
  return <CircleDashed aria-hidden="true" />;
}

function AssessmentBadge({ verdict, label }: { verdict: InstitutionalAssessmentVerdict; label: string }) {
  return <span className={`assessment-badge verdict-${verdict.toLowerCase().replaceAll("_", "-")}`}>{label}</span>;
}

function evidenceAnchorId(assessmentId: string, documentId: string) {
  return `assessment-evidence-${assessmentId}-${documentId}`.replaceAll(/[^a-zA-Z0-9_-]/g, "-");
}

function SelectionAssessmentCard({ assessment }: { assessment: InstitutionalSelectionAssessment }) {
  const evidenceById = new Map<string, InstitutionalSelectionAssessment["evidence"][number]>();
  assessment.evidence.forEach((document) => {
    if (!evidenceById.has(document.documentId)) evidenceById.set(document.documentId, document);
  });
  const supportedStepCount = assessment.steps.filter((item) => ["CONFIRMED", "SUPPORTED"].includes(item.status)).length;

  return <details className={`mandate-assessment verdict-${assessment.verdict.toLowerCase().replaceAll("_", "-")}`}>
    <summary>
      <AssessmentBadge verdict={assessment.verdict} label={assessment.verdictLabel} />
      <div className="assessment-title">
        <strong>{assessment.managerName}</strong>
        <span>{assessment.trackName ?? "track 확인 필요"}</span>
      </div>
      <p>{assessment.rationale}</p>
      <ChevronDown aria-hidden="true" className="assessment-route-icon" />
    </summary>
    <div className="assessment-body">
      <header className="assessment-meta">
        <div><span>후속 행위</span><strong>{assessment.actionLabel}</strong></div>
        {assessment.reportedAllocation && <div><span>보도 금액</span><strong>{amountText(assessment.reportedAllocation, assessment.allocationCurrency)}</strong></div>}
        {assessment.verdict !== "OFFICIAL_SELECTION" && <div><span>판단 근거</span><strong>충족 {supportedStepCount}/{assessment.steps.length}</strong></div>}
      </header>
      <ol className="decision-chain" aria-label={`${assessment.managerName} 선정 판단 과정`}>
        {assessment.steps.map((item) => {
          const supportingDocuments = item.evidenceDocumentIds
            .map((documentId) => evidenceById.get(documentId))
            .filter((document): document is InstitutionalSelectionAssessment["evidence"][number] => Boolean(document));
          return <li className={`step-${item.status.toLowerCase()}`} key={item.code}>
            <span className="decision-step-icon"><StepIcon status={item.status} /></span>
            <div>
              <header><strong>{item.label}</strong><span>{stepStatusLabels[item.status]}</span></header>
              <p>{item.detail}</p>
              {supportingDocuments.length > 0 && <div className="step-evidence-links" aria-label={`${item.label} 근거 문서`}>
                {supportingDocuments.map((document) => <a href={`#${evidenceAnchorId(assessment.assessmentId, document.documentId)}`} key={document.documentId} title={document.title}>{document.roleLabel}</a>)}
              </div>}
            </div>
          </li>;
        })}
      </ol>
      {assessment.evidence.length > 0 && <section className="assessment-evidence">
        <h5><FileCheck2 aria-hidden="true" /> 단계별 근거</h5>
        {assessment.evidence.map((document) => <article id={evidenceById.get(document.documentId) === document ? evidenceAnchorId(assessment.assessmentId, document.documentId) : undefined} key={`${document.documentId}:${document.role}`}>
          <div><span>{document.roleLabel}</span><strong>{document.title}</strong><small>{[document.publisher, document.publishedAt?.slice(0, 10)].filter(Boolean).join(" · ")}</small></div>
          {document.href && <a href={document.href} target="_blank" rel="noreferrer">원문</a>}
        </article>)}
      </section>}
      {assessment.missingChecks.length > 0 && <p className="assessment-missing"><strong>다음 확인</strong> {assessment.missingChecks.join(" · ")}</p>}
    </div>
  </details>;
}

export function InstitutionalCapitalWorkspace({ initialMandateId = null }: { initialMandateId?: string | null }) {
  const [data, setData] = useState<InstitutionalCapitalResponse | null>(null);
  const [error, setError] = useState(false);
  const initialTargetRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/institutional-capital", { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<InstitutionalCapitalResponse>; })
      .then(setData).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!data || !initialMandateId || !initialTargetRef.current) return;
    initialTargetRef.current.scrollIntoView?.({ block: "start", behavior: "smooth" });
    initialTargetRef.current.focus({ preventScroll: true });
  }, [data, initialMandateId]);

  return <section className="domain-workspace capital-workspace">
    <header className="workspace-hero"><div><p className="eyebrow">INSTITUTIONAL CAPITAL</p><h2>기관자금 Mandate 추적</h2><p>공고부터 선정·입찰·실제 집행까지, 운용사 판단의 근거와 빈칸을 한 흐름으로 확인합니다.</p></div></header>
    <section className="coverage-strip capital-coverage" aria-label="기관자금 근거 현황">
      <div><span>Mandate</span><strong>{data?.coverage.mandates ?? "-"}</strong></div>
      <div><span>공식 선정</span><strong>{data?.coverage.officialSelections ?? "-"}</strong></div>
      <div><span>집행 기반 유추</span><strong>{data?.coverage.inferredSelections ?? "-"}</strong></div>
      <div><span>입찰 참여</span><strong>{data?.coverage.bidParticipations ?? "-"}</strong></div>
      <div><span>검토 필요</span><strong>{data?.coverage.reviewRequired ?? "-"}</strong></div>
      <div><span>확인된 집행</span><strong>{data?.coverage.deployments ?? "-"}</strong></div>
    </section>
    <div className="evidence-banner capital-rule-banner">
      <strong>판정 원칙</strong>
      <p><b>공식 선정</b>은 기관 결과 원문으로 확정합니다. 동일 LP·track의 자금, vehicle·deal, 집행 운용사가 후속 문서에서 함께 확인될 때만 <b>선정 유추</b>로 올립니다. <b>입찰 참여만으로는 선정이 아닙니다.</b></p>
    </div>
    {!data && !error && <div className="state-block"><span className="spinner"/><strong>기관자금 근거 조립 중</strong></div>}
    {error && <div className="state-block error-state"><strong>기관자금 조회 오류</strong></div>}
    <div className="domain-card-list mandate-list">{data?.items.map((item) => {
      const leadingAssessment = item.assessments[0];
      const isInitialTarget = item.mandateId === initialMandateId;
      return <details className={`domain-card mandate-card${isInitialTarget ? " search-target-record" : ""}`} key={item.mandateId} open={isInitialTarget} ref={isInitialTarget ? initialTargetRef : undefined} tabIndex={isInitialTarget ? -1 : undefined}>
      <summary>
        <div className="mandate-summary-copy">
          <span className="status-pill">{statusLabels[item.status] ?? item.status}</span><h3>{item.mandateName}</h3><p>{item.lpName} · {item.scope} · {item.announcedAt?.slice(0,10) ?? "발표일 미상"}</p>
          {leadingAssessment && <div className="mandate-leading-signal"><AssessmentBadge verdict={leadingAssessment.verdict} label={leadingAssessment.verdictLabel} /><strong>{leadingAssessment.managerName}</strong><span>{leadingAssessment.rationale}</span></div>}
        </div>
        <div className="card-counts mandate-counts">
          <span>공식 <b>{item.officialSelectionCount}</b></span>
          <span>유추 <b>{item.inferredSelectionCount}</b></span>
          <span>입찰 <b>{item.bidParticipationCount}</b></span>
          <span>검토 <b>{item.reviewRequiredCount}</b></span>
        </div>
        <ChevronDown aria-hidden="true" className="mandate-toggle-icon" />
      </summary>
      <div className="domain-card-body mandate-card-body">
        <section className="domain-narrative mandate-narrative"><p className="eyebrow">EVIDENCE SUMMARY</p><h4>현재 판단</h4><p>{capitalNarrative(item)}</p></section>
        <section className="mandate-assessment-section">
          <header><div><p className="eyebrow">SELECTION ASSESSMENT</p><h4>선정 판단과 근거 경로</h4></div><span>{item.assessments.length}개 운용사 signal</span></header>
          {item.assessments.length
            ? <div className="mandate-assessment-list">{item.assessments.map((assessment) => <SelectionAssessmentCard assessment={assessment} key={assessment.assessmentId} />)}</div>
            : <div className="mandate-assessment-empty"><strong>후속 운용사 근거 미연결</strong><p>공식 선정 결과 또는 동일 LP·track의 입찰·vehicle·deal 집행 문서가 연결되면 판단 경로가 생성됩니다.</p></div>}
        </section>
        <details className="mandate-raw-details">
          <summary><span>구조화 원자료 보기</span><small>track {item.trackCount} · 금액 {item.amountCount} · 문서 {item.documents.length}</small><ChevronDown aria-hidden="true" /></summary>
          <div className="mandate-raw-grid">
            <section><h4>전략 Track·가이드라인</h4>{item.tracks.length ? item.tracks.map((track, index) => <article key={String(track.trackId ?? index)}><strong>{String(track.name ?? track.code ?? "Track")}</strong><p>{[track.strategy,track.geography,evidenceLabels[String(track.evidenceStatus)] ?? track.evidenceStatus].filter(Boolean).map(String).join(" · ")}</p>{Array.isArray(track.guidelines) && track.guidelines.length > 0 && <ul>{track.guidelines.map((guide, guideIndex) => <li key={guideIndex}>{String((guide as Record<string,unknown>).termType ?? "조건")}: {String((guide as Record<string,unknown>).rawText ?? "-")}</li>)}</ul>}</article>) : <p className="empty-copy">구조화된 track이 없습니다.</p>}</section>
            <section><h4>금액 Basis</h4>{item.amounts.length ? <div className="fact-table">{item.amounts.map((amount, index) => <div key={String(amount.amountId ?? index)}><span>{String(amount.basis ?? "OTHER")}</span><strong>{amountText(amount.amount, amount.currency)}</strong><small>{[amount.status,amount.comparator,evidenceLabels[String(amount.evidenceStatus)] ?? amount.evidenceStatus].filter(Boolean).map(String).join(" · ")}</small></div>)}</div> : <p className="empty-copy">공개 금액 근거가 없습니다.</p>}</section>
            <section><h4>구조화된 공식 선정</h4>{item.selections.length ? item.selections.map((selection, index) => <article key={String(selection.selectionId ?? index)}><strong>{String(selection.managerName ?? "운용사")}</strong><p>{[selection.trackName,selection.status,selection.selectedAt,evidenceLabels[String(selection.evidenceStatus)] ?? selection.evidenceStatus].filter(Boolean).map(String).join(" · ")}</p></article>) : <p className="empty-copy">공식 선정 결과가 연결되지 않았습니다.</p>}</section>
            <section><h4>공고·프로그램 문서</h4>{item.documents.length ? item.documents.map((document) => <article key={document.documentId}><strong>{document.title}</strong><p>{[document.documentType,document.publisher,document.publishedAt?.slice(0,10)].filter(Boolean).join(" · ")}</p>{document.href && <a href={document.href} target="_blank" rel="noreferrer">원문 열기</a>}</article>) : <p className="empty-copy">mandate에 직접 연결된 문서가 없습니다.</p>}</section>
          </div>
        </details>
        <footer className="evidence-footer">근거 {evidenceLabels[item.evidenceStatus] ?? item.evidenceStatus} · 확인된 deployment {item.deploymentCount}건</footer>
      </div>
    </details>})}</div>
  </section>;
}
