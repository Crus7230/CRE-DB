"use client";

import { FormEvent, useEffect, useState } from "react";
import type {
  ContextualSearchMode,
  ContextualSearchResponse,
  ContextualSearchResult,
} from "@/lib/contextual-search-contract";

type Props = {
  onOpenEvent: (eventId: string, title: string) => void;
  onOpenDocument: (documentId: string, title: string) => void;
};

const modes: Array<{ key: ContextualSearchMode; label: string; description: string }> = [
  { key: "APPROVED", label: "승인 정보", description: "검토 완료" },
  { key: "CANDIDATE", label: "검토 후보", description: "자동 추출" },
  { key: "LEGACY", label: "LEGACY 감사", description: "이전 파생결과" },
];

const domains = [
  ["", "전체 사건"], ["TRANSACTION", "매각·인수"], ["MANAGER_SELECTION", "위탁운용사 선정"],
  ["POLICY_REGULATION", "정책·규제"], ["MONETARY_POLICY", "금리·통화정책"],
  ["GEOPOLITICS_TRADE", "전쟁·제재·관세"], ["INDUSTRY_DEMAND", "산업·수요"],
  ["MARKET_TREND", "시장 추세"], ["ASSET_REGIONAL_CHANGE", "자산·지역 변화"],
  ["FINANCING_RESTRUCTURING", "금융·구조조정"],
] as const;
const stages = [["", "전체 단계"], ["ANNOUNCED", "발표"], ["PLANNED", "추진·예정"],
  ["BIDDING", "입찰"], ["PREFERRED_BIDDER_SELECTED", "우협 선정"], ["SELECTED", "최종 선정"],
  ["SIGNED", "계약"], ["CLOSED", "종결"], ["EFFECTIVE", "시행"], ["WITHDRAWN", "철회"]] as const;
const roles = [["", "전체 역할"], ["SELLER", "매도인"], ["BUYER", "매수인"],
  ["ADVISOR", "자문사"], ["BIDDER", "입찰자"], ["PREFERRED_BIDDER", "우선협상대상자"],
  ["APPOINTING_ENTITY", "선정기관·LP"], ["SELECTED_MANAGER", "선정 운용사"], ["POLICY_ACTOR", "정책기관"]] as const;
const impacts = [["", "전체 영향"], ["INCREASE", "증가·상승"], ["DECREASE", "감소·하락"],
  ["TIGHTEN", "긴축·강화"], ["EASE", "완화"], ["DISRUPT", "차질"], ["ENABLE", "촉진"]] as const;
const grades = [["", "전체 근거"], ["OFFICIAL_DIRECT", "공식 직접"], ["OFFICIAL_DERIVED", "공식 파생"],
  ["MULTI_SOURCE_CORROBORATED", "복수 근거"], ["MEDIA_DIRECT", "언론 직접"], ["INFERRED", "추론"]] as const;

const labels: Record<string, string> = Object.fromEntries([...domains, ...stages, ...roles, ...impacts, ...grades]);

function optionList(items: ReadonlyArray<readonly [string, string]>) {
  return items.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>);
}

function metadataString(result: ContextualSearchResult, key: string) {
  const value = result.metadata?.[key];
  return typeof value === "string" ? value : "";
}

type SearchFilters = {
  q: string; domain: string; stage: string; role: string; impact: string;
  sourceGrade: string; from: string; to: string;
};

function searchUrl(mode: ContextualSearchMode, filters: SearchFilters) {
  const params = new URLSearchParams({
    mode, q: filters.q.trim(), domain: filters.domain, stage: filters.stage,
    role: filters.role, impact: filters.impact, sourceGrade: filters.sourceGrade,
    from: filters.from, to: filters.to, page: "1", pageSize: "50",
  });
  return `/api/contextual-search?${params}`;
}

const emptyFilters: SearchFilters = {
  q: "", domain: "", stage: "", role: "", impact: "", sourceGrade: "", from: "", to: "",
};

