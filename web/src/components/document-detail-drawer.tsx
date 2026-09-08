"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { DocumentDetail } from "@/lib/server/document-intelligence";
import { TransactionDetail } from "@/components/transaction-template";
import { documentTemplateKey, viewTemplates } from "@/lib/view-template-registry";

type Props = { documentId: string; fallbackTitle: string; onClose: () => void };
const REQUEST_TIMEOUT_MS = 10_000;

const relationKindLabels: Record<string, string> = {
  EVENT: "이벤트", ASSET: "자산", ORGANIZATION: "기업·기관", PROJECT: "프로젝트",
  LP_MANDATE: "기관자금 프로그램", SALE_PROCESS: "매각 절차",
};
const relationBasisLabels: Record<string, string> = {
  CANONICAL_EVENT: "확정 이벤트", RESOLVED_MENTION: "이름 식별 완료",
  VERIFIED_CLAIM: "근거 검증 완료", SOURCE_CLAIM: "원문 근거",
};
const eventStatusLabels: Record<string, string> = {
  APPROVED: "검토 완료", CONFIRMED: "검토 완료", VERIFIED: "검토 완료",
  REVIEW_READY: "검토 대기", CANDIDATE: "자동 추출·검토 전", PENDING: "자동 추출·검토 전",
};
const rightsStatusLabels: Record<string, string> = {
  EXCERPT_ALLOWED: "제한 발췌 허용", FULL_TEXT_ALLOWED: "전문 저장 허용",
  LINK_ONLY: "원문 링크만 제공", RESTRICTED: "저장 제한",
};

const kstDateFormatter = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
});
const kstDateTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

function formatKstTimestamp(value: string, includeTime = false) {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  const parts = Object.fromEntries(
    (includeTime ? kstDateTimeFormatter : kstDateFormatter)
      .formatToParts(timestamp)
      .map((part) => [part.type, part.value]),
  );
  const date = `${parts.year}-${parts.month}-${parts.day}`;
  return includeTime ? `${date} ${parts.hour}:${parts.minute} KST` : date;
}

const normalizedText = (value: string | null | undefined) => value
  ?.normalize("NFKC")
  .toLocaleLowerCase("ko-KR")
  .replace(/[^\p{L}\p{N}]+/gu, "") ?? "";

function comparableText(value: string | null | undefined, publisher: string | null) {
  const compact = normalizedText(value);
  const compactPublisher = normalizedText(publisher);
  return compactPublisher && compact.endsWith(compactPublisher)
    ? compact.slice(0, -compactPublisher.length)
    : compact;
}

function samePresentationText(left: string | null | undefined, right: string | null | undefined, publisher: string | null) {
  const normalizedLeft = comparableText(left, publisher);
  return Boolean(normalizedLeft) && normalizedLeft === comparableText(right, publisher);
}

function displayTitle(title: string, publisher: string | null) {
  if (!publisher) return title;
  const escapedPublisher = publisher.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return title.replace(new RegExp(`\\s*[-–—|·]\\s*${escapedPublisher}\\s*$`, "iu"), "").trim();
}

