"use client";

import { useEffect, useState } from "react";
import type { InstitutionalCapitalResponse } from "@/lib/intelligence-contract";

function amountText(value: unknown, currency: unknown) {
  if (!value) return "금액 미공개";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return `${String(value)} ${String(currency ?? "")}`;
  if (amount >= 1e12) return `${(amount / 1e12).toFixed(1)}조원`;
  return `${Math.round(amount / 1e8).toLocaleString("ko-KR")}억원`;
}

function capitalNarrative(item: InstitutionalCapitalResponse["items"][number]): string {
  return `${item.lpName}의 ${item.scope} 범위 ${item.mandateName}은 현재 ${item.status} 단계입니다. 전략 track ${item.trackCount}건, 공식 선정 ${item.selectionCount}건, 금액 근거 ${item.amountCount}건, 집행 연결 ${item.deploymentCount}건이 확인됩니다. 근거 수준은 ${item.evidenceStatus}입니다.`;
}

export function InstitutionalCapitalWorkspace() {
  const [data, setData] = useState<InstitutionalCapitalResponse | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/institutional-capital", { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<InstitutionalCapitalResponse>; })
      .then(setData).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); });
    return () => controller.abort();
  }, []);
  return <section className="domain-workspace capital-workspace">
    <header className="workspace-hero"><div><p className="eyebrow">INSTITUTIONAL CAPITAL</p><h2>기관자금 Mandate 추적</h2><p>LP → 프로그램 → 전략 track → 선정 운용사 → vehicle·deal deployment의 공개 근거를 단계별로 구분합니다.</p></div></header>
    <section className="coverage-strip">
      <div><span>Mandate</span><strong>{data?.coverage.mandates ?? "-"}</strong></div>
      <div><span>공식 선정</span><strong>{data?.coverage.selections ?? "-"}</strong></div>
      <div><span>금액 근거</span><strong>{data?.coverage.amounts ?? "-"}</strong></div>
      <div><span>집행 연결</span><strong>{data?.coverage.deployments ?? "-"}</strong></div>
    </section>
    <div className="evidence-banner warning"><strong>잔액 해석</strong><p>프로그램 총액·신청금액·선정한도·약정액을 합산하지 않습니다. 집행 연결이 없으면 dry powder를 0으로 표시하지 않고 ‘공개근거 부족’으로 남깁니다.</p></div>
    {!data && !error && <div className="state-block"><span className="spinner"/><strong>기관자금 근거 조립 중</strong></div>}
    {error && <div className="state-block error-state"><strong>기관자금 조회 오류</strong></div>}
    <div className="domain-card-list">{data?.items.map((item) => <details className="domain-card" key={item.mandateId}><summary><div><span className="status-pill">{item.status}</span><h3>{item.mandateName}</h3><p>{item.lpName} · {item.scope} · {item.announcedAt?.slice(0,10) ?? "발표일 미상"}</p></div><div className="card-counts"><span>track <b>{item.trackCount}</b></span><span>선정 <b>{item.selectionCount}</b></span><span>금액 <b>{item.amountCount}</b></span><span>문서 <b>{item.documents.length}</b></span></div></summary><div className="domain-card-body">
      <section className="domain-narrative"><p className="eyebrow">STRUCTURED SUMMARY</p><h4>기관자금 핵심 설명</h4><p>{capitalNarrative(item)}</p></section>
      <section><h4>전략 Track·가이드라인</h4>{item.tracks.length ? item.tracks.map((track, index) => <article key={String(track.trackId ?? index)}><strong>{String(track.name ?? track.code ?? "Track")}</strong><p>{[track.strategy,track.geography,track.evidenceStatus].filter(Boolean).map(String).join(" · ")}</p>{Array.isArray(track.guidelines) && track.guidelines.length > 0 && <ul>{track.guidelines.map((guide, guideIndex) => <li key={guideIndex}>{String((guide as Record<string,unknown>).termType ?? "조건")}: {String((guide as Record<string,unknown>).rawText ?? "-")}</li>)}</ul>}</article>) : <p className="empty-copy">구조화된 track이 없습니다.</p>}</section>
      <section><h4>금액 Basis</h4>{item.amounts.length ? <div className="fact-table">{item.amounts.map((amount, index) => <div key={String(amount.amountId ?? index)}><span>{String(amount.basis ?? "OTHER")}</span><strong>{amountText(amount.amount, amount.currency)}</strong><small>{[amount.status,amount.comparator,amount.evidenceStatus].filter(Boolean).map(String).join(" · ")}</small></div>)}</div> : <p className="empty-copy">공개 금액 근거가 없습니다.</p>}</section>
      <section><h4>선정 운용사</h4>{item.selections.length ? item.selections.map((selection, index) => <article key={String(selection.selectionId ?? index)}><strong>{String(selection.managerName ?? "운용사")}</strong><p>{[selection.status,selection.selectedAt,selection.evidenceStatus].filter(Boolean).map(String).join(" · ")}</p></article>) : <p className="empty-copy">공식 선정 결과가 연결되지 않았습니다.</p>}</section>
      <section><h4>근거 문서</h4>{item.documents.length ? item.documents.map((document) => <article key={document.documentId}><strong>{document.title}</strong><p>{[document.documentType,document.publisher,document.publishedAt?.slice(0,10)].filter(Boolean).join(" · ")}</p>{document.href && <a href={document.href} target="_blank" rel="noreferrer">원문 열기</a>}</article>) : <p className="empty-copy">event에 직접 연결된 문서가 없습니다.</p>}</section>
      <footer className="evidence-footer">Evidence {item.evidenceStatus} · deployment {item.deploymentCount}건</footer>
    </div></details>)}</div>
  </section>;
}
