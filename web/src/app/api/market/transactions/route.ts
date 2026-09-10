import {
  LargeTransactionRequestError,
  parseLargeTransactionsRequest,
} from "@/lib/large-transactions-contract";
import {
  infrastructureUnavailableResponse,
  jsonWithServerTiming,
} from "@/lib/server/api-response";
import {
  getCachedLargeTransactions,
  LargeTransactionDetailUnavailableError,
} from "@/lib/server/large-transactions-cache";
import { LargeTransactionMonthUnavailableError } from "@/lib/server/large-transactions";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type LargeTransactionsLoader = typeof getCachedLargeTransactions;

export async function loadLargeTransactionsResponse(
  request: Request,
  loader: LargeTransactionsLoader,
) {
  const startedAt = performance.now();
  let parsed;
  try {
    parsed = parseLargeTransactionsRequest(new URL(request.url).searchParams);
  } catch (error) {
    if (error instanceof LargeTransactionRequestError) {
      return jsonWithServerTiming(
        { error: "대형 거래 조회 조건이 올바르지 않습니다.", code: error.code },
        { status: 400, headers: { "Cache-Control": "no-store" } },
        "data",
        startedAt,
      );
    }
    throw error;
  }

  try {
    const payload = await loader(parsed);
    return jsonWithServerTiming(
      payload,
      { headers: { "Cache-Control": "private, no-store" } },
      "data",
      startedAt,
    );
  } catch (error) {
    if (error instanceof LargeTransactionRequestError) {
      return jsonWithServerTiming(
        { error: "요청한 결과 페이지가 존재하지 않습니다.", code: error.code },
        { status: 400, headers: { "Cache-Control": "no-store" } },
        "data",
        startedAt,
      );
    }
    if (error instanceof LargeTransactionMonthUnavailableError) {
      return jsonWithServerTiming(
        {
          error: "선택한 월의 서울 25개 자치구 완료 자료가 준비되지 않았습니다.",
          code: error.code,
        },
        { status: 409, headers: { "Cache-Control": "no-store" } },
        "data",
        startedAt,
      );
    }
    if (error instanceof LargeTransactionDetailUnavailableError) {
      return jsonWithServerTiming(
        {
          error: "현재 데이터 제공 방식에는 개별 거래 자료가 포함되어 있지 않습니다.",
          code: error.code,
        },
        { status: 503, headers: { "Cache-Control": "no-store" } },
        "data",
        startedAt,
      );
    }
    // Do not serialize or log provider messages, SQL, URLs, or credentials.
    console.error("large transaction request failed", {
      code: "LARGE_TRANSACTIONS_UNAVAILABLE",
    });
    return infrastructureUnavailableResponse(
      "LARGE_TRANSACTIONS_UNAVAILABLE",
      startedAt,
      { "Cache-Control": "no-store" },
    );
  }
}

export async function GET(request: Request) {
  return loadLargeTransactionsResponse(request, getCachedLargeTransactions);
}
