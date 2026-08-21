"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { ArchivedDetailDrawer } from "@/components/archived-detail-drawer";
import { CompanyWorkspace } from "@/components/company-workspace";
import { DailyArticleWorkspace } from "@/components/daily-article-workspace";
import { DocumentDetailDrawer } from "@/components/document-detail-drawer";
import { EntityDetailDrawer } from "@/components/entity-detail-drawer";
import { InstitutionalCapitalWorkspace } from "@/components/institutional-capital-workspace";
import { SaleProcessWorkspace } from "@/components/sale-process-workspace";
import { TransactionCard } from "@/components/transaction-template";
import type { CategoryIndexItem, CategoryIndexResponse, SearchKind, SearchResponse, SearchResult } from "@/lib/search-contract";

type Workspace = "MARKET" | "DAILY" | "COMPANIES" | "CAPITAL" | "SALES";
type MarketKind = Extract<SearchKind, "EVENT" | "DOCUMENT" | "ASSET">;


const workspaceTabs: Array<{ key: Workspace; label: string; description: string }> = [
  { key: "MARKET", label: "시장 탐색", description: "변화·자산·근거 확인" },
  { key: "DAILY", label: "뉴스 모니터", description: "오늘의 시장 신호" },
  { key: "COMPANIES", label: "기업·임차", description: "기업과 점유 관계" },
  { key: "CAPITAL", label: "기관자금", description: "모집·선정·집행" },
  { key: "SALES", label: "매각 파이프라인", description: "입찰부터 종결까지" },
];

const marketKinds: Array<{ key: MarketKind; label: string; description: string }> = [
  { key: "EVENT", label: "시장 변화", description: "매각·임대·공급·인허가·PF·대출·투자" },
  { key: "ASSET", label: "관련 자산", description: "시장 변화가 발생한 물건과 위치" },
  { key: "DOCUMENT", label: "근거자료", description: "판단에 필요한 거래·공시·기사·공고" },
];

