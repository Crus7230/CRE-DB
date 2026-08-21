"use client";

import { useEffect, useState } from "react";
import type { SaleProcessResponse } from "@/lib/intelligence-contract";

function amountText(value: unknown, currency: unknown) {
  if (!value) return "금액 미공개";
  const amount = Number(value);
  return Number.isFinite(amount) ? `${Math.round(amount / 1e8).toLocaleString("ko-KR")}억원` : `${String(value)} ${String(currency ?? "")}`;
}

function saleNarrative(item: SaleProcessResponse["items"][number]): string {
  return `${item.title}은 ${item.saleMethod} 방식의 매각절차로 현재 ${item.status} 단계입니다. 대상 자산 ${item.assets.length}건, 입찰 round ${item.rounds.length}건, milestone ${item.milestones.length}건, 자금조달 근거 ${item.funding.length}건, 문서 ${item.documents.length}건이 연결되어 있습니다. 근거 수준은 ${item.evidenceStatus}입니다.`;
}

export function SaleProcessWorkspace() {
  const [data, setData] = useState<SaleProcessResponse | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/sale-processes", { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<SaleProcessResponse>; })
      .then(setData).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); });
    return () => controller.abort();
  }, []);
  return <section className="domain-workspace sale-workspace">
    <header className="workspace-hero"><div><p className="eyebrow">SALE PROCESS</p><h2>매각절차 Chronology</h2><p>기사 한 건이 아니라 매각 착수부터 입찰·우협·SPA·종결·무산까지 process 단위로 재구성합니다.</p></div></header>
    <section className="coverage-strip sale-coverage">
      <div><span>Process</span><strong>{data?.coverage.processes ?? "-"}</strong></div><div><span>Round</span><strong>{data?.coverage.rounds ?? "-"}</strong></div><div><span>참여자</span><strong>{data?.coverage.bidders ?? "-"}</strong></div><div><span>가격제출</span><strong>{data?.coverage.submissions ?? "-"}</strong></div><div><span>결정</span><strong>{data?.coverage.decisions ?? "-"}</strong></div><div><span>Funding</span><strong>{data?.coverage.fundingComponents ?? "-"}</strong></div>
    </section>
    {!data && !error && <div className="state-block"><span className="spinner"/><strong>매각 chronology 조립 중</strong></div>}
    {error && <div className="state-block error-state"><strong>매각절차 조회 오류</strong></div>}
    <div className="domain-card-list">{data?.items.map((item) => <details className="domain-card" key={item.saleProcessId}><summary><div><span className="status-pill">{item.status}</span><h3>{item.title}</h3><p>{item.processCode} · {item.saleMethod} · {item.launchedAt?.slice(0,10) ?? "착수일 미상"}</p></div><div className="card-counts"><span>자산 <b>{item.assets.length}</b></span><span>round <b>{item.rounds.length}</b></span><span>milestone <b>{item.milestones.length}</b></span><span>문서 <b>{item.documents.length}</b></span></div></summary><div className="domain-card-body">
      <section className="domain-narrative"><p className="eyebrow">STRUCTURED SUMMARY</p><h4>매각절차 핵심 설명</h4><p>{saleNarrative(item)}</p></section>
      <section><h4>대상 자산</h4>{item.assets.length ? item.assets.map((asset,index) => <article key={String(asset.assetId ?? index)}><strong>{String(asset.name ?? "자산")}</strong><p>{String(asset.address ?? "주소 미상")}</p></article>) : <p className="empty-copy">연결된 canonical asset이 없습니다.</p>}</section>
      <section><h4>입찰 Round</h4>{item.rounds.length ? item.rounds.map((round,index) => <article className="round-card" key={String(round.roundId ?? index)}><header><strong>{String(round.roundCode ?? `Round ${index+1}`)}</strong><span>{String(round.status ?? "-")}</span></header><p>{[round.roundType,round.deadlineAt,round.evidenceStatus].filter(Boolean).map(String).join(" · ")}</p>{Array.isArray(round.bidders) && round.bidders.length > 0 && <div className="chip-row">{round.bidders.map((bidder,bidderIndex) => <span key={bidderIndex}>{String((bidder as Record<string,unknown>).name ?? "비공개")} · {String((bidder as Record<string,unknown>).status ?? "")}</span>)}</div>}{Array.isArray(round.submissions) && round.submissions.map((submission,submissionIndex) => { const row=submission as Record<string,unknown>; return <div className="price-row" key={submissionIndex}><span>{String(row.priceBasis ?? "입찰가")}</span><strong>{amountText(row.amount,row.currency)}</strong><small>rank {String(row.rank ?? "비공개")}</small></div>; })}</article>) : <p className="empty-copy">구조화된 입찰 round가 없습니다.</p>}</section>
      <section><h4>Milestone</h4>{item.milestones.length ? <ol className="timeline">{item.milestones.map((milestone,index) => <li key={index}><time>{String(milestone.effectiveDate ?? milestone.announcedAt ?? milestone.expectedDate ?? "날짜 미상").slice(0,10)}</time><div><strong>{String(milestone.code ?? "MILESTONE")}</strong><p>{[milestone.status,milestone.note,milestone.evidenceStatus].filter(Boolean).map(String).join(" · ")}</p></div></li>)}</ol> : <p className="empty-copy">milestone 근거가 없습니다.</p>}</section>
      <section><h4>자금조달</h4>{item.funding.length ? <div className="fact-table">{item.funding.map((fund,index) => <div key={index}><span>{String(fund.type ?? "FUNDING")}</span><strong>{amountText(fund.amount,fund.currency)}</strong><small>{[fund.provider,fund.status,fund.evidenceStatus].filter(Boolean).map(String).join(" · ")}</small></div>)}</div> : <p className="empty-copy">공개된 funding component가 없습니다.</p>}</section>
      <section><h4>근거 문서</h4>{item.documents.length ? item.documents.map((document) => <article key={document.documentId}><strong>{document.title}</strong><p>{[document.documentType,document.publisher,document.publishedAt?.slice(0,10)].filter(Boolean).join(" · ")}</p>{document.href && <a href={document.href} target="_blank" rel="noreferrer">원문 열기</a>}</article>) : <p className="empty-copy">process event에 연결된 문서가 없습니다.</p>}</section>
      <footer className="evidence-footer">Evidence {item.evidenceStatus} · 종료일 {item.closedAt?.slice(0,10) ?? "미확정"}</footer>
    </div></details>)}</div>
  </section>;
}
