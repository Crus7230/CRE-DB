"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  normalizeLargeTransactions,
  type LargeTransactionsResponse,
} from "@/lib/large-transactions-contract";
import styles from "./large-transaction-list.module.css";

const REQUEST_TIMEOUT_MS = 10_000;
const CACHE_TTL_MS = 30_000;
const MAX_CACHE_ENTRIES = 16;

type RequestError = "TIMEOUT" | "MONTH_UNAVAILABLE" | "DETAIL_UNAVAILABLE" | "STALE_PULSE" | "REQUEST";
type CachedPage = { expiresAt: number; data: LargeTransactionsResponse };

class HttpFailure extends Error {
  constructor(readonly status: number, readonly code: string | null) {
    super("Large transaction request failed");
  }
}

class StalePulseError extends Error {}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const responseCode = (value: unknown) => isRecord(value) && typeof value.code === "string" ? value.code : null;
const exactM2 = (value: number) => `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 4 }).format(value)}㎡`;
const pyeong = (value: number) => `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(value)}평`;
const won = (value: string) => `${BigInt(value).toLocaleString("ko-KR")}원`;

function errorCopy(error: RequestError) {
  if (error === "TIMEOUT") return ["5천평 이상 거래 목록 조회 시간이 초과되었습니다.", "잠시 뒤 다시 조회해 주세요."] as const;
  if (error === "MONTH_UNAVAILABLE") return ["이 월은 상세 목록 조회 범위에 아직 포함되지 않습니다.", "수집 완료 범위만 조회할 수 있습니다."] as const;
  if (error === "DETAIL_UNAVAILABLE") return ["5천평 이상 상세 데이터 연결 전입니다.", "월별 차트 집계는 유지되며 상세 목록만 현재 사용할 수 없습니다."] as const;
  if (error === "STALE_PULSE") return ["집계 기준이 갱신되었습니다.", "최신 월별 집계와 상세 목록을 맞추려면 화면을 새로고침해 주세요."] as const;
  return ["5천평 이상 거래 목록을 불러오지 못했습니다.", "상세 데이터 연결을 확인한 뒤 다시 조회해 주세요."] as const;
}

