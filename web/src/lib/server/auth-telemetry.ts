export type AuthInfrastructureStage =
  | "LOGIN_LIMITER_CONSUME"
  | "ALLOWLIST_LOOKUP"
  | "LOGIN_LIMITER_CLEAR";

type SafeErrorClass =
  | "DatabaseRequestError"
  | "DatabaseQueryTimeoutError"
  | "DatabaseConfigurationError"
  | "SyntaxError"
  | "TypeError"
  | "Error"
  | "UnknownError";

type SafeErrorCode =
  | "DATABASE_REQUEST_FAILED"
  | "DATABASE_QUERY_TIMEOUT"
  | "DATABASE_CONFIGURATION_ERROR"
  | "SYNTAX_ERROR"
  | "TYPE_ERROR"
  | "UNCLASSIFIED_ERROR";

export type AuthInfrastructureTelemetry = {
  event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE";
  stage: AuthInfrastructureStage;
  errorClass: SafeErrorClass;
  errorCode: SafeErrorCode;
  upstreamStatus?: number;
  timeoutMs?: number;
};

const SAFE_UPSTREAM_STATUSES = new Set([
  400, 401, 403, 404, 405, 406, 408, 409, 415, 422, 429, 500, 502, 503, 504,
]);

function errorRecord(error: unknown) {
  return error !== null && typeof error === "object"
    ? error as Record<string, unknown>
    : null;
}

export function authInfrastructureTelemetry(
  stage: AuthInfrastructureStage,
  error: unknown,
): AuthInfrastructureTelemetry {
  const candidate = errorRecord(error);
  const name = candidate?.name;
  const code = candidate?.code;

  if (name === "DatabaseRequestError" && code === "DATABASE_REQUEST_FAILED") {
    const telemetry: AuthInfrastructureTelemetry = {
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage,
      errorClass: "DatabaseRequestError",
      errorCode: "DATABASE_REQUEST_FAILED",
    };
    const status = candidate?.status;
    if (typeof status === "number" && SAFE_UPSTREAM_STATUSES.has(status)) {
      telemetry.upstreamStatus = status;
    }
    return telemetry;
  }

  if (name === "DatabaseQueryTimeoutError" && code === "DATABASE_QUERY_TIMEOUT") {
    const telemetry: AuthInfrastructureTelemetry = {
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage,
      errorClass: "DatabaseQueryTimeoutError",
      errorCode: "DATABASE_QUERY_TIMEOUT",
    };
    const timeoutMs = candidate?.timeoutMs;
    if (
      typeof timeoutMs === "number"
      && Number.isInteger(timeoutMs)
      && timeoutMs >= 1_000
      && timeoutMs <= 30_000
    ) telemetry.timeoutMs = timeoutMs;
    return telemetry;
  }

  if (name === "DatabaseConfigurationError" && code === "DATABASE_CONFIGURATION_ERROR") {
    return {
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage,
      errorClass: "DatabaseConfigurationError",
      errorCode: "DATABASE_CONFIGURATION_ERROR",
    };
  }

  if (name === "SyntaxError") {
    return {
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage,
      errorClass: "SyntaxError",
      errorCode: "SYNTAX_ERROR",
    };
  }

  if (name === "TypeError") {
    return {
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage,
      errorClass: "TypeError",
      errorCode: "TYPE_ERROR",
    };
  }

  return {
    event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
    stage,
    errorClass: name === "Error" ? "Error" : "UnknownError",
    errorCode: "UNCLASSIFIED_ERROR",
  };
}
