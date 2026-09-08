export const DATA_SERVER_UNAVAILABLE_MESSAGE =
  "데이터 서버에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.";

export function safeErrorDescriptor(error: unknown) {
  const value = error as { name?: unknown; code?: unknown };
  return {
    name: typeof value?.name === "string" ? value.name : "UnknownError",
    code: typeof value?.code === "string" ? value.code : undefined,
  };
}

export function jsonWithServerTiming(
  body: unknown,
  options: ResponseInit = {},
  metric = "data",
  startedAt = performance.now(),
) {
  const headers = new Headers(options.headers);
  const duration = Math.max(0, performance.now() - startedAt).toFixed(1);
  headers.set("Server-Timing", `${metric};dur=${duration}`);
  return Response.json(body, { ...options, headers });
}

export function infrastructureUnavailableResponse(
  code: string,
  startedAt: number,
  headers?: HeadersInit,
) {
  return jsonWithServerTiming(
    { error: DATA_SERVER_UNAVAILABLE_MESSAGE, code },
    { status: 503, headers },
    "data",
    startedAt,
  );
}
