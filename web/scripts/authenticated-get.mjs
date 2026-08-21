export async function createAuthenticatedGet(base) {
  const email = process.env.DASHBOARD_SMOKE_EMAIL?.trim().toLowerCase();
  if (!email) throw new Error("DASHBOARD_SMOKE_EMAIL is required and must already be approved");

  const login = await fetch(`${base}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!login.ok) throw new Error(`auth login failed: ${login.status}`);
  const sessionCookie = login.headers.get("set-cookie")?.split(";", 1)[0] ?? "";
  if (!sessionCookie) throw new Error("auth login did not return a session cookie");

  return async function get(path) {
    const response = await fetch(`${base}${path}`, { headers: { Cookie: sessionCookie } });
    const payload = await response.json();
    if (!response.ok) throw new Error(`${path} ${response.status} ${JSON.stringify(payload)}`);
    return payload;
  };
}