export function LargeTransactionList({
  month,
  baseTransactionCount,
  cacheScope,
  onClear,
}: {
  month: string | null;
  baseTransactionCount: number | null;
  cacheScope: string;
  onClear: () => void;
}) {
  const cache = useRef(new Map<string, CachedPage>());
  const [pages, setPages] = useState<Record<string, number>>({});
  const [result, setResult] = useState<{ requestKey: string; data: LargeTransactionsResponse } | null>(null);
  const [error, setError] = useState<{ requestKey: string; kind: RequestError } | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const monthKey = month ? `${cacheScope}:${month}` : null;
  const page = monthKey ? pages[monthKey] ?? 1 : 1;
  const cacheKey = monthKey ? `${monthKey}:${page}` : null;
  const requestKey = cacheKey ? `${cacheKey}:retry-${retryKey}` : null;

  useEffect(() => {
    cache.current.clear();
  }, [cacheScope]);

  useEffect(() => {
    if (!month || baseTransactionCount === null || !cacheKey || !requestKey) return;
    const controller = new AbortController();
    let disposed = false;
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);

    void (async () => {
      try {
        const cached = cache.current.get(cacheKey);
        if (cached && cached.expiresAt > Date.now()) {
          if (!disposed) {
            setResult({ requestKey, data: cached.data });
            setError(null);
          }
          return;
        }
        if (cached) cache.current.delete(cacheKey);
        const response = await fetch(`/api/market/transactions?month=${encodeURIComponent(month)}&page=${page}`, {
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (!response.ok) {
          let code: string | null = null;
          try { code = responseCode(await response.json()); } catch { /* Fixed status fallback below. */ }
          throw new HttpFailure(response.status, code);
        }
        const data = normalizeLargeTransactions(await response.json());
        if (data.month !== month || data.page !== page || data.baseTransactionCount !== baseTransactionCount) throw new StalePulseError("Mismatched transaction response");
        while (cache.current.size >= MAX_CACHE_ENTRIES) {
          const oldest = cache.current.keys().next().value;
          if (oldest === undefined) break;
          cache.current.delete(oldest);
        }
        cache.current.set(cacheKey, { expiresAt: Date.now() + CACHE_TTL_MS, data });
        if (!disposed) {
          setResult({ requestKey, data });
          setError(null);
        }
      } catch (reason) {
        if (disposed) return;
        if (timedOut) setError({ requestKey, kind: "TIMEOUT" });
        else if (reason instanceof HttpFailure && reason.status === 409 && reason.code === "LARGE_TRANSACTION_MONTH_UNAVAILABLE") setError({ requestKey, kind: "MONTH_UNAVAILABLE" });
        else if (reason instanceof HttpFailure && reason.status === 503 && reason.code === "LARGE_TRANSACTION_DETAIL_UNAVAILABLE") setError({ requestKey, kind: "DETAIL_UNAVAILABLE" });
        else if (reason instanceof StalePulseError) setError({ requestKey, kind: "STALE_PULSE" });
        else if (!(reason instanceof DOMException && reason.name === "AbortError")) setError({ requestKey, kind: "REQUEST" });
      } finally {
        window.clearTimeout(timeout);
      }
    })();

    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [baseTransactionCount, cacheKey, month, page, requestKey]);

  if (!month || baseTransactionCount === null || !monthKey || !requestKey) return null;
  const current = result?.requestKey === requestKey ? result.data : null;
  const currentError = error?.requestKey === requestKey ? error.kind : null;
  const [errorTitle, errorDetail] = currentError ? errorCopy(currentError) : ["", ""];
  const setPage = (nextPage: number) => setPages((currentPages) => ({ ...currentPages, [monthKey]: nextPage }));

  return <section id="large-transaction-list" className={styles.list} aria-labelledby="large-transaction-title">
    <header className={styles.listHeader}>
      <div><p className="eyebrow">SELECTED MONTH DETAIL</p><h4 id="large-transaction-title">{month} · 거래면적 5천평 이상 <span>(약 16,529㎡)</span></h4></div>
      <button type="button" onClick={onClear}>{month} 선택 해제</button>
    </header>
    {!current && !currentError && <div className={styles.state} role="status">5천평 이상 거래 목록을 불러오는 중입니다.</div>}
    {currentError && <div className={`${styles.state} ${styles.error}`} role="alert"><strong>{errorTitle}</strong><span>{errorDetail}</span>{currentError !== "STALE_PULSE" && <button type="button" onClick={() => setRetryKey((value) => value + 1)}><RefreshCw aria-hidden="true" size={14}/>다시 조회</button>}</div>}
    {current && <>
      <div className={styles.counts} aria-label={`${month} 거래 목록 기준 비교`}>
        <span><b>전체 신고</b>{current.baseTransactionCount.toLocaleString("ko-KR")}건 <small>(&gt;3,300㎡)</small></span>
        <span><b>5천평 이상</b>{current.totalCount.toLocaleString("ko-KR")}건</span>
        <span><b>수집 범위</b>{current.coverage.completedDistrictCount}/{current.coverage.expectedDistrictCount}개 자치구 완료</span>
      </div>
      {current.totalCount === 0 ? <div className={styles.empty} role="status">
        {current.baseTransactionCount > 0
          ? `이 월의 전체 신고 ${current.baseTransactionCount.toLocaleString("ko-KR")}건(>3,300㎡)에는 5천평 미만 거래가 포함되어 있지만, 거래면적 5천평 이상 신고행은 없습니다.`
          : "이 월에는 차트 모집단 및 거래면적 5천평 이상 신고행이 없습니다."}
      </div> : <>
        <div className={styles.tableWrap}>
          <table aria-label={`${month} 거래면적 5천평 이상 신고행`}>
            <thead><tr><th>거래일</th><th>소재지·용도</th><th>거래면적</th><th>거래금액</th></tr></thead>
            <tbody>{current.rows.map((row) => <tr key={row.id}>
              <td>{row.dealDate}</td>
              <th><span>{row.address}</span><small className={styles.rowMeta}>{row.buildingUse}{row.buildingType ? ` · ${row.buildingType}` : ""}{row.address.includes("*") ? " · 지번 일부 마스킹" : ""}</small></th>
              <td><strong className={styles.cellPrimary}>{pyeong(row.areaPyeong)}</strong><small className={styles.cellSecondary}>{exactM2(row.areaM2)}</small></td>
              <td>{won(row.amountKrw)}</td>
            </tr>)}</tbody>
          </table>
        </div>
        {current.totalPages > 1 && <nav className={styles.pagination} aria-label={`${month} 거래 목록 페이지`}>
          <button type="button" disabled={current.page <= 1} onClick={() => setPage(current.page - 1)}>이전</button>
          <span>{current.page.toLocaleString("ko-KR")} / {current.totalPages.toLocaleString("ko-KR")}</span>
          <button type="button" disabled={current.page >= current.totalPages} onClick={() => setPage(current.page + 1)}>다음</button>
        </nav>}
      </>}
      <footer className={styles.listFoot}>
        <span>{current.source.label} · 서울특별시 · 수집 완료 자료 · 동일 내용 중복 제외</span>
        <small>거래면적은 신고행의 거래 건축물 면적이며 건물 전체 연면적과 다를 수 있습니다.</small>
      </footer>
    </>}
  </section>;
}
