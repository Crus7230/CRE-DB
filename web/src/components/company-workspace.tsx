"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  CompanyDetailResponse,
  CompanyListItem,
  CompanyListResponse,
  CompanyView,
  LocationEvidence,
} from "@/lib/intelligence-contract";

type DetailTab = "LOCATION_EVIDENCE" | "EVENTS" | "ASSETS" | "DOCUMENTS" | "OCCUPANCIES";
const COMPANY_SEARCH_DEBOUNCE_MS = 400;

const viewLabels: Array<{ key: CompanyView; label: string; description: string }> = [
  { key: "OVERALL", label: "시가총액 상위 50", description: "2026-07-31 KRX 공식 snapshot" },
  { key: "INDUSTRY", label: "업종별 상위 10", description: "KIND 업종별 시가총액 순위" },
  { key: "TENANT_SIGNALS", label: "입지 관련 근거", description: "행동 표현·근거 문장 확인" },
];

const wordingLabels = {
  CONFIRMED_WORDING: "확정 표현",
  IN_PROGRESS_WORDING: "추진 표현",
  EXPLORING_WORDING: "검토·타진 표현",
  REVIEW_REQUIRED: "문맥 검토",
} as const;

function marketCap(value: string | null) {
  if (!value) return "-";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  if (amount >= 1e12) return `${(amount / 1e12).toFixed(1)}조원`;
  return `${Math.round(amount / 1e8).toLocaleString("ko-KR")}억원`;
}

function displayDate(value: string | null) {
  if (!value) return "시점 미확인";
  return value.slice(0, 10).replaceAll("-", ".");
}

function recordText(record: Record<string, string | number | null>, keys: string[]) {
  return keys.map((key) => record[key]).filter((value) => value !== null && value !== undefined && value !== "").join(" · ");
}

function reviewLabel(evidence: LocationEvidence) {
  if (evidence.classificationBasis === "MANAGED_TAXONOMY") {
    if (evidence.classificationReviewStatus === "APPROVED") return "관리형 분류 승인";
    return "관리형 분류 검토 중";
  }
  if (evidence.mentionStatus === "APPROVED") return "추출 승인";
  if (evidence.mentionStatus === "REVIEW_READY") return "검토 대기";
  return "자동 추출·검토 전";
}

function readableEvidence(value: string | null) {
  if (!value) return null;
  const compact = value.replace(/\s+/g, " ").trim();
  if (!compact.startsWith("{")) return compact.length > 260 ? `${compact.slice(0, 257)}…` : compact;
  try {
    const parsed = JSON.parse(compact) as Record<string, unknown>;
    const roles = parsed.roles && typeof parsed.roles === "object" ? parsed.roles as Record<string, unknown> : {};
    const parts = [
      typeof parsed.asset === "string" ? `대상 ${parsed.asset}` : null,
      typeof parsed.current_status === "string" ? `현재 상태 ${parsed.current_status}` : null,
      typeof parsed.status === "string" ? `상태 ${parsed.status}` : null,
      typeof parsed.stage === "string" ? `단계 ${parsed.stage}` : null,
      typeof parsed.tenant === "string" ? `임차인 ${parsed.tenant}` : null,
      typeof roles.tenant === "string" ? `임차인 ${roles.tenant}` : null,
    ].filter(Boolean);
    return parts.length ? parts.join(" · ") : null;
  } catch {
    return null;
  }
}

function companyNarrative(detail: CompanyDetailResponse): string {
  const rank = detail.organization.overallRank ? `시가총액 전체 ${detail.organization.overallRank}위` : "시가총액 순위 미확인";
  return `${detail.organization.name}은 ${detail.organization.industry ?? detail.organization.organizationType} 분류의 회사로 ${rank}, 기준 시가총액은 ${marketCap(detail.organization.marketCap)}입니다. 정규 이벤트 ${detail.counts.events}건, 관련 자산 ${detail.counts.assets}건, 연결 문서 ${detail.counts.documents}건, 승인·검증 점유관계 ${detail.counts.occupancies}건이 확인됩니다.`;
}

function relationLabel(value: string) {
  if (value === "CANONICAL_EVENT") return "정규 이벤트";
  if (value === "RESOLVED_MENTION") return "회사관계 해소";
  if (value === "VERIFIED_CLAIM") return "검증된 주장";
  if (value === "SOURCE_CLAIM") return "원천 주장";
  return "입지문서 이름 일치";
}

