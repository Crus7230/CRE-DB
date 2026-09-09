"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  Building2,
  CheckCircle2,
  Clock3,
  Database,
  ExternalLink,
  MapPin,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import {
  detectLookupKind,
  type LookupCandidate,
  type LookupCard,
  type LookupKind,
  type LookupResponse,
  type LookupSourceState,
  type ResolvedLookupKind,
} from "@/lib/smart-lookup-contract";
import styles from "./smart-api-search.module.css";

const REQUEST_TIMEOUT_MS = 45_000;
const SLOW_NOTICE_MS = 1_800;

const kindOptions: Array<{ key: LookupKind; label: string }> = [
  { key: "auto", label: "자동" },
  { key: "address", label: "주소" },
  { key: "company", label: "기업" },
];

const examples = ["서울특별시 강남구 테헤란로 152", "SK하이닉스", "000660"];

const sourceStatus: Record<LookupSourceState, { label: string; tone: string }> = {
  ok: { label: "정상", tone: styles.ok },
  empty: { label: "자료 없음", tone: styles.empty },
  unconfigured: { label: "연결·승인 필요", tone: styles.unconfigured },
  error: { label: "오류", tone: styles.error },
  timeout: { label: "시간 초과", tone: styles.timeout },
};

class LookupRequestError extends Error {}

type RequestSnapshot = {
  query: string;
  kind: LookupKind;
  selection?: string;
  candidate?: LookupCandidate;
};

function isLookupResponse(value: unknown): value is LookupResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Partial<LookupResponse>;
  return typeof item.query === "string"
    && (item.kind === "auto" || item.kind === "address" || item.kind === "company")
    && (item.stage === "candidates" || item.stage === "detail" || item.stage === "empty" || item.stage === "unavailable")
    && Array.isArray(item.candidates)
    && Array.isArray(item.cards)
    && Array.isArray(item.sources)
    && typeof item.queriedAt === "string";
}

