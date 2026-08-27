/** 面板与后端 /api 的客户端。 */
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
  // 设置
  settings: (token: string) => req(token, "/api/settings"),
  oauthMetadataAudit: (token: string) => req(token, "/api/oauth/metadata-audit"),
  mcpAudit: (token: string) => req(token, "/api/mcp-audit"),
  shells: (token: string) => req(token, "/api/shells"),
  killShell: (token: string, shellId: string) => req(token, `/api/shells/${encodeURIComponent(shellId)}/kill`, { method: "POST" }),
  cancelShellWait: (token: string, waitId: string, reason = "") => req(token, `/api/shell-waits/${encodeURIComponent(waitId)}/cancel`, { method: "POST", body: JSON.stringify({ reason }) }),
  clearMcpAudit: (token: string) => req(token, "/api/mcp-audit", { method: "DELETE" }),
  setSettings: (token: string, kv: Record<string, any>) =>
    req(token, "/api/settings", { method: "POST", body: JSON.stringify(kv) }),
  installTunnelClient: (token: string, release = "") =>
    req(token, "/api/native/tunnel-client/install", { method: "POST", body: JSON.stringify({ release }) }),
  // 全局公网入口：仅 direct / cloudflared
  publicRouteStatus: (token: string) => req(token, "/api/public-route/status"),
  publicRouteStart: (token: string, body: any) =>
    req(token, "/api/public-route/start", { method: "POST", body: JSON.stringify(body) }),
  publicRouteStop: (token: string) =>
    req(token, "/api/public-route/stop", { method: "POST" }),
  // ChatGPT Tunnel：独立 MCP 传输
  chatgptTunnelStatus: (token: string) => req(token, "/api/chatgpt-tunnel/status"),
  chatgptTunnelStart: (token: string, body: any) =>
    req(token, "/api/chatgpt-tunnel/start", { method: "POST", body: JSON.stringify(body) }),
  chatgptTunnelStop: (token: string) =>
    req(token, "/api/chatgpt-tunnel/stop", { method: "POST" }),
};
