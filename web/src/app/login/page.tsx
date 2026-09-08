"use client";

import { FormEvent, useState } from "react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
        signal: controller.signal,
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) {
        setError(payload.error ?? "접속을 승인하지 못했습니다.");
        return;
      }
      window.location.replace("/");
    } catch (reason) {
      setError(reason instanceof DOMException && reason.name === "AbortError"
        ? "승인 확인 시간이 초과되었습니다. 다시 시도해 주세요."
        : "서버에 연결하지 못했습니다.");
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }
  }

  return <main className="login-shell">
    <section className="login-panel">
      <div className="login-brand"><span><b>CRE</b><strong>CRE DB</strong></span><small>MARKET INTELLIGENCE</small></div>
      <p className="eyebrow">TEAM ACCESS</p>
      <h1>시장 흐름을<br/>근거와 함께 확인하세요.</h1>
      <p>최신 CRE 기사 분류와 서울 거래, 건축 공급 인허가, 공식 금리 시계열을 한 화면에서 확인하는 팀 전용 워크스페이스입니다.</p>
      <form onSubmit={submit} aria-busy={loading}>
        <label htmlFor="access-email">본인 이메일 주소</label>
        <input id="access-email" type="email" inputMode="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" placeholder="name@company.com" required autoFocus/>
        {error && <p className="login-error" role="alert">{error}</p>}
        <button type="submit" disabled={loading || !email.trim()}>{loading ? "승인 확인 중" : "대시보드 열기"}</button>
      </form>
      <small>사전 등록된 이메일만 접속할 수 있습니다.</small>
    </section>
  </main>;
}