export function DocumentDetailDrawer({ documentId, fallbackTitle, onClose }: Props) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<"TIMEOUT" | "REQUEST" | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useLayoutEffect(() => {
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
      if (event.key !== "Tab") return;
      const focusable = [...(drawerRef.current?.querySelectorAll<HTMLElement>("button:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])") ?? [])];
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable.at(-1) as HTMLElement;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
      if (returnFocus?.isConnected) returnFocus.focus();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
    fetch(`/api/documents/${encodeURIComponent(documentId)}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<DocumentDetail>; })
      .then((value) => {
        if (!disposed) {
          setDetail(value);
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        if (timedOut) setError("TIMEOUT");
        else if (!(reason instanceof DOMException && reason.name === "AbortError")) setError("REQUEST");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [documentId, retryKey]);

  const modeLabel = detail?.contentMode === "FULL_TEXT" ? "저장 본문" : detail?.contentMode === "SAFE_EXCERPT" ? "본문 추출·제한 발췌" : detail?.contentMode === "SNIPPET" ? "출처 발췌" : "메타데이터만";
  const summaryLabel = detail?.summaryMode === "MODEL" ? "검토 전 생성 요약" : detail?.summaryMode === "BODY_EXTRACTIVE" ? "본문 추출 요약" : detail?.summaryMode === "EVENT_EXTRACTION" ? "이벤트 추출 요약" : detail?.summaryMode === "SOURCE_SNIPPET" ? "출처 발췌" : "요약 없음";
  const template = detail ? viewTemplates[documentTemplateKey(detail.documentType, Boolean(detail.transaction))] : viewTemplates.ARTICLE;
  const meaningfulSummary = detail?.summary && !samePresentationText(detail.summary, detail.title, detail.publisher) ? detail.summary : null;
  const visibleSummaryLabel = meaningfulSummary ? summaryLabel : "요약 없음";
  const rightsLabel = detail?.rightsStatus ? rightsStatusLabels[detail.rightsStatus] ?? "권리상태 확인 필요" : "미분류";

  return <div className="drawer-layer" onMouseDown={(event) => event.currentTarget === event.target && onClose()}>
    <section ref={drawerRef} className="detail-drawer document-drawer" role="dialog" aria-modal="true" aria-label="문서 상세">
      <header className="drawer-header"><div><p className="eyebrow">{template.eyebrow}</p><h2>{detail ? displayTitle(detail.title, detail.publisher) : fallbackTitle}</h2><p>{detail ? `${detail.publisher ?? "출처 미상"} · ${template.title}` : "문서 근거 조회 중"}</p></div><button ref={closeRef} type="button" className="icon-button" aria-label="상세 닫기" onClick={onClose}>×</button></header>
      {!detail && !error && <div className="state-block"><span className="spinner"/><strong>요약·키워드·근거 조회 중</strong></div>}
      {error && <div className="state-block error-state" role="alert"><strong>{error === "TIMEOUT" ? "문서 상세 조회 시간이 초과되었습니다." : "문서 상세를 불러오지 못했습니다."}</strong><button type="button" onClick={() => setRetryKey((value) => value + 1)}>다시 조회</button></div>}
      {detail && <div className="drawer-body document-body">
        <div className="document-actions"><span className={`content-mode ${detail.contentMode.toLowerCase()}`}>{detail.transaction ? "실거래 원자료" : modeLabel}</span>{detail.transaction?.dealDate ? <time dateTime={detail.transaction.dealDate}>{detail.transaction.dealDate}</time> : detail.publishedAt && <time dateTime={detail.publishedAt}>게시 {formatKstTimestamp(detail.publishedAt)}</time>}{detail.sourceUrl && <a className="primary-link" href={detail.sourceUrl} target="_blank" rel="noreferrer">{template.sourceLabel} ↗</a>}</div>
        {detail.transaction ? <TransactionDetail transaction={detail.transaction}/> : <section className="knowledge-section"><p className="eyebrow">{visibleSummaryLabel}</p><h3>{template.key === "DISCLOSURE" ? "공시 핵심내용" : template.key === "OFFICIAL_NOTICE" ? "공고 핵심내용" : "기사 핵심내용"}</h3><p className={`document-summary${meaningfulSummary ? "" : " empty"}`}>{meaningfulSummary ?? "본문 요약 없음 · 원문에서 확인"}</p>{meaningfulSummary && detail.summaryGeneratedAt && <small className="summary-provenance">생성 {formatKstTimestamp(detail.summaryGeneratedAt, true)} · {detail.summaryPipeline}</small>}</section>}
        {detail.keywords.length > 0 && <section className="knowledge-section"><p className="eyebrow">KEYWORDS</p><h3>추출 키워드</h3><div className="keyword-cloud">{detail.keywords.map((item) => <span key={`${item.type}-${item.value}`}><small>{item.label}</small>{item.value}</span>)}</div></section>}
        {(detail.relatedEntities?.length ?? 0) > 0 && <section className="knowledge-section"><p className="eyebrow">TYPED RELATIONS</p><h3>관련 기업·자산·이벤트</h3><div className="event-signal-list">{detail.relatedEntities.map((item) => <article key={`${item.kind}-${item.id}`}><div><span className="category-badge">{relationKindLabels[item.kind] ?? item.kind}</span>{item.confidence != null && <small>신뢰도 {Math.round(item.confidence * 100)}%</small>}</div><strong>{item.title}</strong><p>{relationBasisLabels[item.relationBasis] ?? item.relationBasis} · {item.relationRole}</p><small>근거 상태 {item.evidenceStatus}</small></article>)}</div></section>}
        {detail.eventSignals.length > 0 && <section className="knowledge-section"><p className="eyebrow">자동 추출 이벤트</p><h3>연결 가능한 이벤트</h3><div className="event-signal-list">{detail.eventSignals.map((item, index) => {
          const eventTitle = item.title && !samePresentationText(item.title, detail.title, detail.publisher) ? item.title : null;
          const eventSummary = item.summary
            && !samePresentationText(item.summary, detail.title, detail.publisher)
            && !samePresentationText(item.summary, eventTitle, detail.publisher)
            ? item.summary
            : null;
          const statusLabel = eventStatusLabels[item.status] ?? "자동 추출·검토 전";
          const categoryLabel = item.categoryLabel ?? item.category;
          const facts = [item.stage && !samePresentationText(item.stage, categoryLabel, null) ? item.stage : null, item.eventDate].filter(Boolean);
          return <article key={`${item.category}-${index}`}><div><span className="category-badge">{categoryLabel}</span><small className="event-review-status">{statusLabel}{item.confidence != null ? ` · 신뢰도 ${Math.round(item.confidence * 100)}%` : ""}</small></div>{eventTitle && <strong>{eventTitle}</strong>}{eventSummary && <p>{eventSummary}</p>}{facts.length > 0 && <small>{facts.join(" · ")}</small>}</article>;
        })}</div></section>}
        {!detail.transaction && detail.safeExcerpt && <section className="knowledge-section"><p className="eyebrow">SAFE EXCERPT</p><h3>제한 발췌</h3><p className="document-excerpt">{detail.safeExcerpt}</p></section>}
        {!detail.transaction && detail.storedText && <section className="knowledge-section"><p className="eyebrow">STORED TEXT</p><h3>저장 본문</h3><div className="stored-text">{detail.storedText}</div></section>}
        {!detail.transaction && !detail.safeExcerpt && !detail.storedText && detail.snippet && !samePresentationText(detail.snippet, detail.title, detail.publisher) && !samePresentationText(detail.snippet, meaningfulSummary, detail.publisher) && <section className="knowledge-section"><p className="eyebrow">출처 발췌</p><h3>출처 제공 텍스트</h3><p className="document-excerpt">{detail.snippet}</p></section>}
        <footer className="document-rights">{detail.transaction ? "국토교통부 실거래가 공개시스템 원자료 · 면적 기준 판정은 개별 거래 기준 · 거래군 합산은 별도 검토" : `저장 범위: ${modeLabel} · 요약 근거: ${visibleSummaryLabel} · 권리상태: ${rightsLabel} · 전문이 저장되지 않은 기사는 원문 링크에서 확인`}</footer>
      </div>}
    </section>
  </div>;
}
