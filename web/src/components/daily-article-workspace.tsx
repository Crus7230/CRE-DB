"use client";

import { useEffect, useState } from "react";
import type { DailyArticlesResponse } from "@/lib/daily-articles-contract";
import { todayInSeoul } from "@/lib/daily-articles-contract";

function formatDateTime(value: string | null): string {
  if (!value) return "기록 없음";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function DailyArticleWorkspace({
  onOpenArticle,
}: {
  onOpenArticle: (documentId: string, title: string) => void;
}) {
  const today = todayInSeoul();
  const [selectedDate, setSelectedDate] = useState(today);
  const [data, setData] = useState<DailyArticlesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => { setLoading(true); setError(false); });
    fetch(`/api/articles/daily?date=${encodeURIComponent(selectedDate)}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<DailyArticlesResponse>; })
      .then(setData)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [selectedDate]);

  return <section className="daily-workspace domain-workspace">
    <header className="workspace-hero daily-hero">
      <div><p className="eyebrow">DAILY MARKET ARTICLES</p><h2>매일 확인하는 부동산 시장기사</h2><p>공개 원문이 확보된 기사는 본문 기반 요약으로 제공합니다. 원문·수집시각·요약 근거를 함께 표시합니다.</p></div>
      <label className="daily-date-control">기사 게시일<input aria-label="기사 게시일" type="date" max={today} value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)}/></label>
    </header>
    <section className="daily-freshness" aria-label="기사 수집 최신성">
      <div><span>선택일</span><strong>{selectedDate}</strong></div>
      <div><span>기사 수</span><strong>{data?.total.toLocaleString("ko-KR") ?? 0}건</strong></div>
      <div><span>최근 수집</span><strong>{formatDateTime(data?.lastCollectedAt ?? null)}</strong></div>
      <div><span>DB 최신 게시일</span><strong>{data?.latestAvailableDate ?? "기록 없음"}</strong></div>
    </section>
    {loading && <div className="state-block"><span className="spinner"/><strong>시장기사 조회 중</strong></div>}
    {!loading && error && <div className="state-block error-state"><strong>기사 조회 오류</strong><p>수집 상태를 확인한 후 다시 시도해 주세요.</p></div>}
    {!loading && !error && data?.articles.length === 0 && <div className="state-block"><strong>{selectedDate} 게시 기사가 없습니다.</strong><p>DB 최신 게시일은 {data.latestAvailableDate ?? "기록 없음"}입니다.</p></div>}
    {!loading && !error && <div className="daily-article-list">{data?.articles.map((article) => <article key={article.id} className="daily-article-card">
      <button type="button" onClick={() => onOpenArticle(article.id, article.title)}>
        <div className="projection-meta"><span className="category-badge">시장기사</span><span className={`summary-mode ${article.summaryMode.toLowerCase()}`}>{article.summaryMode === "MODEL" ? "생성 요약" : article.summaryMode === "BODY_EXTRACTIVE" ? "본문 요약" : "요약 없음"}</span><time>{formatDateTime(article.publishedAt)}</time><span>{article.publisher ?? "출처 미상"}</span></div>
        <h3>{article.title}</h3>
        {article.summary ? <p>{article.summary}</p> : <p className="empty-copy">공개 본문을 확보하지 못해 제목 외 요약을 표시하지 않습니다.</p>}
        <small>수집 {formatDateTime(article.collectedAt)}{article.summaryGeneratedAt ? ` · 요약 ${formatDateTime(article.summaryGeneratedAt)}` : ""}</small>
      </button>
      {article.href && <a className="source-link" href={article.href} target="_blank" rel="noreferrer">원문</a>}
    </article>)}</div>}
  </section>;
}