function EvidenceBadges({ evidence }: { evidence: LocationEvidence }) {
  return <div className="location-evidence-badges">
    <span className={`location-type type-${evidence.evidenceType.toLowerCase()}`}>{evidence.evidenceLabel}</span>
    <span className={`wording-stage stage-${evidence.wordingStage.toLowerCase()}`}>{wordingLabels[evidence.wordingStage]}</span>
    <span className="review-state">{reviewLabel(evidence)}</span>
  </div>;
}

function LocationEvidenceRow({
  item,
  onOpen,
}: {
  item: CompanyListItem;
  onOpen: () => void;
}) {
  const evidence = item.primaryLocationEvidence;
  return <tr>
    <td>
      <button type="button" className="company-link" onClick={onOpen}>
        <strong>{item.name}</strong>
        <span>{item.industry ?? "미분류"} · {item.stockCode ?? "코드 없음"}</span>
      </button>
    </td>
    <td>
      {item.confirmedOccupancyCount > 0 && <span className="confirmed-occupancy">확정 점유 {item.confirmedOccupancyCount}</span>}
      {evidence ? <EvidenceBadges evidence={evidence} /> : <span className="muted-copy">문서 근거 없음</span>}
    </td>
    <td className="evidence-headline">
      {evidence && <>
        <strong>{evidence.title}</strong>
        <span>{evidence.matchedPhrase ? `감지 표현 ‘${evidence.matchedPhrase}’` : "행동 표현 문맥 일치"}</span>
      </>}
    </td>
    <td className="evidence-reason">{evidence?.evidenceReason ?? "승인·검증된 점유관계"}</td>
    <td className="evidence-source">
      {evidence && <><strong>{evidence.publisher ?? "출처 미확인"}</strong><span>{displayDate(evidence.publishedAt)}</span></>}
    </td>
    <td>
      <button type="button" className="evidence-count-button" onClick={onOpen}>
        <strong>{item.locationEvidenceDocumentCount}건 보기</strong>
        <span>{item.locationEvidencePublisherCount}개 매체</span>
      </button>
    </td>
  </tr>;
}

