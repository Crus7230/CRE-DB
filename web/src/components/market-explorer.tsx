"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { CompanyWorkspace } from "@/components/company-workspace";
import { DocumentDetailDrawer } from "@/components/document-detail-drawer";
import { EntityDetailDrawer } from "@/components/entity-detail-drawer";
import { InstitutionalCapitalWorkspace } from "@/components/institutional-capital-workspace";
import { SaleProcessWorkspace } from "@/components/sale-process-workspace";
import { TransactionCard } from "@/components/transaction-template";
import type { CategoryIndexItem, CategoryIndexResponse, SearchKind, SearchResponse, SearchResult } from "@/lib/search-contract";

type Workspace = "MARKET" | "COMPANIES" | "CAPITAL" | "SALES";
type MarketKind = Extract<SearchKind, "EVENT" | "DOCUMENT" | "ASSET">;


const workspaceTabs: Array<{ key: Workspace; label: string; description: string }> = [
  { key: "MARKET", label: "시장·문서", description: "카테고리별 탐색" },
  { key: "COMPANIES", label: "회사·임차", description: "시총·업종·관계" },
  { key: "CAPITAL", label: "기관자금", description: "Mandate·선정·집행" },
  { key: "SALES", label: "매각절차", description: "입찰·우협·종결" },
];

const marketKinds: Array<{ key: MarketKind; label: string; description: string }> = [
  { key: "EVENT", label: "시장 이벤트", description: "매각·임대·공급·인허가·PF·대출·투자" },
  { key: "DOCUMENT", label: "문서 라이브러리", description: "공시·공식 API·기사·공고를 출처별 구분" },
  { key: "ASSET", label: "자산", description: "이벤트와 연결된 canonical asset" },
];

const documentLabels: Record<string, string> = {
  API_RECORD: "공식 실거래 원자료", DISCLOSURE: "기업공시", OFFICIAL_FILING: "기업공시",
  RSS_ITEM: "시장기사·RSS", ARTICLE: "분석기사", PRESS_RELEASE: "보도자료",
  BID_NOTICE: "입찰공고", NOTICE: "기관공고", RESEARCH_REPORT: "리서치 보고서",
};

function itemLabel(item: CategoryIndexItem, kind: MarketKind) {
  return kind === "DOCUMENT" ? documentLabels[item.key] ?? item.label : item.label;
}

function formatDate(value: string | null) { return value ? value.slice(0, 10) : "날짜 미상"; }
function metadataText(value: unknown) { return typeof value === "string" ? value : ""; }

