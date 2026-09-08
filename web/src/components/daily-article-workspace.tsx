"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  ListFilter,
  Newspaper,
  Rows3,
  Search,
  ShieldCheck,
} from "lucide-react";
import type { DailyArticle, DailyArticleTopic, DailyArticlesResponse } from "@/lib/daily-articles-contract";
import { normalizeDailyArticles, todayInSeoul } from "@/lib/daily-articles-contract";

const DAILY_ARTICLE_BATCH_SIZE = 30;
const REQUEST_TIMEOUT_MS = 10_000;

type CategoryGroup = "TRANSACTION" | "OCCUPANCY" | "DEVELOPMENT" | "CAPITAL" | "CORPORATE" | "OTHER";
type CategorySelection = "ALL" | CategoryGroup | "UNCLASSIFIED";
type ClassificationState = "CONFIRMED" | "AUTOMATIC" | "UNCLASSIFIED";
type Density = "COMPACT" | "SUMMARY";
type LoadError = "TIMEOUT" | "REQUEST" | null;

const categoryGroups: Array<{ key: CategoryGroup; label: string; description: string }> = [
  { key: "TRANSACTION", label: "거래", description: "매각·매입·경공매" },
  { key: "OCCUPANCY", label: "임대·점유", description: "임대차·이전·공실" },
  { key: "DEVELOPMENT", label: "개발·공급", description: "공급·인허가·준공" },
  { key: "CAPITAL", label: "자본·금융", description: "PF·대출·투자·출자" },
  { key: "CORPORATE", label: "기업활동", description: "기업 행위" },
  { key: "OTHER", label: "기타", description: "기타 관리형 주제" },
];

const topicLabels: Record<string, string> = {
  SALE: "매각",
  ACQUISITION: "매입",
  AUCTION: "경공매",
  LEASE: "임대차",
  RELOCATION: "이전",
  VACANCY: "공실",
  SUPPLY: "공급",
  PERMIT: "인허가",
  COMPLETION: "준공",
  PF: "프로젝트금융",
  LOAN: "대출",
  EQUITY_INVESTMENT: "지분투자",
  FUNDRAISING: "자금모집",
  LP_MANDATE: "기관출자",
  CORPORATE_ACTION: "기업행위",
};

const topicGroups = new Map<string, CategoryGroup>([
  ...["SALE", "ACQUISITION", "AUCTION"].map((key) => [key, "TRANSACTION"] as const),
  ...["LEASE", "RELOCATION", "VACANCY"].map((key) => [key, "OCCUPANCY"] as const),
  ...["SUPPLY", "PERMIT", "COMPLETION"].map((key) => [key, "DEVELOPMENT"] as const),
  ...["PF", "LOAN", "EQUITY_INVESTMENT", "FUNDRAISING", "LP_MANDATE"].map((key) => [key, "CAPITAL"] as const),
  ["CORPORATE_ACTION", "CORPORATE"] as const,
]);

function shiftIsoDate(value: string, days: number, maximum: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.valueOf())) return value;
  date.setUTCDate(date.getUTCDate() + days);
  const shifted = date.toISOString().slice(0, 10);
  return shifted > maximum ? maximum : shifted;
}

