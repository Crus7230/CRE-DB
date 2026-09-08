"use client";
import { useEffect, useState } from "react";
import { normalizeInsightSignals, type InsightSignal, type InsightSignalsResponse } from "@/lib/insight-signals-contract";

type Props = { onOpenDocument: (documentId: string, title: string) => void };
const score = (value: number) => `${Math.round(value * 100)}%`;
function SignalCard({ signal, onOpenDocument }: { signal: InsightSignal } & Props) {
  return <article className="insight-card">
    <header><div><span className={`signal-severity ${signal.severity.toLowerCase()}`}>{signal.severity}</span><time>{signal.signalDate}</time></div><span className={`signal-review ${signal.reviewStatus.toLowerCase()}`}>{signal.reviewStatus}</span></header>
    <h4>{signal.title}</h4><p>{signal.summary}</p>
    <dl className="signal-scores"><div><dt>강도</dt><dd>{score(signal.scores.strength)}</dd></div><div><dt>근거</dt><dd>{score(signal.scores.evidence)}</dd></div><div><dt>출처 다양성</dt><dd>{score(signal.scores.sourceDiversity)}</dd></div><div><dt>합성 점수</dt><dd>{score(signal.scores.confidence)}</dd></div></dl>
    <div className="signal-caveat">{signal.syndicationDedupeStatus === "PARTIAL" ? "부분 중복제거 · 기사 전재 가능성은 별도 검토" : `중복제거 ${signal.syndicationDedupeStatus}`}</div>
    <div className="signal-evidence-list">{signal.evidence.map((item) => <div key={`${item.targetKind}-${item.targetId}-${item.rank}`}>
      {item.documentId ? <button type="button" onClick={() => onOpenDocument(item.documentId!, item.title)}><strong>{item.title}</strong><span>{item.sourceName} · {item.publishedAt?.slice(0, 10) ?? "발행일 미상"}</span></button> : <div><strong>{item.title}</strong><span>{item.sourceName} · {item.targetKind}</span></div>}
      {item.canonicalUrl && <a href={item.canonicalUrl} target="_blank" rel="noreferrer">원문</a>}
    </div>)}</div>
  </article>;
}
export function InsightSignalsPanel({ onOpenDocument }: Props) {
  const [data, setData] = useState<InsightSignalsResponse | null>(null); const [error, setError] = useState(false); const [retry, setRetry] = useState(0);
  useEffect(() => { let active=true; fetch("/api/operations/insights?limit=20",{credentials:"same-origin"}).then(async r=>{if(!r.ok) throw new Error(); return normalizeInsightSignals(await r.json());}).then(v=>{if(active)setData(v);}).catch(()=>{if(active)setError(true);}); return()=>{active=false;}; },[retry]);
  if(error) return <div className="operations-state error" role="alert"><strong>인사이트 신호를 불러오지 못했습니다.</strong><button type="button" onClick={()=>{ setError(false); setRetry(v=>v+1); }}>다시 시도</button></div>;
  if(!data) return <div className="operations-state" role="status" aria-live="polite">근거 연결형 신호를 불러오는 중입니다.</div>;
  const approved=data.signals.filter(item=>item.reviewStatus==="APPROVED");
  const reviewNeeded=data.signals.filter(item=>item.reviewStatus==="UNREVIEWED"||item.reviewStatus==="PENDING");
  return <section className="insight-panel">
    <div className="operations-notice"><strong>신호 해석 기준</strong><span>규칙형 signal은 자동 승인되지 않습니다. 합성 점수와 원문 근거를 함께 검토합니다.</span></div>
    <div className="insight-columns">
      <section><header><div><p className="eyebrow">APPROVED</p><h3>검토 완료 신호</h3></div><b>{approved.length}</b></header>{approved.length ? approved.map(item=><SignalCard key={item.signalId} signal={item} onOpenDocument={onOpenDocument}/>) : <p className="empty-copy">승인된 신호가 없습니다.</p>}</section>
      <section><header><div><p className="eyebrow">REVIEW QUEUE</p><h3>검토 필요 신호</h3></div><b>{reviewNeeded.length}</b></header>{reviewNeeded.length ? reviewNeeded.map(item=><SignalCard key={item.signalId} signal={item} onOpenDocument={onOpenDocument}/>) : <p className="empty-copy">검토 대기 신호가 없습니다.</p>}</section>
    </div>
  </section>;
}
