"use client";

import { FormEvent, useState } from "react";

export default function LoginPage() {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) {
        setError(payload.error ?? "접속을 승인하지 못했습니다.");
        return;
      }
      window.location.replace("/");
    } catch {
      setError("서버에 연결하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return <main className="login-shell">
    <section className="login-panel">
      <div className="login-brand"><span>CRE DB</span><strong>MARKET INTELLIGENCE</strong></div>
      <p className="eyebrow">SECURE TEAM ACCESS</p>
      <h1>CRE Intelligence 접속</h1>
      <p>회사·자산·이벤트·기관자금·매각절차를 연결한 팀 전용 대시보드입니다.</p>
      <form onSubmit={submit}>
        <label htmlFor="access-code">팀 공용 접근코드</label>
        <input id="access-code" type="password" value={code} onChange={(event) => setCode(event.target.value)} autoComplete="current-password" required autoFocus/>
        {error && <p className="login-error" role="alert">{error}</p>}
        <button type="submit" disabled={loading || !code}>{loading ? "확인 중" : "대시보드 열기"}</button>
      </form>
      <small>접속 세션은 HttpOnly 보안 쿠키로 12시간 유지됩니다.</small>
    </section>
  </main>;
}
