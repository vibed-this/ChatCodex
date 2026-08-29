/** /api client. */
const BASE = "";

function headers(token = "") {
  return { ...(token ? { authorization: `Bearer ${token}` } : {}), "content-type": "application/json" };
}

async function req(token: string, path: string, opts: RequestInit = {}) {
  const r = await fetch(BASE + path, { credentials: "same-origin", ...opts, headers: { ...headers(token), ...(opts.headers || {}) } });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
}

export const api = {
  health: () => fetch(BASE + "/healthz").then((r) => r.json()),
  login: (token: string) => req("", "/api/auth/session", { method: "POST", body: JSON.stringify({ token }) }),
  authStatus: () => req("", "/api/auth/session"),
  logout: () => req("", "/api/auth/session", { method: "DELETE" }),
  overview: (token: string) => req(token, "/api/overview"),
  settings: (token: string) => req(token, "/api/settings"),
  externalMcp: (token: string) => req(token, "/api/external-mcp"),
  setExternalMcp: (token: string, servers: any[]) => req(token, "/api/external-mcp", { method: "PUT", body: JSON.stringify({ servers }) }),
  testExternalMcp: (token: string, server: any) => req(token, "/api/external-mcp/test", { method: "POST", body: JSON.stringify(server) }),
  oauthMetadataAudit: (token: string) => req(token, "/api/oauth/metadata-audit"),
  mcpAudit: (token: string) => req(token, "/api/mcp-audit"),
  shells: (token: string) => req(token, "/api/shells"),
  killShell: (token: string, shellId: string) => req(token, `/api/shells/${encodeURIComponent(shellId)}/kill`, { method: "POST" }),
  cancelShellWait: (token: string, waitId: string, reason = "") => req(token, `/api/shell-waits/${encodeURIComponent(waitId)}/cancel`, { method: "POST", body: JSON.stringify({ reason }) }),
  clearMcpAudit: (token: string) => req(token, "/api/mcp-audit", { method: "DELETE" }),
  setSettings: (token: string, kv: Record<string, any>) => req(token, "/api/settings", { method: "POST", body: JSON.stringify(kv) }),
};
