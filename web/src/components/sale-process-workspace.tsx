"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BadgeCheck, ChevronDown, ExternalLink, FileSearch2, Search, ShieldCheck } from "lucide-react";
import type { SaleProcessResearchCandidate, SaleProcessResponse } from "@/lib/intelligence-contract";

type CandidateMode = "ALL" | "ACTIVE" | "CLOSED";

const assetTypeLabels: Record<string, string> = {
  OFFICE: "오피스",
  OFFICE_IN_RETAIL_COMPLEX: "복합시설 오피스",
  HOTEL: "호텔",
  LOGISTICS: "물류",
  RETAIL: "리테일",
  DATA_CENTER_PROJECT_COMPANY_STAKE: "데이터센터 지분",
};

const statusLabels: Record<string, string> = {
  CLOSED: "종결",
  CLOSED_MEDIA_FOLLOWUP: "종결 보도·검증 중",
  PREFERRED_BIDDER: "우협 선정",
  PREFERRED_BIDDER_MEDIA_ONLY: "우협 보도·검증 중",
  PREFERRED_NEGOTIATION_FINANCING_DELAY: "우협·자금조달 지연",
  PREFERRED_SPA_NOT_PROVED: "우협·SPA 미확인",
};

const roleLabels: Record<string, string> = {
  legal_owner_or_vehicle: "소유자·매도 vehicle",
  amc_or_manager: "기존 운용사",
  headline_seller: "매도자",
  headline_seller_or_manager: "매도자·운용사",
  headline_seller_or_sponsor: "매도자·스폰서",
  seller_vehicle_or_manager: "매도 vehicle·운용사",
  sell_side_adviser: "매각 자문사",
  sell_side_advisers: "매각 자문사",
  preferred_bidder: "우선협상대상자",
  preferred_buyers: "우선협상대상자",
  buyer_or_preferred: "매수자·우선협상자",
  buyer: "매수자",
  buyer_vehicle: "매수 vehicle",
  buyer_amc: "매수 운용사",
  initial_preferred: "최초 우선협상자",
  preempting_buyer: "우선매수권 행사자",
  reserve_bidder: "차순위",
  economic_sponsor: "주요 출자자",
  continuing_operator: "운영사",
};

function amountText(value: unknown, currency: unknown = "KRW") {
  if (!value) return "금액 미공개";
  const amount = Number(value);
  return Number.isFinite(amount) ? `${Math.round(amount / 1e8).toLocaleString("ko-KR")}억원` : `${String(value)} ${String(currency ?? "")}`;
}

function candidateAmount(item: SaleProcessResearchCandidate) {
  const amount = item.amounts[0];
  if (!amount) return "금액 미공개";
  if (amount.value_krw) return amountText(amount.value_krw);
  return String(amount.raw ?? "금액 미공개");
}

function latestCandidateDate(item: SaleProcessResearchCandidate) {
  return item.sources.map((source) => source.date ?? "").sort().at(-1) || "날짜 미상";
}

function statusLabel(status: string) {
  return statusLabels[status] ?? status.replaceAll("_", " ");
}

function roleValue(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join(" · ");
  return value == null || value === "" ? "미확인" : String(value);
}

function saleNarrative(item: SaleProcessResponse["items"][number]): string {
  return `${item.title}은 ${item.saleMethod} 방식의 매각절차로 현재 ${item.status} 단계입니다. 대상 자산 ${item.assets.length}건, 입찰 round ${item.rounds.length}건, milestone ${item.milestones.length}건, 자금조달 근거 ${item.funding.length}건, 문서 ${item.documents.length}건이 연결되어 있습니다. 근거 수준은 ${item.evidenceStatus}입니다.`;
}

