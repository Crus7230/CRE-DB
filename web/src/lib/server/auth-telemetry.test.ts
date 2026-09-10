import { describe, expect, it } from "vitest";
import { authInfrastructureTelemetry } from "@/lib/server/auth-telemetry";

describe("authInfrastructureTelemetry", () => {
  it("keeps only allowlisted request and timeout diagnostics", () => {
    const requestFailure = Object.assign(new Error("secret upstream response"), {
      name: "DatabaseRequestError",
      code: "DATABASE_REQUEST_FAILED",
      status: 503,
      url: "https://secret.example/rest/v1/rpc/login",
      headers: { authorization: "secret-token" },
      body: "secret-body",
      email: "person@example.com",
      key: "secret-rate-key",
      cookie: "secret-cookie",
    });
    const timeoutFailure = Object.assign(new Error("secret timeout detail"), {
      name: "DatabaseQueryTimeoutError",
      code: "DATABASE_QUERY_TIMEOUT",
      timeoutMs: 8_000,
      stack: "secret-stack",
      env: "secret-env",
    });

    expect(authInfrastructureTelemetry("LOGIN_LIMITER_CONSUME", requestFailure)).toEqual({
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage: "LOGIN_LIMITER_CONSUME",
      errorClass: "DatabaseRequestError",
      errorCode: "DATABASE_REQUEST_FAILED",
      upstreamStatus: 503,
    });
    expect(authInfrastructureTelemetry("ALLOWLIST_LOOKUP", timeoutFailure)).toEqual({
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage: "ALLOWLIST_LOOKUP",
      errorClass: "DatabaseQueryTimeoutError",
      errorCode: "DATABASE_QUERY_TIMEOUT",
      timeoutMs: 8_000,
    });
    const syntaxTelemetry = authInfrastructureTelemetry(
      "ALLOWLIST_LOOKUP",
      Object.assign(new SyntaxError("secret syntax detail"), { cause: "secret-cause" }),
    );
    const typeTelemetry = authInfrastructureTelemetry(
      "ALLOWLIST_LOOKUP",
      Object.assign(new TypeError("secret type detail"), { cause: "secret-cause" }),
    );
    expect(syntaxTelemetry).toEqual({
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage: "ALLOWLIST_LOOKUP",
      errorClass: "SyntaxError",
      errorCode: "SYNTAX_ERROR",
    });
    expect(typeTelemetry).toEqual({
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage: "ALLOWLIST_LOOKUP",
      errorClass: "TypeError",
      errorCode: "TYPE_ERROR",
    });
    expect(JSON.stringify([syntaxTelemetry, typeTelemetry])).not.toContain("secret");
  });

  it("does not pass through unknown classes, codes, statuses, or fields", () => {
    const telemetry = authInfrastructureTelemetry("LOGIN_LIMITER_CLEAR", {
      name: "InjectedSecretClass",
      code: "SECRET_CODE",
      status: 599,
      timeoutMs: 999_999,
      message: "secret-message",
      stack: "secret-stack",
      url: "https://secret.example",
      headers: { authorization: "secret-token" },
      email: "person@example.com",
      key: "secret-rate-key",
      cookie: "secret-cookie",
    });

    expect(telemetry).toEqual({
      event: "DASHBOARD_AUTH_INFRASTRUCTURE_FAILURE",
      stage: "LOGIN_LIMITER_CLEAR",
      errorClass: "UnknownError",
      errorCode: "UNCLASSIFIED_ERROR",
    });
    expect(Object.keys(telemetry).sort()).toEqual([
      "errorClass", "errorCode", "event", "stage",
    ]);
  });
});
