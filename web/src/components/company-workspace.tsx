"use client";

import { useEffect, useMemo, useState } from "react";
import type { CompanyDetailResponse, CompanyListResponse, CompanyView } from "@/lib/intelligence-contract";

type DetailTab = "EVENTS" | "ASSETS" | "DOCUMENTS" | "OCCUPANCIES";

const viewLabels: Array<{ key: CompanyView; label: string; description: string }> = [
  { key: "OVERALL", label: "시가총액 상위 50", description: "2026-07-31 KRX 공식 snapshot" },
  { key: "INDUSTRY", label: "업종별 상위 10", description: "KIND 업종별 시가총액 순위" },
  { key: "TENANT_SIGNALS", label: "임차·이전 신호", description: "확정 점유와 문서 언급을 구분" },
];

function marketCap(value: string | null) {
  if (!value) return "-";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  if (amount >= 1e12) return `${(amount / 1e12).toFixed(1)}조원`;
  return `${Math.round(amount / 1e8).toLocaleString("ko-KR")}억원`;
}

function recordText(record: Record<string, string | number | null>, keys: string[]) {
  return keys.map((key) => record[key]).filter((value) => value !== null && value !== undefined && value !== "").join(" · ");
}

function companyNarrative(detail: CompanyDetailResponse): string {
  const rank = detail.organization.overallRank ? `시가총액 전체 ${detail.organization.overallRank}위` : "시가총액 순위 미확인";
  return `${detail.organization.name}은 ${detail.organization.industry ?? detail.organization.organizationType} 분류의 회사로 ${rank}, 기준 시가총액은 ${marketCap(detail.organization.marketCap)}입니다. 직접 연결된 이벤트 ${detail.counts.events}건, 자산 ${detail.counts.assets}건, 문서 ${detail.counts.documents}건, 승인 점유관계 ${detail.counts.occupancies}건이 확인됩니다.`;
}

