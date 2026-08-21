"use client";

import { useEffect, useState } from "react";
import type { DocumentDetail } from "@/lib/server/document-intelligence";
import { TransactionDetail } from "@/components/transaction-template";
import { documentTemplateKey, viewTemplates } from "@/lib/view-template-registry";

type Props = { documentId: string; fallbackTitle: string; onClose: () => void };

const relationKindLabels: Record<string, string> = {
  EVENT: "이벤트", ASSET: "자산", ORGANIZATION: "기업·기관", PROJECT: "프로젝트",
  LP_MANDATE: "기관자금 프로그램", SALE_PROCESS: "매각 절차",
};
const relationBasisLabels: Record<string, string> = {
  CANONICAL_EVENT: "확정 이벤트", RESOLVED_MENTION: "식별 완료 mention",
  VERIFIED_CLAIM: "검증 claim", SOURCE_CLAIM: "원천 claim",
};

export function DocumentDetailDrawer({ documentId, fallbackTitle, onClose }: Props) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/documents/${encodeURIComponent(documentId)}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<DocumentDetail>; })
      .then(setDetail)
      .catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); });
    return () => controller.abort();
  }, [documentId]);

  const modeLabel = detail?.contentMode === "FULL_TEXT" ? "저장 본문" : detail?.contentMode === "SAFE_EXCERPT" ? "본문 추출·제한 발췌" : detail?.contentMode === "SNIPPET" ? "출처 snippet" : "메타데이터만";
  const summaryLabel = detail?.summaryMode === "MODEL" ? "검토 전 생성 요약" : detail?.summaryMode === "BODY_EXTRACTIVE" ? "본문 추출 요약" : detail?.summaryMode === "EVENT_EXTRACTION" ? "이벤트 추출 요약" : detail?.summaryMode === "SOURCE_SNIPPET" ? "출처 제공 snippet" : "요약 미생성";
  const template = detail ? viewTemplates[documentTemplateKey(detail.documentType, Boolean(detail.transaction))] : viewTemplates.ARTICLE;

  return <div className="drawer-layer" onMouseDown={(event) => event.currentTarget === event.target && onClose()}>
    <section className="detail-drawer document-drawer" role="dialog" aria-modal="true" aria-label="문서 상세">
      <header className="drawer-header"><div><p className="eyebrow">{template.eyebrow}</p><h2>{detail?.title ?? fallbackTitle}</h2><p>{detail ? `${template.title} · ${detail.publisher ?? "출처 미상"} · ${template.purpose}` : "문서 지식정보 조회 중"}</p></div><button type="button" className="icon-button" aria-label="상세 닫기" onClick={onClose}>×</button></header>
      {!detail && !error && <div className="state-block"><span className="spinner"/><strong>요약·키워드·근거 조회 중</strong></div>}
      {error && <div className="state-block error-state"><strong>문서 상세를 불러오지 못했습니다.</strong></div>}
      {detail && <div className="drawer-body document-body">
        <div className="document-actions"><span className={`content-mode ${detail.contentMode.toLowerCase()}`}>{detail.transaction ? "실거래 원자료" : modeLabel}</span>{(detail.transaction?.dealDate ?? detail.publishedAt) && <time>{(detail.transaction?.dealDate ?? detail.publishedAt)?.slice(0,10)}</time>}{detail.sourceUrl && <a className="primary-link" href={detail.sourceUrl} target="_blank" rel="noreferrer">{template.sourceLabel} ↗</a>}</div>
        {detail.transaction ? <TransactionDetail transaction={detail.transaction}/> : <section className="knowledge-section"><p className="eyebrow">SUMMARY · {summaryLabel}</p><h3>{template.key === "DISCLOSURE" ? "공시 핵심내용" : template.key === "OFFICIAL_NOTICE" ? "공고 핵심내용" : "기사 핵심내용"}</h3><p className="document-summary">{detail.summary ?? "본문이나 충분한 출처 텍스트가 확보되지 않아 요약을 생성하지 않았습니다."}</p>{detail.summaryGeneratedAt && <small className="summary-provenance">생성 {detail.summaryGeneratedAt.slice(0,16).replace("T"," ")} · {detail.summaryPipeline}</small>}</section>}
        {detail.keywords.length > 0 && <section className="knowledge-section"><p className="eyebrow">KEYWORDS</p><h3>추출 키워드</h3><div className="keyword-cloud">{detail.keywords.map((item) => <span key={`${item.type}-${item.value}`}><small>{item.label}</small>{item.value}</span>)}</div></section>}
        {(detail.relatedEntities?.length ?? 0) > 0 && <section className="knowledge-section"><p className="eyebrow">TYPED RELATIONS</p><h3>관련 기업·자산·이벤트</h3><div className="event-signal-list">{detail.relatedEntities.map((item) => <article key={`${item.kind}-${item.id}`}><div><span className="category-badge">{relationKindLabels[item.kind] ?? item.kind}</span>{item.confidence != null && <small>신뢰도 {Math.round(item.confidence * 100)}%</small>}</div><strong>{item.title}</strong><p>{relationBasisLabels[item.relationBasis] ?? item.relationBasis} · {item.relationRole}</p><small>근거 상태 {item.evidenceStatus}</small></article>)}</div></section>}
        {detail.eventSignals.length > 0 && <section className="knowledge-section"><p className="eyebrow">EVENT SIGNALS</p><h3>연결 가능한 이벤트</h3><div className="event-signal-list">{detail.eventSignals.map((item, index) => <article key={`${item.category}-${index}`}><div><span className="category-badge">{item.categoryLabel ?? item.category}</span>{item.confidence != null && <small>신뢰도 {Math.round(item.confidence * 100)}%</small>}</div><strong>{item.title ?? item.summary ?? "제목 미상"}</strong>{item.summary && item.summary !== item.title && <p>{item.summary}</p>}<small>{[item.stage,item.eventDate,item.status].filter(Boolean).join(" · ")}</small></article>)}</div></section>}
        {!detail.transaction && detail.safeExcerpt && <section className="knowledge-section"><p className="eyebrow">SAFE EXCERPT</p><h3>제한 발췌</h3><p className="document-excerpt">{detail.safeExcerpt}</p></section>}
        {!detail.transaction && detail.storedText && <section className="knowledge-section"><p className="eyebrow">STORED TEXT</p><h3>저장 본문</h3><div className="stored-text">{detail.storedText}</div></section>}
        {!detail.transaction && !detail.safeExcerpt && !detail.storedText && detail.snippet && detail.snippet !== detail.summary && <section className="knowledge-section"><p className="eyebrow">SOURCE SNIPPET</p><h3>출처 제공 텍스트</h3><p className="document-excerpt">{detail.snippet}</p></section>}
        <footer className="document-rights">{detail.transaction ? "국토교통부 실거래가 공개시스템 원자료 · 면적 기준 판정은 개별 거래 기준 · 거래군 합산은 별도 검토" : `저장 범위: ${modeLabel} · 요약 근거: ${summaryLabel} · 권리상태: ${detail.rightsStatus ?? "미분류"} · 전문이 저장되지 않은 기사는 원문 링크에서 확인`}</footer>
      </div>}
    </section>
  </div>;
}