export function ContextualIntelligenceSearch({ onOpenEvent, onOpenDocument }: Props) {
  const [mode, setMode] = useState<ContextualSearchMode>("APPROVED");
  const [q, setQ] = useState("");
  const [domain, setDomain] = useState("");
  const [stage, setStage] = useState("");
  const [role, setRole] = useState("");
  const [impact, setImpact] = useState("");
  const [sourceGrade, setSourceGrade] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [request, setRequest] = useState<{ url: string; sequence: number }>(() => ({
    url: searchUrl("APPROVED", emptyFilters), sequence: 1,
  }));
  const [data, setData] = useState<ContextualSearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(request.url, { signal: controller.signal, cache: "no-store" })
      .then((response) => { if (!response.ok) throw new Error("unavailable"); return response.json() as Promise<ContextualSearchResponse>; })
      .then(setData)
      .catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [request]);

  function queueSearch(nextMode: ContextualSearchMode, filters: SearchFilters) {
    setLoading(true);
    setError(false);
    setRequest((current) => ({ url: searchUrl(nextMode, filters), sequence: current.sequence + 1 }));
  }
  function currentFilters(): SearchFilters { return { q, domain, stage, role, impact, sourceGrade, from, to }; }
  function requestSearch() { queueSearch(mode, currentFilters()); }
  function submit(event: FormEvent) { event.preventDefault(); requestSearch(); }
  function changeMode(next: ContextualSearchMode) {
    if (next === mode) return;
    setMode(next); setData(null); queueSearch(next, currentFilters());
  }
  function reset() {
    setQ(""); setDomain(""); setStage(""); setRole(""); setImpact("");
    setSourceGrade(""); setFrom(""); setTo(""); setData(null); queueSearch(mode, emptyFilters);
  }

  const description = mode === "APPROVED"
    ? "승인된 사실·사건만 기본 조회합니다."
    : mode === "CANDIDATE"
      ? "자동 추출 후보이며 승인 정보가 아닙니다."
      : "기존 파생결과의 격리 ledger입니다. 일반 검색에는 사용되지 않습니다.";

  return <section className="context-search" aria-labelledby="context-search-title">
    <header className="context-search-heading">
      <div><p className="eyebrow">CONTEXTUAL INTELLIGENCE</p><h2 id="context-search-title">사건·역할·단계·영향 조합 검색</h2><p>{description}</p></div>
      <strong>{data ? `${data.total.toLocaleString("ko-KR")}건` : "조건 조회"}</strong>
    </header>
    <div className="context-mode-switch" role="group" aria-label="검증 상태">{modes.map((item) => <button type="button" key={item.key} aria-pressed={mode === item.key} onClick={() => changeMode(item.key)}><strong>{item.label}</strong><span>{item.description}</span></button>)}</div>
    <form onSubmit={submit} className="context-search-form">
      <label className="context-query">검색어<input value={q} onChange={(event) => setQ(event.target.value)} placeholder={mode === "LEGACY" ? "테이블·레코드 ID·격리 사유" : "회사·자산·사건·근거 문장"}/></label>
      {mode !== "LEGACY" && <>
        <label>사건<select value={domain} onChange={(event) => setDomain(event.target.value)}>{optionList(domains)}</select></label>
        <label>단계<select value={stage} onChange={(event) => setStage(event.target.value)}>{optionList(stages)}</select></label>
        <label>참여 역할<select value={role} onChange={(event) => setRole(event.target.value)}>{optionList(roles)}</select></label>
        <label>영향 방향<select value={impact} onChange={(event) => setImpact(event.target.value)}>{optionList(impacts)}</select></label>
        <label>근거 등급<select value={sourceGrade} onChange={(event) => setSourceGrade(event.target.value)}>{optionList(grades)}</select></label>
        <label>시작일<input type="date" value={from} onChange={(event) => setFrom(event.target.value)}/></label>
        <label>종료일<input type="date" value={to} onChange={(event) => setTo(event.target.value)}/></label>
      </>}
      <div className="context-form-actions"><button type="button" onClick={reset}>초기화</button><button type="submit">조회</button></div>
    </form>
    {loading && <div className="context-state"><span className="spinner"/><strong>문맥 관계 조회 중</strong></div>}
    {!loading && error && <div className="context-state error-state"><strong>문맥형 검색을 불러오지 못했습니다.</strong><button type="button" onClick={requestSearch}>다시 조회</button></div>}
    {!loading && !error && data?.results.length === 0 && <div className="context-state"><strong>조건에 맞는 결과가 없습니다.</strong><p>단계나 역할 조건을 완화해 보세요.</p></div>}
    {!loading && !error && data && data.results.length > 0 && <div className="context-results">{data.results.map((result) => {
      const documentId = metadataString(result, "documentId");
      const resultMode = result.mode ?? mode;
      const participantRoles = Array.isArray(result.participantRoles) ? result.participantRoles : [];
      const impactDirections = Array.isArray(result.impactDirections) ? result.impactDirections : [];
      const why = [result.eventDomain, result.stageCode, ...participantRoles, ...impactDirections].filter(Boolean).map((item) => labels[String(item)] ?? item).join(" · ");
      return <article key={result.id} className={`context-result ${resultMode.toLowerCase()}`}>
        <div className="context-result-meta"><span>{resultMode === "APPROVED" ? "승인" : resultMode === "CANDIDATE" ? "검토 후보" : "LEGACY"}</span>{result.eventDate && <time>{result.eventDate}</time>}{result.sourceGrade && <span>{labels[result.sourceGrade] ?? result.sourceGrade}</span>}</div>
        <h3>{result.title}</h3>{result.summary && <p>{result.summary}</p>}
        {result.evidenceText && <blockquote>{result.evidenceText}</blockquote>}
        <div className="context-why"><strong>매칭 근거</strong><span>{why || "원문 텍스트"}</span></div>
        <div className="context-result-actions">
          {result.sourceRecordKind === "CANONICAL_EVENT" && <button type="button" onClick={() => onOpenEvent(result.sourceRecordId, result.title)}>이벤트 열기</button>}
          {documentId && <button type="button" onClick={() => onOpenDocument(documentId, result.title)}>근거 문서</button>}
        </div>
      </article>;
    })}</div>}
  </section>;
}