export function CompanyWorkspace({ initialCompanyId = null }: { initialCompanyId?: string | null }) {
  const [view, setView] = useState<CompanyView>("OVERALL");
  const [industry, setIndustry] = useState("");
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [data, setData] = useState<CompanyListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(initialCompanyId);
  const [detail, setDetail] = useState<CompanyDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>("EVENTS");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(q.trim()), COMPANY_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ view, industry, q: debouncedQ, limit: view === "OVERALL" ? "50" : "100" });
    queueMicrotask(() => { setLoading(true); setError(false); });
    fetch(`/api/companies?${params}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<CompanyListResponse>; })
      .then(setData)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [view, industry, debouncedQ]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    queueMicrotask(() => setDetailLoading(true));
    fetch(`/api/companies/${encodeURIComponent(selectedId)}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<CompanyDetailResponse>; })
      .then(setDetail)
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selectedId]);

  const tabs = useMemo(() => [
    { key: "LOCATION_EVIDENCE" as const, label: "입지 근거", count: detail?.counts.locationEvidence ?? 0 },
    { key: "EVENTS" as const, label: "정규 이벤트", count: detail?.counts.events ?? 0 },
    { key: "ASSETS" as const, label: "자산", count: detail?.counts.assets ?? 0 },
    { key: "DOCUMENTS" as const, label: "전체 문서", count: detail?.counts.documents ?? 0 },
    { key: "OCCUPANCIES" as const, label: "확정 점유", count: detail?.counts.occupancies ?? 0 },
  ], [detail]);

  function openCompany(organizationId: string) {
    setDetail(null);
    setSelectedId(organizationId);
    setDetailTab(view === "TENANT_SIGNALS" ? "LOCATION_EVIDENCE" : "EVENTS");
  }

  return <section className="domain-workspace company-workspace">
    <header className="workspace-hero">
      <div>
        <p className="eyebrow">COMPANY &amp; TENANT INTELLIGENCE</p>
        <h2>기업 수요와 부동산 노출</h2>
        <p>시가총액·업종 universe와 임차·이전 근거를 같은 회사 identity로 연결합니다.</p>
      </div>
      <div className="hero-stat"><span>KRX 기준일</span><strong>{data?.snapshotDate ?? "-"}</strong></div>
    </header>

    <nav className="subtabs" aria-label="기업 분석 방식">
      {viewLabels.map((item) => <button
        key={item.key}
        type="button"
        aria-pressed={view === item.key}
        onClick={() => { setView(item.key); setIndustry(""); }}
      ><strong>{item.label}</strong><span>{item.description}</span></button>)}
    </nav>

    <section className="detail-filters" aria-label="기업 상세 필터">
      <div><p className="eyebrow">FILTER</p><h3>상세 필터</h3></div>
      <label>회사 검색<input value={q} onChange={(event) => setQ(event.target.value)} placeholder="회사명 또는 종목코드" /></label>
      <label>업종<select value={industry} onChange={(event) => setIndustry(event.target.value)}>
        <option value="">전체 업종</option>
        {data?.industries.map((item) => <option key={item.name} value={item.name}>{item.name} ({item.count})</option>)}
      </select></label>
    </section>

    {view === "TENANT_SIGNALS" && <div className="evidence-banner location-evidence-guide">
      <strong>이 화면을 읽는 법</strong>
      <p>‘확정 점유’와 ‘관련 보도’를 분리했습니다. 관련 보도 수는 독립된 이전 사건 수가 아니며, 제목·요약에서 회사명과 입지 행동 표현이 함께 잡힌 검토 자료입니다.</p>
      <span>확정 점유 {data?.coverage.verifiedOccupancies ?? 0}건 · 관련 근거 기업 {data?.coverage.companiesWithLocationEvidence ?? 0}개 · 관리형 분류 문서 {data?.coverage.managedLocationDocuments ?? 0}건</span>
    </div>}

    {loading && <div className="state-block"><span className="spinner"/><strong>기업 universe 조회 중</strong></div>}
    {!loading && error && <div className="state-block error-state"><strong>기업정보 조회 오류</strong><p>Turso 연결을 확인해 주세요.</p></div>}
    {!loading && !error && view === "TENANT_SIGNALS" && <div className="company-table-wrap location-evidence-table-wrap">
      <table className="company-table location-evidence-table">
        <thead><tr><th>회사</th><th>자동 문서 판정</th><th>문서에서 잡힌 내용</th><th>왜 포함됐나</th><th>출처·시점</th><th>관련 보도</th></tr></thead>
        <tbody>
          {data?.items.map((item) => <LocationEvidenceRow key={item.organizationId} item={item} onOpen={() => openCompany(item.organizationId)} />)}
        </tbody>
      </table>
      {!data?.items.length && <div className="table-empty"><strong>조건에 맞는 입지 관련 근거가 없습니다.</strong><p>확정 점유와 행동 표현이 확인된 문서만 노출합니다.</p></div>}
    </div>}
    {!loading && !error && view !== "TENANT_SIGNALS" && <div className="company-table-wrap">
      <table className="company-table">
        <thead><tr><th>순위</th><th>회사</th><th>업종</th><th>시가총액</th><th>확정 점유</th><th>관련 이벤트·자산</th><th>입지 관련 문서</th></tr></thead>
        <tbody>{data?.items.map((item) => <tr key={item.organizationId}>
          <td>{view === "INDUSTRY" ? item.industryRank ?? "-" : item.overallRank ?? "-"}</td>
          <td><button type="button" className="company-link" onClick={() => openCompany(item.organizationId)}><strong>{item.name}</strong><span>{item.stockCode ?? "비상장·코드없음"}</span></button></td>
          <td>{item.industry ?? "미분류"}</td>
          <td><strong>{marketCap(item.marketCap)}</strong></td>
          <td>{item.confirmedOccupancyCount}</td>
          <td>{item.canonicalEventCount} / {item.relatedAssetCount}</td>
          <td>{item.locationEvidenceDocumentCount}</td>
        </tr>)}</tbody>
      </table>
    </div>}

    {selectedId && <div className="drawer-layer" onMouseDown={(event) => {
      if (event.currentTarget === event.target) { setSelectedId(null); setDetail(null); }
    }}>
      <section className="detail-drawer company-drawer" role="dialog" aria-modal="true" aria-label="회사 360 상세">
        <header className="drawer-header">
          <div><p className="eyebrow">COMPANY EVIDENCE</p><h2>{detail?.organization.name ?? "회사정보 로딩"}</h2>{detail && <p>{detail.organization.industry ?? detail.organization.organizationType} · {marketCap(detail.organization.marketCap)}</p>}</div>
          <button type="button" className="icon-button" aria-label="상세 닫기" onClick={() => { setSelectedId(null); setDetail(null); }}>×</button>
        </header>
        {detailLoading && <div className="state-block"><span className="spinner"/><strong>관계정보 조회 중</strong></div>}
        {detail && <>
          <section className="domain-narrative company-narrative"><p className="eyebrow">STRUCTURED SUMMARY</p><h3>회사 핵심 설명</h3><p>{companyNarrative(detail)}</p></section>
          <nav className="drawer-tabs">{tabs.map((tab) => <button key={tab.key} type="button" aria-pressed={detailTab === tab.key} onClick={() => setDetailTab(tab.key)}>{tab.label}<b>{tab.count}</b></button>)}</nav>
          <div className="drawer-body relation-sections">
            {detailTab === "LOCATION_EVIDENCE" && <section className="location-evidence-detail">
              <header><div><p className="eyebrow">WHY THIS WAS FOUND</p><h3>왜 입지 관련 근거로 잡혔나</h3></div><span>승인 점유와 별도</span></header>
              <p className="evidence-disclaimer">아래 카드는 문서 표현을 설명합니다. ‘확정 표현’도 기사의 문구 수준이며, 승인·검증된 임차계약 또는 실제 이전 확정을 뜻하지 않습니다.</p>
              {detail.locationEvidence.length > 0 && <div className="evidence-list-heading"><strong>관련 문서 시계열</strong><span>최근 근거순 · 동일 사건의 반복 보도 포함</span></div>}
              {detail.locationEvidence.length ? detail.locationEvidence.map((evidence) => {
                const excerpt = readableEvidence(evidence.evidenceExcerpt);
                return <article className="location-evidence-card" key={evidence.documentId}>
                  <EvidenceBadges evidence={evidence} />
                  <h4>{evidence.title}</h4>
                  <div className="match-explanation"><span>판정 이유</span><strong>{evidence.evidenceReason}</strong></div>
                  {evidence.matchedPhrase && <p className="matched-phrase">감지 표현 <mark>‘{evidence.matchedPhrase}’</mark></p>}
                  {excerpt && <blockquote>{excerpt}</blockquote>}
                  <footer>
                    <span>{evidence.publisher ?? "출처 미확인"} · {displayDate(evidence.publishedAt)}</span>
                    <span>{evidence.sourceCategory} · {evidence.confidence === null ? "신뢰도 미확인" : `추출 신뢰도 ${Math.round(evidence.confidence * 100)}%`}</span>
                    {evidence.href && <a href={evidence.href} target="_blank" rel="noreferrer">원문 열기</a>}
                  </footer>
                </article>;
              }) : <p className="empty-copy">행동 표현까지 확인된 입지 관련 문서가 없습니다.</p>}
            </section>}
            {detailTab === "EVENTS" && (detail.events.length ? detail.events.map((item, index) => <article key={String(item.event_id ?? index)}><strong>{String(item.title ?? "이벤트")}</strong><p>{recordText(item, ["category", "role_code", "stage", "date", "status", "verification"])}</p></article>) : <p className="empty-copy">직접 연결된 canonical event가 없습니다.</p>)}
            {detailTab === "ASSETS" && (detail.assets.length ? detail.assets.map((item, index) => <article key={String(item.asset_id ?? index)}><strong>{String(item.name ?? "자산")}</strong><p>{recordText(item, ["asset_class", "address"])}</p></article>) : <p className="empty-copy">직접 연결된 자산이 없습니다.</p>)}
            {detailTab === "DOCUMENTS" && (detail.documents.length ? detail.documents.map((item) => <article key={item.documentId}><span className={`relation-basis ${item.relationBasis.toLowerCase()}`}>{relationLabel(item.relationBasis)}</span><strong>{item.title}</strong><p>{[item.documentType,item.publisher,item.publishedAt?.slice(0,10)].filter(Boolean).join(" · ")}</p>{item.href && <a href={item.href} target="_blank" rel="noreferrer">원문 열기</a>}</article>) : <p className="empty-copy">연결된 문서가 없습니다.</p>)}
            {detailTab === "OCCUPANCIES" && (detail.occupancies.length ? detail.occupancies.map((item, index) => <article key={String(item.occupancy_id ?? index)}><strong>{recordText(item,["occupancy_type","tenure_type","occupancy_status"])}</strong><p>{recordText(item,["valid_from","valid_to","verification_status","review_status"])}</p></article>) : <p className="empty-copy">승인·검증된 점유관계가 아직 없습니다.</p>)}
          </div>
        </>}
      </section>
    </div>}
  </section>;
}
