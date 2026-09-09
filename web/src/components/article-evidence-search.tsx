"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { ExternalLink, Search, Tags } from "lucide-react";
import {
  EVIDENCE_SEARCH_MAX_RESULTS,
  EvidenceSearchRequestError,
  normalizeEvidenceSearchResponse,
  parseEvidenceSearchBody,
  type EvidenceSearchResponse,
} from "@/lib/evidence-search-contract";

const REQUEST_TIMEOUT_MS = 10_000;

const topics = [
  ["", "전체 주제"],
  ["SALE", "매각"],
  ["ACQUISITION", "매입"],
  ["AUCTION", "경공매"],
  ["LEASE", "임대차"],
  ["RELOCATION", "이전"],
  ["VACANCY", "공실"],
  ["SUPPLY", "공급"],
  ["PERMIT", "인허가"],
  ["COMPLETION", "준공"],
  ["PF", "프로젝트금융"],
  ["LOAN", "대출"],
  ["EQUITY_INVESTMENT", "지분투자"],
  ["FUNDRAISING", "자금모집"],
  ["LP_MANDATE", "기관출자"],
  ["CORPORATE_ACTION", "기업활동"],
] as const;

function formatPublishedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value.slice(0, 10);
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).format(date);
}

function normalizeComparableText(value: string) {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ").toLocaleLowerCase("ko-KR");
}

export function ArticleEvidenceSearch({
  onOpenArticle,
}: {
  onOpenArticle: (documentId: string, title: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [topic, setTopic] = useState("");
  const [data, setData] = useState<EvidenceSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    let search;
    try {
      search = parseEvidenceSearchBody({
        q: query,
        from: from || null,
        to: to || null,
        topic: topic || null,
        topK: EVIDENCE_SEARCH_MAX_RESULTS,
      });
    } catch (reason) {
      setError(reason instanceof EvidenceSearchRequestError && reason.message.includes("query")
        ? "검색어를 두 글자 이상 입력해 주세요."
        : "검색 기간과 주제 조건을 확인해 주세요.");
      return;
    }

    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const timeout = window.setTimeout(() => controller.abort("timeout"), REQUEST_TIMEOUT_MS);
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/evidence-search", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(search),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("request failed");
      const payload = await response.json() as unknown;
      setData(normalizeEvidenceSearchResponse(payload, search));
    } catch {
      if (controller.signal.aborted && activeRequest.current !== controller) return;
      setError(controller.signal.aborted
        ? "검색 시간이 초과되었습니다. 조건을 좁혀 다시 검색해 주세요."
        : "근거 검색을 불러오지 못했습니다. 잠시 후 다시 검색해 주세요.");
    } finally {
      window.clearTimeout(timeout);
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setLoading(false);
      }
    }
  }

  return <section className="article-evidence-search" aria-labelledby="article-evidence-search-title" aria-busy={loading}>
    <details>
      <summary className="evidence-search-heading">
        <div>
          <span>INDEXED ARTICLE SEARCH</span>
          <h2 id="article-evidence-search-title">근거 검색</h2>
          <p>사전 색인에서 관련 기사와 검증 가능한 원문을 찾습니다.</p>
        </div>
        <small><Tags aria-hidden="true" size={14}/>열어서 검색 · 최대 {EVIDENCE_SEARCH_MAX_RESULTS}건</small>
      </summary>

      <form className="evidence-search-form" onSubmit={submit}>
      <label className="evidence-query">
        <span>기사 검색어</span>
        <div><Search aria-hidden="true" size={16}/><input type="search" required minLength={2} maxLength={200} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="예: 매각"/></div>
      </label>
      <label><span>시작일</span><input type="date" value={from} max={to || undefined} onChange={(event) => setFrom(event.target.value)}/></label>
      <label><span>종료일</span><input type="date" value={to} min={from || undefined} onChange={(event) => setTo(event.target.value)}/></label>
      <label><span>기사 주제</span><select value={topic} onChange={(event) => setTopic(event.target.value)}>{topics.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}</select></label>
      <button type="submit" disabled={loading}>{loading ? "검색 중" : "근거 찾기"}</button>
      </form>

      {!data && !loading && !error && <p className="evidence-search-guide">두 글자 이상의 한 검색어 또는 문구를 입력해 주세요.</p>}
      {error && <div className="evidence-search-state error-state" role="alert"><strong>{error}</strong></div>}
      {loading && <div className="evidence-search-state"><span className="spinner"/><strong>색인에서 관련 근거를 찾는 중입니다.</strong></div>}
      {!loading && !error && data && <div className="evidence-search-output">
        <div className="evidence-search-summary">
          <strong>“{data.query}” 관련 근거 {data.returned.toLocaleString("ko-KR")}건 · 최대 {data.maxResults}건</strong>
          <span>{data.truncated ? "관련도 높은 결과만 표시" : "현재 조건의 반환 결과"}</span>
        </div>
        {data.items.length === 0
          ? <div className="evidence-search-state"><strong>일치하는 근거가 없습니다.</strong><p>검색어 또는 기간·주제 조건을 바꿔 보세요.</p></div>
          : <div className="evidence-result-list">{data.items.map((item) => {
            const titleOnlyMatch = normalizeComparableText(item.evidenceText) === normalizeComparableText(item.title);
            return <article key={item.documentId}>
              <header><span>{item.publisher ?? "출처 미상"}</span><time dateTime={item.publishedAt}>{formatPublishedAt(item.publishedAt)}</time></header>
              <h3>{item.title}</h3>
              {titleOnlyMatch
                ? <span className="evidence-title-match">제목 일치</span>
                : <blockquote><strong>기사 발췌</strong><p>{item.evidenceText}</p></blockquote>}
              <footer>
                <button type="button" onClick={() => onOpenArticle(item.documentId, item.title)}>기사 상세</button>
                {item.href && <a href={item.href} target="_blank" rel="noreferrer">원문 열기 <ExternalLink aria-hidden="true" size={13}/></a>}
              </footer>
            </article>;
          })}</div>}
      </div>}
    </details>
  </section>;
}