function formatDateTime(value: string | null, timeOnly = false): string {
  if (!value) return "기록 없음";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    ...(timeOnly ? {} : { month: "numeric", day: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function governedTopicKind(topic: DailyArticleTopic): "APPROVED" | "PENDING" | null {
  if (topic.status === "CONFIRMED" && topic.provenance === "APPROVED_CLASSIFICATION") return "APPROVED";
  if (topic.status === "CANDIDATE" && topic.provenance === "PENDING_CLASSIFICATION") return "PENDING";
  return null;
}

function governedTopics(article: DailyArticle): DailyArticleTopic[] {
  return article.topics.filter((topic) => governedTopicKind(topic) !== null);
}

function primaryTopic(article: DailyArticle): DailyArticleTopic | null {
  const topics = governedTopics(article);
  return topics.find((topic) => governedTopicKind(topic) === "APPROVED")
    ?? topics.find((topic) => governedTopicKind(topic) === "PENDING")
    ?? null;
}

function articleClassification(article: DailyArticle): {
  topic: DailyArticleTopic | null;
  group: CategoryGroup | "UNCLASSIFIED";
  state: ClassificationState;
} {
  const topic = primaryTopic(article);
  if (!topic) return { topic: null, group: "UNCLASSIFIED", state: "UNCLASSIFIED" };
  return {
    topic,
    group: topicGroups.get(topic.key) ?? "OTHER",
    state: governedTopicKind(topic) === "APPROVED" ? "CONFIRMED" : "AUTOMATIC",
  };
}

function includesQuery(article: DailyArticle, query: string): boolean {
  if (!query) return true;
  const haystack = [article.title, article.summary, article.publisher].filter(Boolean).join(" ").toLocaleLowerCase("ko-KR");
  return haystack.includes(query.toLocaleLowerCase("ko-KR"));
}

function presentationTitle(article: DailyArticle): string {
  const publisher = article.publisher?.trim();
  if (!publisher) return article.title;
  const suffix = ` - ${publisher}`;
  return article.title.endsWith(suffix) ? article.title.slice(0, -suffix.length).trimEnd() : article.title;
}

export function DailyArticleWorkspace({
  onOpenArticle,
}: {
  onOpenArticle: (documentId: string, title: string) => void;
}) {
  const today = todayInSeoul();
  const [requestedDate, setRequestedDate] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<CategorySelection>("ALL");
  const [selectedTopic, setSelectedTopic] = useState("");
  const [query, setQuery] = useState("");
  const [density, setDensity] = useState<Density>("COMPACT");
  const [data, setData] = useState<DailyArticlesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<LoadError>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [visibleCount, setVisibleCount] = useState(DAILY_ARTICLE_BATCH_SIZE);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
    queueMicrotask(() => {
      if (disposed) return;
      setLoading(true);
      setError(null);
      setVisibleCount(DAILY_ARTICLE_BATCH_SIZE);
      setSelectedCategory("ALL");
      setSelectedTopic("");
    });
    const endpoint = requestedDate
      ? `/api/articles/daily?date=${encodeURIComponent(requestedDate)}`
      : "/api/articles/daily";
    fetch(endpoint, { signal: controller.signal, credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) throw new Error();
        return normalizeDailyArticles(await response.json());
      })
      .then((value) => { if (!disposed) setData(value); })
      .catch((reason: unknown) => {
        if (disposed) return;
        if (timedOut) setError("TIMEOUT");
        else if (!(reason instanceof DOMException && reason.name === "AbortError")) setError("REQUEST");
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [requestedDate, retryKey]);

  const selectedDate = requestedDate ?? data?.selectedDate ?? today;
  const sortedArticles = useMemo(() => (data?.articles ?? []).slice().sort((left, right) =>
    right.publishedAt.localeCompare(left.publishedAt) || left.id.localeCompare(right.id)
  ), [data]);

  const classifiedArticles = useMemo(() => sortedArticles.map((article) => ({
    article,
    classification: articleClassification(article),
  })), [sortedArticles]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<CategorySelection, number>([["ALL", classifiedArticles.length]]);
    categoryGroups.forEach(({ key }) => counts.set(key, 0));
    counts.set("UNCLASSIFIED", 0);
    classifiedArticles.forEach(({ classification }) => {
      counts.set(classification.group, (counts.get(classification.group) ?? 0) + 1);
    });
    return counts;
  }, [classifiedArticles]);

  const topicCounts = useMemo(() => {
    if (selectedCategory === "ALL" || selectedCategory === "UNCLASSIFIED") return [];
    const counts = new Map<string, number>();
    classifiedArticles.forEach(({ classification }) => {
      if (classification.group !== selectedCategory || !classification.topic) return;
      counts.set(classification.topic.key, (counts.get(classification.topic.key) ?? 0) + 1);
    });
    return [...counts.entries()]
      .map(([key, count]) => ({ key, label: topicLabels[key] ?? key, count }))
      .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, "ko"));
  }, [classifiedArticles, selectedCategory]);

  const filteredArticles = useMemo(() => classifiedArticles.filter(({ article, classification }) => {
    if (selectedCategory !== "ALL" && classification.group !== selectedCategory) return false;
    if (selectedTopic && classification.topic?.key !== selectedTopic) return false;
    return includesQuery(article, query.trim());
  }), [classifiedArticles, query, selectedCategory, selectedTopic]);

  const visibleArticles = filteredArticles.slice(0, visibleCount);
  const moveDate = (days: number) => setRequestedDate(shiftIsoDate(selectedDate, days, today));
  const isToday = selectedDate >= today;
  const returned = data?.returned ?? data?.articles.length ?? 0;
  const confirmedCount = classifiedArticles.filter(({ classification }) => classification.state === "CONFIRMED").length;
  const automaticCount = classifiedArticles.filter(({ classification }) => classification.state === "AUTOMATIC").length;
  const unclassifiedCount = classifiedArticles.filter(({ classification }) => classification.state === "UNCLASSIFIED").length;
  const statusValue = (value: string) => loading ? "조회 중" : error || !data ? "—" : value;

  return <section className="news-workspace" aria-labelledby="news-workspace-title" aria-busy={loading}>
    <header className="news-commandbar">
      <div className="commandbar-title">
        <span>LATEST CRE ARTICLES</span>
        <strong id="news-workspace-title">최신기사</strong>
        <small>주제별 흐름과 검토 상태를 함께 확인합니다.</small>
      </div>
      <div className="daily-date-control" role="group" aria-labelledby="daily-date-label">
        <span id="daily-date-label"><CalendarDays aria-hidden="true" size={15}/>기사 게시일</span>
        <div className="daily-date-stepper">
          <button type="button" aria-label="1일 전으로 이동" title="1일 전" onClick={() => moveDate(-1)}><ChevronLeft aria-hidden="true" size={18}/></button>
          <input aria-label="기사 게시일" type="date" max={today} value={selectedDate} onChange={(event) => event.target.value && setRequestedDate(event.target.value)}/>
          <button type="button" aria-label="1일 후로 이동" title="1일 후" disabled={isToday} onClick={() => moveDate(1)}><ChevronRight aria-hidden="true" size={18}/></button>
          <button type="button" aria-label="DB 최신 게시일로 이동" onClick={() => setRequestedDate(null)}>최신일</button>
        </div>
      </div>
    </header>

    <div className="news-workbench">
      <aside className="topic-rail" aria-labelledby="topic-rail-title">
        <header><ListFilter aria-hidden="true" size={16}/><div><strong id="topic-rail-title">시장 주제</strong><small>기사당 대표 1개</small></div></header>
        <nav aria-label="기사 대표 주제">
          <button type="button" aria-pressed={selectedCategory === "ALL"} onClick={() => { setSelectedCategory("ALL"); setSelectedTopic(""); setVisibleCount(DAILY_ARTICLE_BATCH_SIZE); }}>
            <span><strong>전체</strong><small>불러온 기사</small></span><b>{loading ? "—" : categoryCounts.get("ALL") ?? 0}</b>
          </button>
          {categoryGroups.filter(({ key }) => (categoryCounts.get(key) ?? 0) > 0).map((group) => <button
            type="button"
            key={group.key}
            aria-pressed={selectedCategory === group.key}
            onClick={() => { setSelectedCategory(group.key); setSelectedTopic(""); setVisibleCount(DAILY_ARTICLE_BATCH_SIZE); }}
          ><span><strong>{group.label}</strong><small>{group.description}</small></span><b>{categoryCounts.get(group.key)}</b></button>)}
          {!loading && unclassifiedCount > 0 && <button type="button" className="pending-filter" aria-pressed={selectedCategory === "UNCLASSIFIED"} onClick={() => { setSelectedCategory("UNCLASSIFIED"); setSelectedTopic(""); setVisibleCount(DAILY_ARTICLE_BATCH_SIZE); }}>
            <span><strong>분류 대기</strong><small>주제 확인 필요</small></span><b>{unclassifiedCount}</b>
          </button>}
        </nav>

        {topicCounts.length > 1 && <section className="subtopic-filter" aria-labelledby="subtopic-filter-title">
          <strong id="subtopic-filter-title">세부 주제</strong>
          <div role="group" aria-label="세부 주제 필터">
            <button type="button" aria-pressed={!selectedTopic} onClick={() => setSelectedTopic("")}>전체</button>
            {topicCounts.map((topic) => <button type="button" key={topic.key} aria-pressed={selectedTopic === topic.key} onClick={() => setSelectedTopic(topic.key)}>{topic.label} <b>{topic.count}</b></button>)}
          </div>
        </section>}
      </aside>

      <section className="article-feed" aria-labelledby="article-feed-title">
        <header className="article-feed-toolbar">
          <div>
            <strong id="article-feed-title">{selectedCategory === "ALL" ? "전체 기사" : categoryGroups.find(({ key }) => key === selectedCategory)?.label ?? "분류 대기"}</strong>
            <span>{loading ? "게시일 기준 조회 중" : `${filteredArticles.length.toLocaleString("ko-KR")}건 · 현재 불러온 ${returned.toLocaleString("ko-KR")}건 내 검색`}</span>
          </div>
          <label className="article-search"><Search aria-hidden="true" size={15}/><span className="sr-only">불러온 기사 검색</span><input type="search" value={query} onChange={(event) => { setQuery(event.target.value); setVisibleCount(DAILY_ARTICLE_BATCH_SIZE); }} placeholder="제목·요약·출처 검색"/></label>
          <div className="density-switch" role="group" aria-label="기사 표시 밀도">
            <button type="button" aria-pressed={density === "COMPACT"} onClick={() => setDensity("COMPACT")}><Rows3 aria-hidden="true" size={14}/>간결</button>
            <button type="button" aria-pressed={density === "SUMMARY"} onClick={() => setDensity("SUMMARY")}><Newspaper aria-hidden="true" size={14}/>요약</button>
          </div>
        </header>

        {loading && <div className="state-block"><span className="spinner"/><strong>최신기사를 불러오는 중입니다.</strong><p>연결이 10초 이상 지연되면 다시 조회할 수 있습니다.</p></div>}
        {!loading && error && <div className="state-block error-state" role="alert"><strong>{error === "TIMEOUT" ? "기사 조회 시간이 초과되었습니다." : "기사를 불러오지 못했습니다."}</strong><p>선택한 날짜는 유지됩니다.</p><button type="button" onClick={() => setRetryKey((value) => value + 1)}>다시 조회</button></div>}
        {!loading && !error && data?.articles.length === 0 && <div className="state-block"><strong>{selectedDate}에 확인된 CRE 기사가 없습니다.</strong><p>DB 최신 게시일은 {data.latestAvailableDate ?? "기록 없음"}입니다.</p><button type="button" onClick={() => setRequestedDate(null)}>최신기사 보기</button></div>}
        {!loading && !error && filteredArticles.length === 0 && sortedArticles.length > 0 && <div className="state-block"><strong>현재 조건에 맞는 기사가 없습니다.</strong><p>검색어 또는 대표 주제 필터를 바꿔보세요.</p><button type="button" onClick={() => { setQuery(""); setSelectedCategory("ALL"); setSelectedTopic(""); }}>필터 초기화</button></div>}

        {!loading && !error && visibleArticles.length > 0 && <div className={`daily-article-list density-${density.toLowerCase()}`}>{visibleArticles.map(({ article, classification }) => {
          const topics = governedTopics(article);
          return <article key={article.id} className={`daily-article-row state-${classification.state.toLowerCase()}`}>
            <button type="button" className="article-open" onClick={() => onOpenArticle(article.id, article.title)}>
              <div className="article-topic-tags">
                {topics.slice(0, 3).map((topic, index) => {
                  const kind = governedTopicKind(topic);
                  return <span className={`topic-tag ${kind?.toLowerCase()}`} key={`${topic.key}-${index}`} title={kind === "APPROVED" ? "관리자 검토 완료 분류" : "자동분류 · 검토 전"}>
                    <span>{topicLabels[topic.key] ?? topic.key}</span><em>{kind === "APPROVED" ? "검토완료" : "자동분류"}</em>
                  </span>;
                })}
                {topics.length === 0 && <span className="topic-tag unclassified">분류 대기</span>}
              </div>
              <h2>{presentationTitle(article)}</h2>
              {density === "SUMMARY" && article.summary && <p>{article.summary}</p>}
              <footer>
                <span>{article.publisher ?? "출처 미상"}</span>
                <time dateTime={article.publishedAt}>게시 {formatDateTime(article.publishedAt)}</time>
                {article.evidenceGrade && <span>근거 {article.evidenceGrade.label}</span>}
              </footer>
            </button>
            {article.href && <a className="article-source-link" href={article.href} target="_blank" rel="noreferrer" aria-label={`${article.title} 원문 열기`}>원문 ↗</a>}
          </article>;
        })}</div>}

        {!loading && !error && visibleArticles.length < filteredArticles.length && <div className="article-load-more"><span>{visibleArticles.length.toLocaleString("ko-KR")} / {filteredArticles.length.toLocaleString("ko-KR")}건</span><button type="button" onClick={() => setVisibleCount((count) => count + DAILY_ARTICLE_BATCH_SIZE)}>기사 {Math.min(DAILY_ARTICLE_BATCH_SIZE, filteredArticles.length - visibleArticles.length).toLocaleString("ko-KR")}건 더 보기</button></div>}
      </section>

      <aside className="news-context" aria-labelledby="news-context-title">
        <header><ShieldCheck aria-hidden="true" size={16}/><div><strong id="news-context-title">조회 범위</strong><small>{selectedDate} 게시 기사</small></div></header>
        <dl>
          <div><dt>해당일 전체</dt><dd>{statusValue(`${data?.total.toLocaleString("ko-KR")}건`)}</dd></div>
          <div><dt>현재 불러옴</dt><dd>{statusValue(`${returned.toLocaleString("ko-KR")}건`)}</dd></div>
          <div className="approved"><dt><CheckCircle2 aria-hidden="true" size={13}/>검토 완료 대표주제</dt><dd>{statusValue(`${confirmedCount}건`)}</dd></div>
          <div className="automatic"><dt>자동분류 · 검토 전</dt><dd>{statusValue(`${automaticCount}건`)}</dd></div>
          <div className="unclassified"><dt>분류 대기</dt><dd>{statusValue(`${unclassifiedCount}건`)}</dd></div>
          <div><dt><Clock3 aria-hidden="true" size={13}/>최근 수집</dt><dd>{statusValue(formatDateTime(data?.lastCollectedAt ?? null))}</dd></div>
        </dl>
        <p><b>분류 안내</b> 자동분류는 검토 전 주제입니다. ‘검토 완료’는 담당자가 승인한 대표 주제에만 표시합니다.</p>
        {data && returned < data.total && <small>전체 {data.total.toLocaleString("ko-KR")}건 중 최근 {returned.toLocaleString("ko-KR")}건이 이 화면의 검색·필터 범위입니다.</small>}
      </aside>
    </div>
  </section>;
}