function formatTimestamp(value?: string) {
  if (!value) return "시각 미상";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "시각 미상";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function safeExternalUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function fallbackRequestError(status: number) {
  if (status === 400) return "검색어나 선택한 후보를 다시 확인해 주세요.";
  if (status === 401) return "로그인이 만료되었습니다. 다시 로그인한 뒤 조회해 주세요.";
  if (status === 403) return "이 조회를 사용할 권한이 없습니다.";
  if (status === 429) return "조회가 많습니다. 잠시 기다린 뒤 다시 시도해 주세요.";
  if (status >= 500) return "조회 서비스 연결 상태를 확인해 주세요.";
  return "스마트 조회를 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

async function requestErrorMessage(response: Response) {
  try {
    const value: unknown = await response.json();
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const message = (value as { error?: unknown }).error;
      if (typeof message === "string" && message.trim() && message.length <= 180) return message.trim();
    }
  } catch {
    // Non-JSON provider responses are intentionally replaced with a safe status message.
  }
  return fallbackRequestError(response.status);
}

function kindLabel(kind: LookupKind) {
  if (kind === "address") return "주소 조회";
  if (kind === "company") return "기업 조회";
  return "자동 판별";
}

function stageLabel(stage: LookupResponse["stage"]) {
  if (stage === "candidates") return "후보 선택";
  if (stage === "detail") return "조회 완료";
  if (stage === "empty") return "결과 없음";
  return "조회 제한";
}

function ResultKindIcon({ kind }: { kind: ResolvedLookupKind | "auto" }) {
  if (kind === "address") return <MapPin aria-hidden="true" size={18}/>;
  if (kind === "company") return <Building2 aria-hidden="true" size={18}/>;
  return <Search aria-hidden="true" size={18}/>;
}

function LookupResultCard({ card }: { card: LookupCard }) {
  const isBuilding = card.presentation === "building";
  const isDisclosure = card.presentation === "disclosures";
  const highlights = isBuilding ? ["연면적", "층수", "주용도", "사용승인일"] : [];
  const technical = ["PNU", "법정동코드", "대장 구분", "지번 주소", "도로명 주소"];
  const visibleFields = isBuilding ? card.fields.filter(field => !technical.includes(field.label) && !highlights.includes(field.label)) : card.fields;
  const renderFields = (fields: LookupCard["fields"]) => <dl>{fields.map((field, index) => <div key={`${field.label}-${index}`}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>;
  return <article data-layout={card.presentation ?? "default"}>
    <header><div><small>{card.sourceLabel}</small><h3>{isBuilding && <Building2 aria-hidden="true" size={17}/>} {card.title}</h3>{card.subtitle && <p>{card.subtitle}</p>}</div>{card.asOf && <span>자료 기준 {card.asOf}</span>}</header>
    {isDisclosure ? <ol className={styles.disclosureList}>{card.fields.map((field, index) => {
      const href = card.links?.[index] ? safeExternalUrl(card.links[index].url) : null;
      return <li key={`${field.label}-${index}`}><time>{field.label}</time>{href ? <a href={href} target="_blank" rel="noreferrer">{field.value}<ExternalLink aria-hidden="true" size={13}/></a> : <span>{field.value}</span>}</li>;
    })}</ol> : <>
      {isBuilding && <div className={styles.buildingMetrics}>{highlights.map(label => {
        const field = card.fields.find(item => item.label === label);
        return field && <div key={label}><span>{field.label}</span><strong>{field.value}</strong></div>;
      })}</div>}
      {renderFields(visibleFields)}
      {isBuilding && <details className={styles.technicalDetails}><summary>주소·대장 식별정보</summary>{renderFields(card.fields.filter(field => technical.includes(field.label)))}</details>}
    </>}
    {(card.note || (!isDisclosure && card.links?.length)) && <footer>{card.note && <p>{card.note}</p>}{!isDisclosure && card.links && <div>{card.links.map(link => {
      const href = safeExternalUrl(link.url);
      return href ? <a key={`${link.label}-${href}`} href={href} target="_blank" rel="noreferrer">{link.label}<ExternalLink aria-hidden="true" size={13}/></a> : null;
    })}</div>}</footer>}
  </article>;
}

export function SmartApiSearch() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<LookupKind>("auto");
  const [response, setResponse] = useState<LookupResponse | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<LookupCandidate | null>(null);
  const [lastRequest, setLastRequest] = useState<RequestSnapshot | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [isSlow, setIsSlow] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const requestSerial = useRef(0);

  const cancelActiveRequest = () => {
    requestSerial.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
  };

  const clearResult = () => {
    cancelActiveRequest();
    setResponse(null);
    setSelectedCandidate(null);
    setLastRequest(null);
    setIsSlow(false);
    setErrorMessage("");
    setPhase("idle");
  };

  useEffect(() => () => {
    requestSerial.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  const runLookup = async (request: RequestSnapshot) => {
    const normalizedQuery = request.query.trim();
    if (!normalizedQuery) {
      setErrorMessage("주소, 회사명 또는 종목코드를 입력해 주세요.");
      setPhase("error");
      inputRef.current?.focus();
      return;
    }

    cancelActiveRequest();
    const controller = new AbortController();
    controllerRef.current = controller;
    const serial = ++requestSerial.current;
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
    const slowNotice = window.setTimeout(() => {
      if (requestSerial.current === serial && !controller.signal.aborted) setIsSlow(true);
    }, SLOW_NOTICE_MS);
    const snapshot = { ...request, query: normalizedQuery };

    setResponse(null);
    setSelectedCandidate(request.candidate ?? null);
    setLastRequest(snapshot);
    setIsSlow(false);
    setErrorMessage("");
    setPhase("loading");

    try {
      const apiResponse = await fetch("/api/lookup", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: normalizedQuery,
          kind: request.kind,
          ...(request.selection ? { selection: request.selection } : {}),
        }),
        signal: controller.signal,
      });
      if (!apiResponse.ok) throw new LookupRequestError(await requestErrorMessage(apiResponse));
      const payload: unknown = await apiResponse.json();
      if (!isLookupResponse(payload)) throw new LookupRequestError("조회 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.");
      if (requestSerial.current !== serial || controller.signal.aborted) return;
      setResponse(payload);
      setPhase("ready");
    } catch (error) {
      if (requestSerial.current !== serial) return;
      if (controller.signal.aborted && !timedOut) return;
      setErrorMessage(timedOut
        ? "전체 조회가 45초를 넘었습니다. 잠시 후 다시 시도해 주세요."
        : error instanceof LookupRequestError
          ? error.message
          : "스마트 조회를 완료하지 못했습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.");
      setPhase("error");
    } finally {
      window.clearTimeout(timeout);
      window.clearTimeout(slowNotice);
      if (requestSerial.current === serial) controllerRef.current = null;
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void runLookup({ query, kind });
  };

  const updateQuery = (value: string) => {
    if (value === query) return;
    clearResult();
    setQuery(value);
  };

  const updateKind = (value: LookupKind) => {
    if (value === kind) return;
    clearResult();
    setKind(value);
  };

  const editSearch = () => {
    clearResult();
    window.queueMicrotask(() => inputRef.current?.focus());
  };

  const detectedKind = kind === "auto" ? detectLookupKind(query) : kind;
  const partialResult = Boolean(response && ["detail", "candidates"].includes(response.stage) && response.sources.some(source => !["ok", "empty"].includes(source.status)));
  const resultKind: ResolvedLookupKind | "auto" = selectedCandidate?.kind
    ?? (response?.kind === "address" || response?.kind === "company" ? response.kind : detectedKind);

  return <section className={styles.workspace} aria-labelledby="smart-lookup-title">
    <header className={styles.intro}>
      <div>
        <p>SMART LOOKUP</p>
        <h1 id="smart-lookup-title">주소와 기업 정보를 한 번에 조회</h1>
        <span>검색을 실행한 뒤 연결된 원천별 응답 상태와 자료 기준일을 구분해 보여줍니다.</span>
      </div>
      <aside><Database aria-hidden="true" size={18}/><span><b>요청형 조회</b>입력 중에는 외부 API를 호출하지 않습니다.</span></aside>
    </header>

    <form className={styles.searchPanel} onSubmit={submit} aria-label="스마트 조회 검색">
      <div className={styles.modeRow}>
        <span>조회 유형</span>
        <div role="group" aria-label="조회 유형 선택">
          {kindOptions.map((option) => <button
            key={option.key}
            type="button"
            aria-pressed={kind === option.key}
            onClick={() => updateKind(option.key)}
          >{option.label}</button>)}
        </div>
        <small>{kind === "auto"
          ? detectedKind === "auto" ? "주소·기업 출처를 함께 확인" : `${kindLabel(detectedKind)}로 우선 판별`
          : `${kindLabel(kind)}만 확인`}</small>
      </div>

      <div className={styles.searchRow}>
        <Search aria-hidden="true" size={20}/>
        <label className={styles.visuallyHidden} htmlFor="smart-lookup-query">주소·회사명·종목코드</label>
        <input
          ref={inputRef}
          id="smart-lookup-query"
          value={query}
          onChange={(event) => updateQuery(event.target.value)}
          placeholder="주소·회사명·종목코드를 입력하세요"
          autoComplete="off"
          spellCheck={false}
        />
        {query && <button className={styles.clearQuery} type="button" aria-label="검색어 지우기" onClick={() => updateQuery("")}><X aria-hidden="true" size={16}/></button>}
        <button className={styles.submit} type="submit" disabled={!query.trim() || phase === "loading"}>{phase === "loading" ? "조회 중" : "조회"}</button>
      </div>

      <div className={styles.examples} aria-label="검색 예시">
        <span>예시</span>
        {examples.map((example) => <button type="button" key={example} onClick={() => { updateQuery(example); inputRef.current?.focus(); }}>{example}</button>)}
      </div>
    </form>

    <section className={styles.resultPanel} aria-label="스마트 조회 결과" aria-live="polite">
      {phase === "idle" && <div className={styles.idleState}>
        <Search aria-hidden="true" size={22}/>
        <div><strong>검색어를 입력하고 조회를 실행하세요.</strong><p>주소는 위치·건축물 후보, 기업은 법인·종목 후보를 먼저 확인한 뒤 상세자료로 이어집니다.</p></div>
      </div>}

      {phase === "loading" && <div className={styles.loadingState} role="status">
        <span className={styles.spinner}/>
        <div><strong>{isSlow ? "원천기관에서 확인 중입니다." : selectedCandidate ? "선택한 후보의 상세정보를 조회 중입니다." : "연결된 출처를 확인하고 있습니다."}</strong><p>{isSlow ? "공시·주소 원천은 첫 조회에 시간이 더 걸릴 수 있습니다. 최대 45초까지 기다립니다." : `${lastRequest?.query} · 각 출처를 확인합니다.`}</p></div>
        <div className={styles.loadingActions}><span className={`${styles.statusPill} ${styles.loading}`}>{isSlow ? "확인 중" : "조회 중"}</span><button type="button" onClick={clearResult}>취소</button></div>
      </div>}

      {phase === "error" && <div className={styles.errorState} role="alert">
        <AlertCircle aria-hidden="true" size={21}/>
        <div><strong>조회하지 못했습니다.</strong><p>{errorMessage}</p></div>
        {lastRequest && <button type="button" onClick={() => void runLookup(lastRequest)}><RotateCcw aria-hidden="true" size={15}/>다시 조회</button>}
      </div>}

      {phase === "ready" && response && <>
        <header className={styles.resultHeader}>
          <div className={styles.resultIdentity}><span><ResultKindIcon kind={resultKind}/></span><div><small>{kindLabel(resultKind)}</small><h2>{response.query}</h2><p><Clock3 aria-hidden="true" size={13}/>요청 완료 {formatTimestamp(response.queriedAt)}{response.cacheHit ? " · 캐시 응답" : ""}</p></div></div>
          <div className={styles.resultActions}><span>{partialResult ? "일부 확인" : stageLabel(response.stage)}</span><button type="button" onClick={editSearch}>검색어 수정</button><button type="button" aria-label="검색 결과 닫기" onClick={clearResult}><X aria-hidden="true" size={16}/></button></div>
        </header>

        {response.sources.length > 0 && <details className={styles.sources}>
          <summary><strong>출처 연결 상태</strong><span>{response.sources.map(source => <b key={source.id} className={`${styles.statusPill} ${sourceStatus[source.status].tone}`}>{source.label.replace("국토교통부 건축HUB 건축물대장", "건축물대장").replace("VWorld 주소검색 API", "주소").replace("OpenDART ", "").replace("KRX 종목 기본정보", "KRX")} · {sourceStatus[source.status].label}</b>)}</span><small>상세 보기</small></summary>
          <div>{response.sources.map((source) => {
            const status = sourceStatus[source.status];
            return <article key={source.id}>
              <span className={`${styles.sourceIcon} ${status.tone}`}>{source.status === "ok" ? <CheckCircle2 aria-hidden="true" size={16}/> : source.status === "timeout" ? <Clock3 aria-hidden="true" size={16}/> : <Database aria-hidden="true" size={16}/>}</span>
              <div><strong>{source.label}</strong><p>{source.message ?? status.label}</p><small>{source.checkedAt ? `응답 ${formatTimestamp(source.checkedAt)}` : "응답 시각 없음"}{source.asOf ? ` · 자료 기준 ${source.asOf}` : ""}</small></div>
              <b className={`${styles.statusPill} ${status.tone}`}>{status.label}</b>
            </article>;
          })}</div>
        </details>}

        {partialResult && <p className={styles.partialNote} role="status"><AlertCircle aria-hidden="true" size={14}/>{response.message ?? "일부 출처를 확인하지 못했습니다. 수신된 자료만 표시하며 출처 연결 상태에서 상세 이유를 확인할 수 있습니다."}</p>}

        {response.stage === "candidates" && <section className={styles.candidates} aria-labelledby="lookup-candidate-title">
          <header><div><strong id="lookup-candidate-title">조회 대상을 선택하세요.</strong><p>동명이인·유사 주소를 구분한 뒤에만 상세 출처를 호출합니다.</p></div><span>{response.candidates.length}개 후보</span></header>
          <div>{response.candidates.map((candidate) => <button type="button" key={candidate.id} onClick={() => void runLookup({ query: response.query, kind: candidate.kind, selection: candidate.id, candidate })}>
            <span className={styles.candidateIcon}><ResultKindIcon kind={candidate.kind}/></span>
            <span><strong>{candidate.title}</strong><small>{candidate.subtitle}</small><em>{candidate.sourceLabel}</em></span>
            <ArrowRight aria-hidden="true" size={17}/>
          </button>)}</div>
        </section>}

        {response.stage === "detail" && <section className={styles.cards} aria-label="상세 조회 자료">
          {response.cards.map(card => <LookupResultCard key={card.id} card={card}/>)}
        </section>}

        {(response.stage === "empty" || response.stage === "unavailable") && <div className={styles.emptyState}>
          <Database aria-hidden="true" size={21}/><div><strong>{response.stage === "empty" ? "일치하는 자료가 없습니다." : "현재 조회 가능한 출처가 없습니다."}</strong><p>{response.message ?? "검색어를 수정하거나 출처 상태를 확인해 주세요."}</p></div><button type="button" onClick={editSearch}>검색 수정</button>
        </div>}
      </>}
    </section>
  </section>;
}