export function MarketExplorer() {
  const [workspace, setWorkspace] = useState<Workspace>("MARKET");
  const [companyTarget, setCompanyTarget] = useState<string | null>(null);
  const [kind, setKind] = useState<MarketKind>("DOCUMENT");
  const [category, setCategory] = useState("");
  const [draftQ, setDraftQ] = useState("");
  const [q, setQ] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [includeTransactionsUnder1000Eok, setIncludeTransactionsUnder1000Eok] = useState(false);
  const [index, setIndex] = useState<CategoryIndexResponse | null>(null);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [selected, setSelected] = useState<SearchResult | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/index", { signal: controller.signal }).then((response) => response.json() as Promise<CategoryIndexResponse>).then(setIndex).catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (workspace !== "MARKET") return;
    const controller = new AbortController();
    const params = new URLSearchParams({ q, kind, from, to, category, page: "1", pageSize: "50", includeTransactionsUnder1000Eok: String(includeTransactionsUnder1000Eok) });
    queueMicrotask(() => { setLoading(true); setError(false); });
    fetch(`/api/search?${params}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<SearchResponse>; })
      .then(setData).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspace, q, kind, from, to, category, includeTransactionsUnder1000Eok]);


  const activeGroup = useMemo(() => index?.groups.find((group) => group.kind === kind) ?? null, [index, kind]);
  const categoryItems = activeGroup?.items ?? [];
  const selectedCategoryLabel = category ? itemLabel(categoryItems.find((item) => item.key === category) ?? { key: category, label: category, itemCount: 0 }, kind) : marketKinds.find((item) => item.key === kind)?.label;

  function submitSearch(event: FormEvent) { event.preventDefault(); setQ(draftQ.trim()); }
  function openResult(item: SearchResult) {
    if (item.kind === "ORGANIZATION") { setCompanyTarget(item.id); setWorkspace("COMPANIES"); return; }
    setSelected(item);
  }

  return <main className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">MI</span><div><strong>Market Intelligence</strong><small>Source-grounded real estate signals</small></div></div><div className="topbar-meta"><span className="live-dot"/>Supabase main · 2026-07-31</div></header>
    <nav className="workspace-nav" aria-label="주요 분석 영역">{workspaceTabs.map((tab) => <button type="button" key={tab.key} aria-pressed={workspace === tab.key} onClick={() => { setWorkspace(tab.key); if (tab.key !== "COMPANIES") setCompanyTarget(null); }}><strong>{tab.label}</strong><span>{tab.description}</span></button>)}</nav>

    {workspace === "MARKET" && <section className="market-workspace">
      <header className="market-hero"><div><p className="eyebrow">CATEGORY-FIRST EXPLORE</p><h1>시장 카테고리로 찾고, 근거문서로 검증</h1><p>검색어는 범위를 좁히는 수단이며, 탐색의 출발점은 매각·임대·공급·인허가·PF·대출·투자 category입니다.</p></div><form className="hero-search" onSubmit={submitSearch}><input aria-label="통합 검색" value={draftQ} onChange={(event) => setDraftQ(event.target.value)} placeholder="회사·자산·이벤트·문서 검색"/><button type="submit">검색</button></form></header>
      <div className="explore-layout">
        <aside className="category-rail"><div className="rail-heading"><span>01</span><div><p className="eyebrow">CATEGORY</p><h2>탐색 영역</h2></div></div><nav className="domain-nav">{marketKinds.map((item) => <button key={item.key} type="button" aria-pressed={kind === item.key} onClick={() => { setKind(item.key); setCategory(""); }}><strong>{item.label}</strong><span>{item.description}</span></button>)}</nav><div className="category-list"><button type="button" aria-pressed={!category} onClick={() => setCategory("")}><span>전체 {marketKinds.find((item) => item.key === kind)?.label}</span><b>{categoryItems.reduce((sum, item) => sum + item.itemCount, 0)}</b></button>{categoryItems.map((item) => <button type="button" key={item.key} aria-pressed={category === item.key} onClick={() => setCategory(item.key)}><span>{itemLabel(item, kind)}</span><b>{item.itemCount}</b></button>)}</div></aside>
        <section className="market-content">
          <section className="detail-filters market-filter-panel" aria-label="상세 필터"><div><span className="step-index">02</span><p className="eyebrow">FILTER</p><h2>상세 필터</h2></div><label>시작일<input type="date" value={from} onChange={(event) => setFrom(event.target.value)}/></label><label>종료일<input type="date" value={to} max="2026-07-31" onChange={(event) => setTo(event.target.value)}/></label>{kind === "DOCUMENT" && <label className="toggle-filter"><input type="checkbox" checked={includeTransactionsUnder1000Eok} onChange={(event) => setIncludeTransactionsUnder1000Eok(event.target.checked)}/><span><strong>1,000억원 미만 실거래 포함</strong><small>기본 조회에서는 숨김</small></span></label>}<button type="button" className="reset-button" onClick={() => { setDraftQ(""); setQ(""); setFrom(""); setTo(""); setIncludeTransactionsUnder1000Eok(false); }}>초기화</button></section>
          <header className="results-heading"><div><p className="eyebrow">RESULT</p><h2>{selectedCategoryLabel}</h2><p>{q ? `“${q}” · ` : ""}{from || to ? `${from || "최초"}~${to || "현재"}` : "전체 기간"}</p></div><strong>{data?.total.toLocaleString("ko-KR") ?? 0}건</strong></header>
          {kind === "DOCUMENT" && <section className="document-taxonomy"><p className="eyebrow">DOCUMENT TYPES</p><div>{categoryItems.map((item) => <button type="button" key={item.key} aria-pressed={category === item.key} onClick={() => setCategory(item.key)}><strong>{itemLabel(item, kind)}</strong><span>{item.itemCount.toLocaleString("ko-KR")}건</span></button>)}</div></section>}
          {loading && <div className="state-block"><span className="spinner"/><strong>{selectedCategoryLabel} 조회 중</strong></div>}
          {!loading && error && <div className="state-block error-state"><strong>조회 오류</strong><p>잠시 후 다시 시도해 주세요.</p></div>}
          {!loading && !error && data?.results.length === 0 && <div className="state-block"><strong>조건에 맞는 결과가 없습니다.</strong><p>category는 유지하고 상세 필터만 완화해 보세요.</p></div>}
          {!loading && !error && <div className={`projection-list ${kind.toLowerCase()}-projection`}>{data?.results.map((item) => <article key={`${item.kind}-${item.id}`} className={`projection-card ${item.metadata?.documentType === "API_RECORD" ? "transaction-projection-card" : ""}`}><button type="button" onClick={() => openResult(item)}><div className="projection-meta"><span className="category-badge">{item.kind === "DOCUMENT" ? documentLabels[item.category ?? ""] ?? item.categoryLabel : item.categoryLabel}</span><time>{formatDate(item.date)}</time><span>{item.status ?? "상태 미상"}</span></div>{item.kind === "DOCUMENT" && item.metadata?.documentType === "API_RECORD" ? <TransactionCard metadata={item.metadata}/> : <><h3>{item.title}</h3>{item.summary && <p>{item.summary}</p>}</>}<div className="projection-details">{item.kind === "EVENT" && <><span>자산 {metadataText(item.metadata?.assets) || "미연결"}</span><span>참여자 {metadataText(item.metadata?.participants) || "미연결"}</span></>}{item.kind === "DOCUMENT" && item.metadata?.documentType !== "API_RECORD" && <><span>{item.source ?? "출처 미상"}</span><span>{String(item.metadata?.documentType ?? "문서유형 미상")}</span></>}{item.kind === "ASSET" && <><span>{String(item.metadata?.assetClass ?? "자산유형 미상")}</span><span>{String(item.metadata?.region ?? item.summary ?? "지역 미상")}</span></>}</div></button>{item.kind === "DOCUMENT" && item.href && <a className="source-link" href={item.href} target="_blank" rel="noreferrer">{item.metadata?.documentType === "API_RECORD" ? "API" : "원문"}</a>}</article>)}</div>}
        </section>
      </div>
    </section>}

    {workspace === "COMPANIES" && <CompanyWorkspace key={companyTarget ?? "company-workspace"} initialCompanyId={companyTarget}/>}
    {workspace === "CAPITAL" && <InstitutionalCapitalWorkspace/>}
    {workspace === "SALES" && <SaleProcessWorkspace/>}

    {selected?.kind === "DOCUMENT" && <DocumentDetailDrawer documentId={selected.id} fallbackTitle={selected.title} onClose={() => setSelected(null)}/>}
    {selected && (selected.kind === "EVENT" || selected.kind === "ASSET") && <EntityDetailDrawer kind={selected.kind} id={selected.id} fallbackTitle={selected.title} onClose={() => setSelected(null)}/>}
  </main>;
}