export function CompanyWorkspace({ initialCompanyId = null }: { initialCompanyId?: string | null }) {
  const [view, setView] = useState<CompanyView>("OVERALL");
  const [industry, setIndustry] = useState("");
  const [q, setQ] = useState("");
  const [data, setData] = useState<CompanyListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(initialCompanyId);
  const [detail, setDetail] = useState<CompanyDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>("EVENTS");


  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ view, industry, q, limit: view === "OVERALL" ? "50" : "100" });
    queueMicrotask(() => { setLoading(true); setError(false); });
    fetch(`/api/companies?${params}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<CompanyListResponse>; })
      .then(setData).catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true);
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [view, industry, q]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    queueMicrotask(() => setDetailLoading(true));
    fetch(`/api/companies/${encodeURIComponent(selectedId)}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<CompanyDetailResponse>; })
      .then(setDetail).finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selectedId]);

  const tabs = useMemo(() => [
    { key: "EVENTS" as const, label: "이벤트", count: detail?.counts.events ?? 0 },
    { key: "ASSETS" as const, label: "자산", count: detail?.counts.assets ?? 0 },
    { key: "DOCUMENTS" as const, label: "문서", count: detail?.counts.documents ?? 0 },
    { key: "OCCUPANCIES" as const, label: "점유", count: detail?.counts.occupancies ?? 0 },
  ], [detail]);

  return <section className="domain-workspace company-workspace">
    <header className="workspace-hero">
      <div><p className="eyebrow">COMPANY &amp; TENANT INTELLIGENCE</p><h2>기업 수요와 부동산 노출</h2><p>시가총액·업종 universe와 임차·이전 근거를 같은 회사 identity로 연결합니다.</p></div>
      <div className="hero-stat"><span>KRX 기준일</span><strong>{data?.snapshotDate ?? "-"}</strong></div>
    </header>

    <nav className="subtabs" aria-label="기업 분석 방식">
      {viewLabels.map((item) => <button key={item.key} type="button" aria-pressed={view === item.key} onClick={() => { setView(item.key); setIndustry(""); }}><strong>{item.label}</strong><span>{item.description}</span></button>)}
    </nav>

    <section className="detail-filters" aria-label="기업 상세 필터">
      <div><p className="eyebrow">FILTER</p><h3>상세 필터</h3></div>
      <label>회사 검색<input value={q} onChange={(event) => setQ(event.target.value)} placeholder="회사명 또는 종목코드" /></label>
      <label>업종<select value={industry} onChange={(event) => setIndustry(event.target.value)}><option value="">전체 업종</option>{data?.industries.map((item) => <option key={item.name} value={item.name}>{item.name} ({item.count})</option>)}</select></label>
    </section>

    {view === "TENANT_SIGNALS" && <div className="evidence-banner"><strong>근거 구분</strong><p>확정 임차는 승인된 점유관계만 집계합니다. 문서 신호는 LEASE category 제목·snippet의 회사명 직접 언급이며 계약 확정으로 간주하지 않습니다.</p><span>확정 점유 {data?.coverage.verifiedOccupancies ?? 0}건 · 문서 신호 기업 {data?.coverage.companiesWithLeaseDocumentSignals ?? 0}개</span></div>}

    {loading && <div className="state-block"><span className="spinner"/><strong>기업 universe 조회 중</strong></div>}
    {!loading && error && <div className="state-block error-state"><strong>기업정보 조회 오류</strong><p>Supabase 연결을 확인해 주세요.</p></div>}
    {!loading && !error && <div className="company-table-wrap"><table className="company-table"><thead><tr><th>순위</th><th>회사</th><th>업종</th><th>시가총액</th><th>확정 점유</th><th>관련 이벤트·자산</th><th>LEASE 문서 신호</th></tr></thead><tbody>{data?.items.map((item) => <tr key={item.organizationId}><td>{view === "INDUSTRY" ? item.industryRank ?? "-" : item.overallRank ?? "-"}</td><td><button type="button" className="company-link" onClick={() => { setDetail(null); setSelectedId(item.organizationId); setDetailTab("EVENTS"); }}><strong>{item.name}</strong><span>{item.stockCode ?? "비상장·코드없음"}</span></button></td><td>{item.industry ?? "미분류"}</td><td><strong>{marketCap(item.marketCap)}</strong></td><td>{item.confirmedOccupancyCount}</td><td>{item.canonicalEventCount} / {item.relatedAssetCount}</td><td>{item.leaseDocumentSignalCount}</td></tr>)}</tbody></table></div>}

    {selectedId && <div className="drawer-layer" onMouseDown={(event) => { if (event.currentTarget === event.target) { setSelectedId(null); setDetail(null); } }}><section className="detail-drawer company-drawer" role="dialog" aria-modal="true" aria-label="회사 360 상세"><header className="drawer-header"><div><p className="eyebrow">COMPANY 360</p><h2>{detail?.organization.name ?? "회사정보 로딩"}</h2>{detail && <p>{detail.organization.industry ?? detail.organization.organizationType} · {marketCap(detail.organization.marketCap)}</p>}</div><button type="button" className="icon-button" aria-label="상세 닫기" onClick={() => { setSelectedId(null); setDetail(null); }}>×</button></header>{detailLoading && <div className="state-block"><span className="spinner"/><strong>관계정보 조회 중</strong></div>}{detail && <><section className="domain-narrative company-narrative"><p className="eyebrow">STRUCTURED SUMMARY</p><h3>회사 핵심 설명</h3><p>{companyNarrative(detail)}</p></section><nav className="drawer-tabs">{tabs.map((tab) => <button key={tab.key} type="button" aria-pressed={detailTab === tab.key} onClick={() => setDetailTab(tab.key)}>{tab.label}<b>{tab.count}</b></button>)}</nav><div className="drawer-body relation-sections">
      {detailTab === "EVENTS" && (detail.events.length ? detail.events.map((item, index) => <article key={String(item.event_id ?? index)}><strong>{String(item.title ?? "이벤트")}</strong><p>{recordText(item, ["category", "role_code", "stage", "date", "status", "verification"])}</p></article>) : <p className="empty-copy">직접 연결된 canonical event가 없습니다.</p>)}
      {detailTab === "ASSETS" && (detail.assets.length ? detail.assets.map((item, index) => <article key={String(item.asset_id ?? index)}><strong>{String(item.name ?? "자산")}</strong><p>{recordText(item, ["asset_class", "address"])}</p></article>) : <p className="empty-copy">직접 연결된 자산이 없습니다.</p>)}
      {detailTab === "DOCUMENTS" && (detail.documents.length ? detail.documents.map((item) => <article key={item.documentId}><span className={`relation-basis ${item.relationBasis.toLowerCase()}`}>{item.relationBasis === "CANONICAL_EVENT" ? "정규관계" : "이름언급 신호"}</span><strong>{item.title}</strong><p>{[item.documentType,item.publisher,item.publishedAt?.slice(0,10)].filter(Boolean).join(" · ")}</p>{item.href && <a href={item.href} target="_blank" rel="noreferrer">원문 열기</a>}</article>) : <p className="empty-copy">연결 또는 이름언급 문서가 없습니다.</p>)}
      {detailTab === "OCCUPANCIES" && (detail.occupancies.length ? detail.occupancies.map((item, index) => <article key={String(item.occupancy_id ?? index)}><strong>{recordText(item,["occupancy_type","tenure_type","occupancy_status"])}</strong><p>{recordText(item,["valid_from","valid_to","verification_status","review_status"])}</p></article>) : <p className="empty-copy">승인된 점유관계가 아직 없습니다.</p>)}
    </div></>}</section></div>}
  </section>;
}