const evidenceDescriptions: Record<string, string> = {
  TRANSACTION_EVIDENCE: "실거래 가격과 면적 확인",
  CORPORATE_EVIDENCE: "기업 공시와 사업 발표 확인",
  MARKET_EVIDENCE: "뉴스·분석·리서치로 흐름 확인",
  PROCESS_EVIDENCE: "입찰과 기관 절차 확인",
};

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
  const [kind, setKind] = useState<MarketKind>("EVENT");
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
  const [retryKey, setRetryKey] = useState(0);
  const [selected, setSelected] = useState<SearchResult | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/index", { signal: controller.signal }).then((response) => response.json() as Promise<CategoryIndexResponse>).then(setIndex).catch(() => undefined);
    return () => controller.abort();
  }, []);

  const activeGroup = useMemo(() => index?.groups.find((group) => group.kind === kind) ?? null, [index, kind]);

  useEffect(() => {
    if (workspace !== "MARKET") return;
    const controller = new AbortController();
    const taxonomyScheme = category && activeGroup && ["MARKET_CATEGORY", "DOCUMENT_PURPOSE"].includes(activeGroup.group) ? activeGroup.group : "";
    const params = new URLSearchParams({ q, kind, from, to, category, classificationScheme: taxonomyScheme, page: "1", pageSize: "50", includeTransactionsUnder1000Eok: String(includeTransactionsUnder1000Eok) });
    queueMicrotask(() => { setLoading(true); setError(false); });
    fetch(`/api/search?${params}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<SearchResponse>; })
      .then(setData).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspace, q, kind, from, to, category, activeGroup, includeTransactionsUnder1000Eok, retryKey]);


  const categoryItems = activeGroup?.items ?? [];
  const selectedCategoryLabel = category ? itemLabel(categoryItems.find((item) => item.key === category) ?? { key: category, label: category, itemCount: 0 }, kind) : marketKinds.find((item) => item.key === kind)?.label;
  const categoryPrompt = kind === "EVENT" ? "변화 유형" : kind === "ASSET" ? "자산 유형" : "근거 목적";

  function submitSearch(event: FormEvent) { event.preventDefault(); setQ(draftQ.trim()); }
  function openResult(item: SearchResult) {
    if (item.kind === "ORGANIZATION") { setCompanyTarget(item.id); setWorkspace("COMPANIES"); return; }
    setSelected(item);
  }

  return <main className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">MI</span><div><strong>Market Intelligence</strong><small>Source-grounded real estate signals</small></div></div><div className="topbar-meta"><span className="live-dot"/>Supabase main · daily article sync</div></header>
    <nav className="workspace-nav" aria-label="업무 화면">
      <div className="workspace-nav-context"><span>업무 화면</span><strong>무엇을 할까요?</strong></div>
      {workspaceTabs.map((tab) => <button type="button" key={tab.key} aria-pressed={workspace === tab.key} onClick={() => { setWorkspace(tab.key); if (tab.key !== "COMPANIES") setCompanyTarget(null); }}><strong>{tab.label}</strong><span>{tab.description}</span></button>)}
    </nav>

    {workspace === "MARKET" && <section className="market-workspace">
      <header className="market-hero"><div><p className="eyebrow">MARKET EXPLORE</p><h1>시장 변화부터 근거까지 한 흐름으로 탐색</h1><p>먼저 찾을 대상을 고르고, 변화 유형·자산 유형·근거 목적과 기간으로 범위를 좁혀 확인합니다.</p></div><form className="hero-search" onSubmit={submitSearch}><input aria-label="통합 검색" value={draftQ} onChange={(event) => setDraftQ(event.target.value)} placeholder="회사·자산·이벤트·근거자료 검색"/><button type="submit">검색</button></form></header>
      <div className="explore-layout">
        <aside className="category-rail">
          <div className="rail-heading"><div><p className="eyebrow">탐색 기준</p><h2>무엇을 찾을까요?</h2><p>현재 업무 안에서 조회 대상을 정합니다.</p></div></div>
          <nav className="domain-nav" aria-label="탐색 대상">{marketKinds.map((item) => <button key={item.key} type="button" aria-pressed={kind === item.key} onClick={() => { setKind(item.key); setCategory(""); }}><strong>{item.label}</strong><span>{item.description}</span></button>)}</nav>
          <div className="category-section-title"><span>{categoryPrompt}</span><small>{kind === "DOCUMENT" ? "원천 형식이 아닌 활용 목적 기준" : "하나를 선택해 결과를 좁힙니다"}</small></div>
          <div className="category-list"><button type="button" aria-pressed={!category} onClick={() => setCategory("")}><span><strong>전체 보기</strong><small>{marketKinds.find((item) => item.key === kind)?.label} 전체</small></span><b>{categoryItems.reduce((sum, item) => sum + item.itemCount, 0)}</b></button>{categoryItems.map((item) => <button type="button" key={item.key} aria-pressed={category === item.key} onClick={() => setCategory(item.key)}><span><strong>{itemLabel(item, kind)}</strong>{kind === "DOCUMENT" && <small>{evidenceDescriptions[item.key]}</small>}</span><b>{item.itemCount}</b></button>)}</div>
        </aside>
        <section className="market-content">
          <section className="detail-filters market-filter-panel" aria-label="조회 조건"><div><p className="eyebrow">조회 조건</p><h2>언제, 어느 범위까지 볼까요?</h2></div><label>시작일<input type="date" value={from} onChange={(event) => setFrom(event.target.value)}/></label><label>종료일<input type="date" value={to} onChange={(event) => setTo(event.target.value)}/></label>{kind === "DOCUMENT" && (!category || category === "TRANSACTION_EVIDENCE") && <label className="toggle-filter"><input type="checkbox" checked={includeTransactionsUnder1000Eok} onChange={(event) => setIncludeTransactionsUnder1000Eok(event.target.checked)}/><span><strong>1,000억원 미만 실거래 포함</strong><small>거래·가격 근거에만 적용</small></span></label>}<button type="button" className="reset-button" onClick={() => { setDraftQ(""); setQ(""); setFrom(""); setTo(""); setIncludeTransactionsUnder1000Eok(false); }}>조건 초기화</button></section>
          <header className="results-heading"><div><p className="result-path">시장 탐색 <span>/</span> {marketKinds.find((item) => item.key === kind)?.label}{category && <> <span>/</span> {selectedCategoryLabel}</>}</p><h2>{selectedCategoryLabel}</h2><p>{q ? `“${q}” · ` : ""}{from || to ? `${from || "최초"}~${to || "현재"}` : "전체 기간"}</p></div><strong>{data?.total.toLocaleString("ko-KR") ?? 0}건</strong></header>
          {loading && <div className="state-block"><span className="spinner"/><strong>{selectedCategoryLabel} 조회 중</strong></div>}
          {!loading && error && <div className="state-block error-state"><strong>데이터를 불러오지 못했습니다.</strong><p>선택한 탐색 기준은 유지됩니다.</p><button type="button" onClick={() => setRetryKey((value) => value + 1)}>다시 조회</button></div>}
          {!loading && !error && data?.results.length === 0 && <div className="state-block"><strong>조건에 맞는 결과가 없습니다.</strong><p>category는 유지하고 상세 필터만 완화해 보세요.</p></div>}
          {!loading && !error && <div className={`projection-list ${kind.toLowerCase()}-projection`}>{data?.results.map((item) => <article key={`${item.kind}-${item.id}`} className={`projection-card ${item.metadata?.documentType === "API_RECORD" ? "transaction-projection-card" : ""}`}><button type="button" onClick={() => openResult(item)}><div className="projection-meta"><span className="category-badge">{item.kind === "DOCUMENT" ? documentLabels[item.category ?? ""] ?? item.categoryLabel : item.categoryLabel}</span><time>{formatDate(item.date)}</time><span>{item.status ?? "상태 미상"}</span></div>{item.kind === "DOCUMENT" && item.metadata?.documentType === "API_RECORD" ? <TransactionCard metadata={item.metadata}/> : <><h3>{item.title}</h3>{item.summary && <p>{item.summary}</p>}</>}<div className="projection-details">{item.kind === "EVENT" && <><span>자산 {metadataText(item.metadata?.assets) || "미연결"}</span><span>참여자 {metadataText(item.metadata?.participants) || "미연결"}</span></>}{item.kind === "DOCUMENT" && item.metadata?.documentType !== "API_RECORD" && <><span>{item.source ?? "출처 미상"}</span><span>{documentLabels[String(item.metadata?.documentType ?? "")] ?? "근거자료"}</span></>}{item.kind === "ASSET" && <><span>{String(item.metadata?.assetClass ?? "자산유형 미상")}</span><span>{String(item.metadata?.region ?? item.summary ?? "지역 미상")}</span></>}</div></button>{item.kind === "DOCUMENT" && item.href && <a className="source-link" href={item.href} target="_blank" rel="noreferrer">{item.metadata?.documentType === "API_RECORD" ? "API" : "원문"}</a>}</article>)}</div>}
        </section>
      </div>
    </section>}

    {workspace === "DAILY" && <DailyArticleWorkspace onOpenArticle={(documentId, title) => setSelected({ kind: "DOCUMENT", id: documentId, title, subtitle: null, summary: null, date: null, status: null, confidence: null, source: null, href: null, category: "RSS_ITEM", categoryLabel: "시장기사", metadata: { documentType: "RSS_ITEM" } })}/>}
    {workspace === "COMPANIES" && <CompanyWorkspace key={companyTarget ?? "company-workspace"} initialCompanyId={companyTarget}/>}
    {workspace === "CAPITAL" && <InstitutionalCapitalWorkspace/>}
    {workspace === "SALES" && <SaleProcessWorkspace/>}

    {selected?.metadata?.archived === true && <ArchivedDetailDrawer result={selected} onClose={() => setSelected(null)}/>}
    {selected?.metadata?.archived !== true && selected?.kind === "DOCUMENT" && <DocumentDetailDrawer documentId={selected.id} fallbackTitle={selected.title} onClose={() => setSelected(null)}/>}
    {selected?.metadata?.archived !== true && selected && (selected.kind === "EVENT" || selected.kind === "ASSET") && <EntityDetailDrawer kind={selected.kind} id={selected.id} fallbackTitle={selected.title} onClose={() => setSelected(null)}/>}
  </main>;
}