function ResearchCandidateCard({ item }: { item: SaleProcessResearchCandidate }) {
  const roles = Object.entries(item.roles).filter(([, value]) => value != null && value !== "");
  return <details className="sale-candidate-card">
    <summary>
      <time>{latestCandidateDate(item)}</time>
      <div className="sale-candidate-summary">
        <div className="sale-candidate-badges">
          <span className="candidate-status">{statusLabel(item.status)}</span>
          <span>{assetTypeLabels[item.assetType] ?? item.assetType}</span>
          <span>근거 {item.evidenceGrade}</span>
        </div>
        <h4>{item.title}</h4>
        <p>{item.processCode} · 출처 {item.sources.length}건</p>
      </div>
      <strong className="candidate-amount">{candidateAmount(item)}</strong>
      <ChevronDown aria-hidden="true" />
    </summary>
    <div className="sale-candidate-body">
      <p className="candidate-review-note"><FileSearch2 aria-hidden="true" /><span><b>조사·검토 후보</b>입니다. 기사·공시 근거는 묶였지만 자산 중복 확인과 승인 전이므로 정식 매각절차 수에는 합산하지 않습니다.</span></p>
      <section>
        <h5>확인된 흐름</h5>
        {item.milestones.length > 0 ? <ol className="candidate-milestones">
          {item.milestones.map((milestone, index) => <li key={index}>
            <time>{String(milestone.date ?? "날짜 미상")}</time>
            <strong>{statusLabel(String(milestone.type ?? "MILESTONE"))}</strong>
            {milestone.party ? <span>{String(milestone.party)}</span> : null}
          </li>)}
        </ol> : <p className="empty-copy">단계별 milestone은 추가 확인 중입니다.</p>}
      </section>
      <section>
        <h5>입찰·참여 정보</h5>
        {item.rounds.length > 0 ? <div className="candidate-rounds">
          {item.rounds.map((round, index) => <article key={index}>
            <header><strong>{statusLabel(String(round.round_type ?? `ROUND ${index + 1}`))}</strong><time>{String(round.date ?? "날짜 미상")}</time></header>
            <p>{[
              Array.isArray(round.bidders) ? round.bidders.map(String).join(" · ") : null,
              Array.isArray(round.bidders_partial) ? round.bidders_partial.map(String).join(" · ") : null,
              round.bidder_count ? `참여 ${String(round.bidder_count)}곳` : null,
              round.bidder_count_claim ? `참여 ${String(round.bidder_count_claim)}` : null,
              round.count_claim_note,
            ].filter(Boolean).map(String).join(" / ") || "참여자 세부 정보 미공개"}</p>
          </article>)}
        </div> : <p className="empty-copy">공개된 입찰 round 세부 정보가 없습니다.</p>}
      </section>
      <section>
        <h5>주요 관계자</h5>
        <dl className="candidate-roles">
          {roles.map(([key, value]) => <div key={key}><dt>{roleLabels[key] ?? key.replaceAll("_", " ")}</dt><dd>{roleValue(value)}</dd></div>)}
        </dl>
      </section>
      <section className="candidate-sources">
        <h5>판단 근거</h5>
        {item.sources.map((source, index) => <article key={`${source.url}-${index}`}>
          <BadgeCheck aria-hidden="true" />
          <div><strong>{source.span || "매각절차 관련 근거"}</strong><p>{source.date ?? "날짜 미상"}</p></div>
          <a href={source.url} target="_blank" rel="noreferrer">원문 <ExternalLink aria-hidden="true" /></a>
        </article>)}
      </section>
    </div>
  </details>;
}

