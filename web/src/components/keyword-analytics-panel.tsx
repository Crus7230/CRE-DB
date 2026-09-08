"use client";
import { useEffect, useMemo, useState } from "react";
import { normalizeKeywordAnalytics, type KeywordAnalyticsItem, type KeywordAnalyticsResponse } from "@/lib/keyword-analytics-contract";

function Sparkline({ item }: { item: KeywordAnalyticsItem }) {
  const points = useMemo(() => {
    const values = item.trend.map((point) => point.documentFrequency); const max = Math.max(1, ...values);
    return values.map((value, index) => `${values.length === 1 ? 100 : index * 200 / (values.length - 1)},${48 - value * 44 / max}`).join(" ");
  }, [item]);
  return <svg className="keyword-spark" viewBox="0 0 200 52" role="img" aria-label={`${item.term} 30일 추이`}><polyline points={points}/></svg>;
}

export function KeywordAnalyticsPanel() {
  const [data, setData] = useState<KeywordAnalyticsResponse | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    fetch("/api/operations/keywords?limit=30", { credentials: "same-origin" })
      .then(async (response) => { if (!response.ok) throw new Error(); return normalizeKeywordAnalytics(await response.json()); })
      .then((value) => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [retry]);
  if (error) return <div className="operations-state error"><strong>키워드 분석을 불러오지 못했습니다.</strong><button type="button" onClick={() => { setError(false); setRetry((v) => v + 1); }}>다시 시도</button></div>;
  if (!data) return <div className="operations-state">키워드 aggregate를 불러오는 중입니다.</div>;
  if (!data.keywords.length) return <div className="operations-state"><strong>아직 refresh된 키워드가 없습니다.</strong><span>일일 analytics refresh 후 표시됩니다.</span></div>;
  return <section className="keyword-panel">
    <div className="operations-notice"><strong>집계 의미</strong><span>발행일 기준 distinct document frequency · 28일 baseline · 수집 query 영향 별도 표시</span></div>
    <div className="keyword-summary"><span>알고리즘 <strong>{data.algorithmVersion}</strong></span><span>사전 <strong>{data.summary.keywordCount.toLocaleString("ko-KR")}</strong></span><span>발행일 미상 제외 <strong>{data.summary.excludedMissingPublicationCount.toLocaleString("ko-KR")}</strong></span></div>
    <div className="keyword-grid">{data.keywords.map((item) => <article className="keyword-card" key={item.keywordId}>
      <header><div><strong>{item.term}</strong>{item.isCollectionBias && <em>수집 query 영향</em>}</div><span>burst {item.burstScore.toFixed(2)}</span></header>
      <Sparkline item={item}/>
      <dl><div><dt>현재 DF</dt><dd>{item.documentFrequency.toLocaleString("ko-KR")}</dd></div><div><dt>28일 baseline</dt><dd>{item.baselineDocumentFrequency.toFixed(1)}</dd></div></dl>
      <footer>{item.cooccurrences.map((peer) => <span key={peer.term}>{peer.term}<b>{peer.documentFrequency}</b></span>)}</footer>
    </article>)}</div>
  </section>;
}