export function SaleProcessWorkspace({ initialSaleProcessId = null }: { initialSaleProcessId?: string | null }) {
  const [data, setData] = useState<SaleProcessResponse | null>(null);
  const [error, setError] = useState(false);
  const [candidateMode, setCandidateMode] = useState<CandidateMode>("ALL");
  const [assetType, setAssetType] = useState("ALL");
  const [query, setQuery] = useState("");
  const initialTargetRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/sale-processes", { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<SaleProcessResponse>; })
      .then(setData).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!data || !initialSaleProcessId || !initialTargetRef.current) return;
    initialTargetRef.current.scrollIntoView?.({ block: "start", behavior: "smooth" });
    initialTargetRef.current.focus({ preventScroll: true });
  }, [data, initialSaleProcessId]);

  const assetTypes = useMemo(() => Array.from(new Set(data?.candidateProcesses.map((item) => item.assetType) ?? [])).sort(), [data]);
  const candidates = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("ko-KR");
    return (data?.candidateProcesses ?? [])
      .filter((item) => candidateMode === "ALL" || (candidateMode === "CLOSED" ? item.status.startsWith("CLOSED") : !item.status.startsWith("CLOSED")))
      .filter((item) => assetType === "ALL" || item.assetType === assetType)
      .filter((item) => !normalizedQuery || `${item.title} ${item.processCode} ${Object.values(item.roles).flat().join(" ")}`.toLocaleLowerCase("ko-KR").includes(normalizedQuery))
      .sort((a, b) => latestCandidateDate(b).localeCompare(latestCandidateDate(a)));
  }, [assetType, candidateMode, data, query]);

  return <section className="domain-workspace sale-workspace">
    <header className="workspace-hero"><div><p className="eyebrow">SALE PROCESS</p><h2>매각 파이프라인</h2><p>올해 조사 후보와 검증 완료된 매각절차를 구분하고, 입찰부터 우협·종결까지 근거를 따라갑니다.</p></div></header>
    <section className="coverage-strip sale-coverage" aria-label="매각 데이터 현황">
      <div className="coverage-emphasis"><span>{data?.coverage.signalYear ?? new Date().getFullYear()} 고유 후보</span><strong>{data?.coverage.currentYearCandidateProcesses ?? "-"}</strong></div>
      <div><span>올해 정식 절차</span><strong>{data?.coverage.currentYearProcesses ?? "-"}</strong></div>
      <div><span>검토 기사 신호</span><strong>{data?.coverage.currentYearArticleSignals ?? "-"}</strong></div>
      <div><span>우선 검토 신호</span><strong>{data?.coverage.currentYearPriorityArticleSignals ?? "-"}</strong></div>
      <div><span>전체 정식 절차</span><strong>{data?.coverage.processes ?? "-"}</strong></div>
      <div><span>구조화 Round</span><strong>{data?.coverage.rounds ?? "-"}</strong></div>
    </section>
    {!data && !error && <div className="state-block"><span className="spinner"/><strong>올해 후보와 정식 절차를 조립 중</strong></div>}
    {error && <div className="state-block error-state"><strong>매각절차 조회 오류</strong></div>}
    {data && <>
      <section className="sale-current-panel" aria-labelledby="current-sale-heading">
        <header>
          <div className="sale-current-icon"><Search aria-hidden="true" /></div>
          <div><p className="eyebrow">{data.coverage.candidateCutoffDate.replaceAll("-", ".")} 조사 기준</p><h3 id="current-sale-heading">올해 매각·입찰 후보 <b>{data.coverage.currentYearCandidateProcesses}건</b></h3><p>고유 프로세스로 묶은 조사 레코드입니다. 기사 단위 신호 {data.coverage.currentYearArticleSignals}건은 중복·오탐 검토 큐로 별도 관리합니다.</p></div>
          <span className="candidate-boundary"><ShieldCheck aria-hidden="true" />정본과 분리</span>
        </header>
        <div className="sale-candidate-filters">
          <div className="candidate-mode-buttons" aria-label="후보 상태 필터">
            {([ ["ALL", "전체"], ["ACTIVE", "진행 중"], ["CLOSED", "종결"] ] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={candidateMode === value} onClick={() => setCandidateMode(value)}>{label}</button>)}
          </div>
          <label><span>자산 유형</span><select value={assetType} onChange={(event) => setAssetType(event.target.value)}><option value="ALL">전체 유형</option>{assetTypes.map((value) => <option key={value} value={value}>{assetTypeLabels[value] ?? value}</option>)}</select></label>
          <label className="candidate-search"><Search aria-hidden="true" /><span className="sr-only">후보 검색</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="자산·운용사·매수자 검색" /></label>
          <strong className="candidate-result-count">{candidates.length}건 표시</strong>
        </div>
        <div className="sale-candidate-list">
          {candidates.map((item) => <ResearchCandidateCard key={item.candidateId} item={item} />)}
          {candidates.length === 0 && <div className="candidate-empty"><FileSearch2 aria-hidden="true" /><strong>조건에 맞는 후보가 없습니다.</strong><p>필터나 검색어를 바꿔보세요.</p></div>}
        </div>
      </section>
      <section className="canonical-sale-section" aria-labelledby="canonical-sale-heading">
        <header><div><p className="eyebrow">VERIFIED CANONICAL</p><h3 id="canonical-sale-heading">검증 완료된 매각절차 <b>{data.coverage.processes}건</b></h3><p>승인·자산 연결을 마친 정식 데이터입니다. {data.coverage.signalYear}년 정식 절차는 현재 {data.coverage.currentYearProcesses}건입니다.</p></div></header>
        <div className="domain-card-list">{data.items.map((item) => { const isInitialTarget = item.saleProcessId === initialSaleProcessId; return <details className={`domain-card${isInitialTarget ? " search-target-record" : ""}`} key={item.saleProcessId} open={isInitialTarget} ref={isInitialTarget ? initialTargetRef : undefined} tabIndex={isInitialTarget ? -1 : undefined}><summary><div><span className="status-pill">{item.status}</span><h3>{item.title}</h3><p>{item.processCode} · {item.saleMethod} · {item.launchedAt?.slice(0,10) ?? "착수일 미상"}</p></div><div className="card-counts"><span>자산 <b>{item.assets.length}</b></span><span>round <b>{item.rounds.length}</b></span><span>milestone <b>{item.milestones.length}</b></span><span>문서 <b>{item.documents.length}</b></span></div></summary><div className="domain-card-body">
          <section className="domain-narrative"><p className="eyebrow">STRUCTURED SUMMARY</p><h4>매각절차 핵심 설명</h4><p>{saleNarrative(item)}</p></section>
          <section><h4>대상 자산</h4>{item.assets.length ? item.assets.map((asset,index) => <article key={String(asset.assetId ?? index)}><strong>{String(asset.name ?? "자산")}</strong><p>{String(asset.address ?? "주소 미상")}</p></article>) : <p className="empty-copy">연결된 canonical asset이 없습니다.</p>}</section>
          <section><h4>입찰 Round</h4>{item.rounds.length ? item.rounds.map((round,index) => <article className="round-card" key={String(round.roundId ?? index)}><header><strong>{String(round.roundCode ?? `Round ${index+1}`)}</strong><span>{String(round.status ?? "-")}</span></header><p>{[round.roundType,round.deadlineAt,round.evidenceStatus].filter(Boolean).map(String).join(" · ")}</p>{Array.isArray(round.bidders) && round.bidders.length > 0 && <div className="chip-row">{round.bidders.map((bidder,bidderIndex) => <span key={bidderIndex}>{String((bidder as Record<string,unknown>).name ?? "비공개")} · {String((bidder as Record<string,unknown>).status ?? "")}</span>)}</div>}{Array.isArray(round.submissions) && round.submissions.map((submission,submissionIndex) => { const row=submission as Record<string,unknown>; return <div className="price-row" key={submissionIndex}><span>{String(row.priceBasis ?? "입찰가")}</span><strong>{amountText(row.amount,row.currency)}</strong><small>rank {String(row.rank ?? "비공개")}</small></div>; })}</article>) : <p className="empty-copy">구조화된 입찰 round가 없습니다.</p>}</section>
          <section><h4>Milestone</h4>{item.milestones.length ? <ol className="timeline">{item.milestones.map((milestone,index) => <li key={index}><time>{String(milestone.effectiveDate ?? milestone.announcedAt ?? milestone.expectedDate ?? "날짜 미상").slice(0,10)}</time><div><strong>{String(milestone.code ?? "MILESTONE")}</strong><p>{[milestone.status,milestone.note,milestone.evidenceStatus].filter(Boolean).map(String).join(" · ")}</p></div></li>)}</ol> : <p className="empty-copy">milestone 근거가 없습니다.</p>}</section>
          <section><h4>자금조달</h4>{item.funding.length ? <div className="fact-table">{item.funding.map((fund,index) => <div key={index}><span>{String(fund.type ?? "FUNDING")}</span><strong>{amountText(fund.amount,fund.currency)}</strong><small>{[fund.provider,fund.status,fund.evidenceStatus].filter(Boolean).map(String).join(" · ")}</small></div>)}</div> : <p className="empty-copy">공개된 funding component가 없습니다.</p>}</section>
          <section><h4>근거 문서</h4>{item.documents.length ? item.documents.map((document) => <article key={document.documentId}><strong>{document.title}</strong><p>{[document.documentType,document.publisher,document.publishedAt?.slice(0,10)].filter(Boolean).join(" · ")}</p>{document.href && <a href={document.href} target="_blank" rel="noreferrer">원문 열기</a>}</article>) : <p className="empty-copy">process event에 연결된 문서가 없습니다.</p>}</section>
          <footer className="evidence-footer">Evidence {item.evidenceStatus} · 종료일 {item.closedAt?.slice(0,10) ?? "미확정"}</footer>
        </div></details>})}</div>
      </section>
    </>}
  </section>;
}
