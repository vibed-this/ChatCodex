import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bot, Check, ChevronRight, Cloud,
  Copy, Download, ExternalLink, Eye, EyeOff, Gauge, KeyRound,
  LockKeyhole, LogOut, Menu, Moon, Network, Play, RefreshCw, Save,
  Settings2, Square, Sun, Zap, Search, Trash2, X,
} from "lucide-react";
import "../styles.css";
import { api } from "./api";
import { cn } from "../lib/utils";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { Separator } from "../components/ui/separator";
import { Switch } from "../components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";

type Tab = "overview" | "tunnel" | "settings" | "mcp-audit";
const NAV: Array<{ id: Tab; label: string; icon: React.ElementType }> = [
  { id: "overview", label: "概览", icon: Gauge },
  { id: "tunnel", label: "公网入口", icon: Network },
  { id: "settings", label: "设置", icon: Settings2 },
  { id: "mcp-audit", label: "MCP 调用审计", icon: Search },
];

function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<any>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [dark, setDark] = useState(localStorage.getItem("cc_theme") === "dark");

  useEffect(() => {
    // Remove the pre-split UI's JavaScript-readable bearer token on upgrade.
    localStorage.removeItem("cc_token");
    sessionStorage.removeItem("cc_token");
  }, []);
  useEffect(() => { api.authStatus().then(() => { setAuthenticated(true); }).catch(() => { setAuthenticated(false); }); }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
    localStorage.setItem("cc_theme", dark ? "dark" : "light");
  }, [dark]);
  useEffect(() => {
    if (!authenticated) return;
    const load = () => api.overview("").then(setOverview).catch((e) => {
      if (String(e).startsWith("Error: 401")) setAuthenticated(false);
    });
    load(); const timer = window.setInterval(load, 5000); return () => { clearInterval(timer); };
  }, [authenticated]);

  if (authenticated === null) return <Splash />;
  if (!authenticated) return <Login onSuccess={() => { setAuthenticated(true); }} dark={dark} setDark={setDark} />;

  const selectTab = (value: Tab) => { setTab(value); setNavOpen(false); };
  return (
    <div className="min-h-screen bg-muted/35 text-foreground">
      <aside className={cn("fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r bg-background transition-transform lg:translate-x-0", navOpen ? "translate-x-0" : "-translate-x-full")}>
        <Brand />
        <nav className="flex-1 space-y-1 px-3 py-4">
          <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[.14em] text-muted-foreground">Workspace</p>
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => { selectTab(id); }} className={cn("flex h-10 w-full items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors", tab === id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground")}>
              <Icon className="h-4 w-4" />{label}
            </button>
          ))}
        </nav>
        <div className="m-3 rounded-xl border bg-muted/40 p-3">
          <StatusLine label="公网入口" on={overview?.publicRoute?.running} />
          <StatusLine label="MCP Tunnel" on={overview?.chatgptTunnel?.running} />
        </div>
        <div className="flex items-center gap-1 border-t p-3">
          <Button variant="ghost" size="icon" aria-label="切换主题" onClick={() => { setDark(!dark); }}>{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
          <Button variant="ghost" className="ml-auto text-muted-foreground" onClick={async () => { await api.logout(); setAuthenticated(false); }}><LogOut className="h-4 w-4" />退出</Button>
        </div>
      </aside>
      {navOpen && <button aria-label="关闭导航" className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={() => { setNavOpen(false); }} />}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur lg:px-8">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="打开导航" onClick={() => { setNavOpen(true); }}><Menu className="h-5 w-5" /></Button>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{NAV.find((item) => item.id === tab)?.label}</p>
            <p className="truncate text-xs text-muted-foreground">ChatCodex Gateway 控制台</p>
          </div>
          <Badge variant={overview ? "success" : "secondary"} className="ml-auto gap-1.5"><span className={cn("h-1.5 w-1.5 rounded-full", overview ? "bg-emerald-500" : "bg-muted-foreground")} />{overview ? "系统正常" : "等待服务"}</Badge>
        </header>
        <main className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
          {tab === "overview" && <Overview data={overview} go={selectTab} />}
          {tab === "tunnel" && <Tunnel />}
          {tab === "settings" && <Settings />}
          {tab === "mcp-audit" && <McpAudit />}
        </main>
      </div>
    </div>
  );
}

function Login({ onSuccess, dark, setDark }: { onSuccess(): void; dark: boolean; setDark(v: boolean): void }) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { await api.login(token.trim()); setToken(""); onSuccess(); }
    catch { setError("Web Access Token 不正确，请检查 Gateway 启动输出或环境配置。"); }
    finally { setBusy(false); }
  }
  return (
    <div className="grid min-h-screen bg-muted/30 lg:grid-cols-[1.1fr_.9fr]">
      <div className="relative hidden overflow-hidden border-r bg-zinc-950 p-12 text-white lg:flex lg:flex-col">
        <div className="absolute inset-0 opacity-40 [background-image:radial-gradient(circle_at_20%_20%,#10a37f_0,transparent_35%),radial-gradient(circle_at_80%_70%,#2563eb_0,transparent_30%)]" />
        <div className="relative"><Brand inverse /></div>
        <div className="relative my-auto max-w-lg">
          <Badge className="mb-5 border-white/15 bg-white/10 text-white">本地优先的智能体网关</Badge>
          <h1 className="text-5xl font-semibold leading-[1.08] tracking-tight">在 ChatGPT 中安全运行本地工具。</h1>
          <p className="mt-5 max-w-md text-base leading-7 text-zinc-300">在此管理工作区、MCP 入口与安全隧道。</p>
        </div>
        <p className="relative text-xs text-zinc-500">Web Access Token 仅用于登录本控制台。</p>
      </div>
      <div className="relative flex items-center justify-center p-6">
        <Button variant="ghost" size="icon" className="absolute right-5 top-5" aria-label="切换主题" onClick={() => { setDark(!dark); }}>{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
        <form onSubmit={submit} className="w-full max-w-sm">
          <div className="mb-8 lg:hidden"><Brand /></div>
          <div className="mb-7">
            <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary"><LockKeyhole className="h-5 w-5" /></div>
            <h2 className="text-2xl font-semibold tracking-tight">连接 Gateway</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">输入 Web Access Token 以登录控制台。Token 见 Gateway 启动输出。</p>
          </div>
          <div className="space-y-2"><Label htmlFor="web-token">Web Access Token</Label><Input id="web-token" type="password" autoFocus autoComplete="current-password" value={token} onChange={(e) => { setToken(e.target.value); }} placeholder="粘贴 Web Access Token" className="h-11 font-mono" /></div>
          {error && <div role="alert" className="mt-3 rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}
          <Button className="mt-5 h-11 w-full" disabled={!token.trim() || busy}>{busy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}{busy ? "正在验证" : "进入控制台"}</Button>
        </form>
      </div>
    </div>
  );
}

function Overview({ data, go }: { data: any; go(tab: Tab): void }) {
  if (!data) return <Loading text="正在读取 Gateway 状态" />;
  const stats = [
    { label: "公网入口", value: data.publicRoute?.running ? "已启用" : "未启用", detail: data.publicRoute?.kind ?? "none", icon: Cloud, tab: "tunnel" as Tab },
  ];
  const publicEndpoint = data.publicRoute?.url?.startsWith("http") ? mcpUrl(data.publicRoute.url) : data.publicRoute?.url;
  const secureTunnel = data.chatgptTunnel?.tunnelId || data.chatgptTunnel?.url;
  return (
    <Page title="运行概览" description="WebChat、Gateway 独立执行与公网入口的实时状态。">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{stats.map(({ icon: Icon, ...item }) => <Card key={item.label} className="group cursor-pointer transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md" onClick={() => { go(item.tab); }}><CardContent className="p-5"><div className="flex items-start justify-between"><div><p className="text-sm text-muted-foreground">{item.label}</p><p className="mt-2 text-2xl font-semibold tracking-tight">{item.value}</p></div><div className="rounded-lg bg-primary/10 p-2.5 text-primary"><Icon className="h-4 w-4" /></div></div><p className="mt-3 text-xs text-muted-foreground">{item.detail}</p></CardContent></Card>)}</div>
      <div className="mt-6 grid gap-6 xl:grid-cols-[1.3fr_.7fr]">
        <Card><CardHeader><CardTitle>ChatGPT MCP 入口</CardTitle><CardDescription>对外提供的 MCP 接入地址。</CardDescription></CardHeader><CardContent className="space-y-3">{publicEndpoint && <CopyValue value={publicEndpoint} />}{secureTunnel && <CopyValue value={secureTunnel} />}{!publicEndpoint && !secureTunnel && <Empty icon={Network} title="尚未建立 MCP 入口" detail="配置 Cloudflare/直接暴露，或在设置中启用 ChatGPT Tunnel。" action={<Button size="sm" variant="outline" onClick={() => { go("tunnel"); }}>配置公网入口<ChevronRight className="h-3.5 w-3.5" /></Button>} />}</CardContent></Card>
        <Card><CardHeader><CardTitle>认证</CardTitle><CardDescription>控制台与 MCP 分别使用独立凭据。</CardDescription></CardHeader><CardContent className="space-y-3"><Boundary icon={LockKeyhole} title="Web" value="Access Token" detail="控制台登录" /><Boundary icon={KeyRound} title="MCP" value={data.auth?.mcp ?? "—"} detail="MCP 工具调用" /></CardContent></Card>
      </div>
    </Page>
  );
}

function Tunnel() {
  const [state, setState] = useState<any>(null);
  const [kind, setKind] = useState("direct");
  const [mode, setMode] = useState("try");
  const [tunnelToken, setTunnelToken] = useState("");
  const [mcpMode, setMcpMode] = useState("");
  const [publicUrl, setPublicUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = () => api.publicRouteStatus("").then(setState).catch(() => {});
  useEffect(() => {
    load();
    api.settings("").then((d) => {
      setMcpMode(d.settings?.mcp_auth_mode ?? "");
      setPublicUrl(d.settings?.public_url ?? "");
      const route = d.settings?.public_route_kind ?? "";
      if (route.startsWith("cloudflared-")) {
        setKind("cloudflared"); setMode(route.slice("cloudflared-".length));
      } else if (route === "direct") setKind("direct");
    });
    const timer = setInterval(load, 3000);
    return () => { clearInterval(timer); };
  }, []);
  async function start() {
    setBusy(true); setError("");
    try {
      const body = kind === "cloudflared"
        ? { kind, mode, token: tunnelToken }
        : { kind: "direct" };
      const result = await api.publicRouteStart("", body);
      setState(result);
      if (!result.running) setError(result.detail || "公网入口未就绪");
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  const endpoint = state?.url?.startsWith("http") ? mcpUrl(state.url) : state?.url;
  return <Page title="全局公网入口" description="选择 Cloudflare 或直接暴露，对外提供 Gateway 服务。">
    <div className="grid gap-6 xl:grid-cols-[.8fr_1.2fr]">
      <div className="space-y-4">
        <Card><CardHeader><CardTitle>入口状态</CardTitle><CardDescription>对外提供 Web、API 与可选直连 MCP 的公网路径。</CardDescription></CardHeader><CardContent className="space-y-4"><div className="flex items-center gap-3"><div className={cn("rounded-full p-3", state?.running ? "bg-emerald-500/10 text-emerald-600" : "bg-muted text-muted-foreground")}><Zap className="h-5 w-5" /></div><div><p className="font-medium">{state?.running ? "公网入口已启用" : "公网入口未启用"}</p><p className="text-sm text-muted-foreground">{state?.kind ?? "none"}</p></div></div>{endpoint && <CopyValue value={endpoint} />}{state?.detail && <p className="rounded-lg bg-muted p-3 text-xs leading-5 text-muted-foreground">{state.detail}</p>}{state?.lastError && <Alert>{state.lastError}</Alert>}</CardContent></Card>
        <Card><CardHeader><CardTitle>当前运行地址</CardTitle><CardDescription>对外服务使用的公网地址。</CardDescription></CardHeader><CardContent><CopyValue value={state?.url || publicUrl || "未配置"} /></CardContent></Card>
      </div>
      <Card><CardHeader><CardTitle>选择公网方式</CardTitle><CardDescription>在 Cloudflare 与直接暴露之间二选一。</CardDescription></CardHeader><CardContent className="space-y-5"><div className="grid gap-2 sm:grid-cols-2">{[["cloudflared", "Cloudflare", Cloud], ["direct", "直接暴露", ExternalLink]].map(([value, label, Icon]: any) => <button key={value} onClick={() => { setKind(value); }} className={cn("rounded-xl border p-3 text-left transition", kind === value ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-accent")}><Icon className="mb-3 h-4 w-4" /><p className="text-sm font-medium">{label}</p></button>)}</div>{kind === "cloudflared" ? <><Field label="Cloudflare 模式"><Select value={mode} onValueChange={setMode}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="try">临时域名（仅调试）</SelectItem><SelectItem value="named">固定域名（生产）</SelectItem></SelectContent></Select></Field>{mode === "named" && <Field label="Tunnel Token"><SecretInput value={tunnelToken} setValue={setTunnelToken} placeholder="Cloudflare tunnel JWT" /></Field>}{mode === "try" && ["oauth", "both"].includes(mcpMode) && <Alert tone="warning">临时域名每次重启都会变化，已有 OAuth 客户端需重新连接；生产请用固定域名。</Alert>}</> : <Alert>直接暴露不启动代理；请确保公网 URL、TLS 证书、DNS/NAT 已指向本 Gateway。</Alert>}{!["oauth", "both"].includes(mcpMode) && <Alert tone="warning">公网 MCP 建议使用 OAuth。</Alert>}{error && <Alert>{error}</Alert>}<div className="flex gap-2"><Button onClick={start} disabled={busy}>{busy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}启用</Button><Button variant="outline" onClick={() => api.publicRouteStop("").then(load)}><Square className="h-3.5 w-3.5" />停止</Button></div></CardContent></Card>
    </div>
  </Page>;
}

function ChatGptMcpTunnel({ cfg, set }: { cfg: Record<string, any>; set(key: string, value: any): void }) {
  const [state, setState] = useState<any>(null);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const load = () => api.chatgptTunnelStatus("").then(setState).catch(() => {});
  useEffect(() => { load(); const timer = setInterval(load, 3000); return () => { clearInterval(timer); }; }, []);
  const oauthMode = ["oauth", "both"].includes(cfg.mcp_auth_mode);
  const issuer = String(cfg.runtime_public_url || cfg.public_url || "");
  const issuerReady = /^https:\/\/(?!localhost(?::|\/)|127\.0\.0\.1(?::|\/)|\[?::1\]?)/i.test(issuer);
  const oauthBlocked = oauthMode && !issuerReady;
  async function start() {
    setBusy(true); setError("");
    try {
      const result = await api.chatgptTunnelStart("", {
        tunnel_id: cfg.chatgpt_tunnel_id ?? "", api_key: apiKey,
        client_bin: cfg.tunnel_client_command ?? "",
      });
      setState(result); set("chatgpt_tunnel_enabled", true);
      if (!result.running || !result.ready) setError(result.detail || "ChatGPT Tunnel 尚未就绪");
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function stop() {
    setBusy(true); setError("");
    try { await api.chatgptTunnelStop(""); set("chatgpt_tunnel_enabled", false); await load(); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function download() {
    setDownloading(true); setError("");
    try { await api.installTunnelClient("", cfg.tunnel_client_release || "v0.0.11-dev"); await load(); }
    catch (e) { setError(String(e)); } finally { setDownloading(false); }
  }
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><Network className="h-4 w-4 text-primary" />ChatGPT Tunnel · MCP</CardTitle><CardDescription>仅把 `/mcp/` 提供给 ChatGPT，不作为全局公网入口。</CardDescription></CardHeader><CardContent className="space-y-5"><div className="grid gap-4 md:grid-cols-2"><Field label="Tunnel ID" hint="OpenAI 控制平面的 tunnel_… 标识。"><Input value={cfg.chatgpt_tunnel_id ?? ""} onChange={(e) => { set("chatgpt_tunnel_id", e.target.value); }} placeholder="tunnel_…" /></Field><Field label="Runtime API Key" hint="仅保留在当前进程；自动启动请用 CONTROL_PLANE_API_KEY。"><SecretInput value={apiKey} setValue={setApiKey} placeholder="sk-…" /></Field><Field label="tunnel-client 版本"><Input value={cfg.tunnel_client_release ?? "v0.0.11-dev"} onChange={(e) => { set("tunnel_client_release", e.target.value); }} className="font-mono text-xs" /></Field><div className="flex items-end"><Button variant="outline" onClick={download} disabled={downloading}>{downloading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}下载 / 更新客户端</Button></div></div><div className="grid gap-3 sm:grid-cols-2"><div className="flex items-center justify-between rounded-lg border p-3"><div><Label>随 Gateway 自动启动</Label><p className="mt-1 text-xs text-muted-foreground">需要环境变量中的 Runtime API Key</p></div><Switch checked={cfg.chatgpt_tunnel_enabled ?? false} onCheckedChange={(v) => { set("chatgpt_tunnel_enabled", v); }} /></div><div className="flex items-center justify-between rounded-lg border p-3"><div><Label>异常自动重启</Label><p className="mt-1 text-xs text-muted-foreground">独立线程与有界退避</p></div><Switch checked={cfg.tunnel_auto_restart ?? true} onCheckedChange={(v) => { set("tunnel_auto_restart", v); }} /></div></div>{oauthMode ? (oauthBlocked ? <Alert tone="warning">OAuth 需要先把全局公网 URL 配成可公开访问的 HTTPS 地址。</Alert> : <Alert>OAuth 授权服务器地址 {issuer} 必须能被 ChatGPT 公开访问。</Alert>) : <Alert>Token 模式下 MCP Access Token 只用于本机私有连接，不提供给 ChatGPT。</Alert>}{error && <Alert>{error}</Alert>}<div className="rounded-lg border p-3"><div className="flex flex-wrap items-center gap-3"><Badge variant={state?.ready ? "success" : state?.running ? "warning" : "secondary"}>{state?.ready ? "已就绪" : state?.running ? "启动中" : "已停止"}</Badge><span className="text-xs text-muted-foreground">PID {state?.pid || "—"} · {state?.detail || "未启动"}</span><div className="ml-auto flex gap-2"><Button size="sm" onClick={start} disabled={busy || oauthBlocked}>{busy ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}启动</Button><Button size="sm" variant="outline" onClick={stop} disabled={busy}><Square className="h-3.5 w-3.5" />停止</Button></div></div>{state?.kind === "chatgpt" && <div className="mt-3 grid grid-cols-3 gap-2"><MiniStatus label="进程" on={state.running} /><MiniStatus label="健康" on={state.healthy} /><MiniStatus label="就绪" on={state.ready} /></div>}{state?.logs?.length > 0 && <details className="mt-3 text-xs"><summary className="cursor-pointer font-medium">最近日志</summary><pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap text-muted-foreground">{state.logs.join("\n")}</pre></details>}</div></CardContent></Card>;
}

function Settings() {
  const [cfg, setCfg] = useState<Record<string, any>>({}); const [audit, setAudit] = useState<any>(null); const [saved, setSaved] = useState(false); const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  useEffect(() => { api.settings("").then((d) => { setCfg(d.settings ?? {}); }); api.oauthMetadataAudit("").then(setAudit).catch(() => {}); }, []);
  const set = (key: string, value: any) => { setCfg((now) => ({ ...now, [key]: value })); setSaved(false); };
  async function save() { setSaving(true); setError(""); const payload = { ...cfg }; for (const key of ["web_access_token", "mcp_access_token", "oauth_password"]) if (!payload[key] || payload[key] === "********") delete payload[key]; try { const result = await api.setSettings("", payload); setCfg(result.settings ?? cfg); setSaved(true); api.oauthMetadataAudit("").then(setAudit).catch(() => {}); } catch (e) { setError(String(e)); } finally { setSaving(false); } }
  return <Page title="Gateway 设置" description="认证、连接方式与公网入口配置。" actions={<Button onClick={save} disabled={saving}>{saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : saved ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}{saved ? "已保存" : "保存更改"}</Button>}>
    {error && <Alert>{error}</Alert>}
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-6">
        <Card><CardHeader><CardTitle className="flex items-center gap-2"><LockKeyhole className="h-4 w-4 text-primary" />访问与认证</CardTitle><CardDescription>Web 与 MCP 凭据相互独立，更改后需重启 Gateway。</CardDescription></CardHeader><CardContent className="space-y-6"><SecurityBlock number="01" title="Web Access Token" description="仅用于登录本控制台。"><SecretSetting value={cfg.web_access_token} onChange={(v) => { set("web_access_token", v); }} placeholder="输入新的 Web Access Token" /></SecurityBlock><Separator /><SecurityBlock number="02" title="MCP 认证" description="保护 /mcp 工具调用。Token 适合本机或 Tunnel；OAuth 需可公开访问的 HTTPS 地址。"><div className="space-y-4"><Field label="认证模式"><Select value={cfg.mcp_auth_mode ?? "token"} onValueChange={(v) => { set("mcp_auth_mode", v); }}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="token">仅 Token（ChatGPT Tunnel 推荐）</SelectItem><SelectItem value="both">Token + OAuth（需公网 issuer）</SelectItem><SelectItem value="oauth">仅 OAuth（需公网 issuer）</SelectItem><SelectItem value="noauth">无认证（仅本机）</SelectItem></SelectContent></Select></Field>{["token", "both"].includes(cfg.mcp_auth_mode ?? "token") && <Field label="MCP Access Token" hint="仅用于 /mcp；不要填入 Web 登录框。"><SecretSetting value={cfg.mcp_access_token} onChange={(v) => { set("mcp_access_token", v); }} placeholder="输入新的 MCP Access Token" /></Field>}{["oauth", "both"].includes(cfg.mcp_auth_mode) && <Field label="OAuth 授权密码" hint="连接时在授权页输入。"><SecretSetting value={cfg.oauth_password} onChange={(v) => { set("oauth_password", v); }} placeholder="输入新的 OAuth 授权密码" /></Field>}<Field label="固定公网 URL" hint="OAuth 需要这里的固定 HTTPS 根地址。"><Input value={cfg.public_url ?? ""} onChange={(e) => { set("public_url", e.target.value); }} placeholder="https://example.com" /></Field><div className="flex items-center justify-between rounded-lg border p-3"><div><Label>OAuth 回调保护（高级）</Label><p className="mt-1 text-xs text-muted-foreground">仅允许 https://chatgpt.com/connector/oauth/*。</p></div><Switch checked={cfg.oauth_callback_protection ?? false} onCheckedChange={(v) => { set("oauth_callback_protection", v); }} /></div></div></SecurityBlock></CardContent></Card>
        <ChatGptMcpTunnel cfg={cfg} set={set} />

      </div>
      <div className="space-y-4 xl:sticky xl:top-24 xl:h-fit"><Card><CardHeader><CardTitle>OAuth Metadata 自检</CardTitle><CardDescription>检查当前运行实例的 OAuth 配置是否完整。</CardDescription></CardHeader><CardContent className="space-y-3"><Badge variant={audit?.complete ? "success" : audit?.enabled ? "warning" : "secondary"}>{audit?.complete ? "配置完整" : audit?.enabled ? "需要修复" : "OAuth 未启用"}</Badge>{audit?.issues?.map((issue: string) => <p key={issue} className="text-xs leading-5 text-destructive">{issue}</p>)}</CardContent></Card><Alert tone="warning">认证类改动需重启 Gateway 才会生效；修改 Web Token 后需重新登录。</Alert></div>
    </div>
  </Page>;
}

function McpAudit() {
  const [data, setData] = useState<{ records: Array<{ timestamp: string; tool: string; arguments: Record<string, unknown>; success: boolean; durationMs: number; result: unknown; error: string | null }>; count: number; maxRecords: number } | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<{ timestamp: string; tool: string; arguments: Record<string, unknown>; success: boolean; durationMs: number; result: unknown; error: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = () => api.mcpAudit("").then((value) => { setData(value); }).catch((e) => { setError(String(e)); });
  useEffect(() => { load(); const timer = setInterval(load, 1500); return () => { clearInterval(timer); }; }, []);
  const records = (data?.records ?? []).filter((record) => {
    const needle = query.trim().toLowerCase();
    return !needle || record.tool.toLowerCase().includes(needle) || JSON.stringify(record.arguments).toLowerCase().includes(needle) || JSON.stringify(record.result).toLowerCase().includes(needle) || (record.error ?? "").toLowerCase().includes(needle);
  });
  async function clear() { setBusy(true); setError(""); try { await api.clearMcpAudit(""); setSelected(null); await load(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <Page title="MCP 调用审计" description="查看当前 Gateway 进程内最近的 MCP tool 调用；不持久化，最多保留 1000 条。" actions={<Button variant="outline" onClick={clear} disabled={busy || !data?.count}><Trash2 className="h-4 w-4" />清空</Button>}>
    {error && <Alert>{error}</Alert>}
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center"><div><CardTitle>调用记录</CardTitle><CardDescription>{data?.count ?? 0} / {data?.maxRecords ?? 1000} 条，按最新调用排序</CardDescription></div><div className="relative sm:ml-auto sm:w-80"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><Input aria-label="筛选 MCP 调用" value={query} onChange={(e) => { setQuery(e.target.value); }} placeholder="按 tool、参数或结果筛选" className="pl-9" /></div></div>
      </CardHeader>
      <CardContent className="p-0">
        {records.length === 0 ? <Empty icon={Search} title={query ? "没有匹配记录" : "暂无 MCP tool 调用"} detail={query ? "调整筛选条件后重试。" : "调用 MCP tool 后，记录会立即出现在这里。"} /> : <div className="divide-y">{records.map((record, index) => <button type="button" key={`${record.timestamp}-${record.tool}-${index}`} onClick={() => { setSelected(record); }} className={cn("block w-full px-5 py-4 text-left transition-colors hover:bg-accent/60", selected === record && "bg-accent")}><div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"><div className="min-w-0"><div className="flex items-center gap-2"><Badge variant={record.success ? "success" : "destructive"}>{record.success ? "成功" : "失败"}</Badge><code className="truncate text-sm font-semibold">{auditTitle(record.tool, record.arguments)}</code></div><p className="mt-1 truncate text-xs text-muted-foreground">{formatAuditTime(record.timestamp)}</p></div><span className="text-xs text-muted-foreground">{record.durationMs.toFixed(1)} ms</span></div></button>)}</div>}
      </CardContent>
    </Card>
    {selected && <div className="fixed inset-0 z-50" role="presentation"><button type="button" aria-label="关闭详情" className="absolute inset-0 bg-black/30" onClick={() => { setSelected(null); }} /><aside role="dialog" aria-modal="true" aria-label="MCP 调用详情" className="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l bg-background shadow-2xl"><div className="flex items-start gap-4 border-b p-5"><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><Badge variant={selected.success ? "success" : "destructive"}>{selected.success ? "成功" : "失败"}</Badge><code className="truncate text-sm font-semibold">{auditTitle(selected.tool, selected.arguments)}</code></div><p className="mt-1 text-xs text-muted-foreground">{formatAuditTime(selected.timestamp)} · {selected.durationMs.toFixed(1)} ms</p></div><Button variant="ghost" size="icon" aria-label="关闭详情" onClick={() => { setSelected(null); }}><X className="h-4 w-4" /></Button></div><div className="flex-1 space-y-5 overflow-y-auto p-5"><AuditJson title="Arguments" value={selected.arguments} /><AuditJson title="Result" value={selected.result} />{selected.error && <AuditJson title="Error" value={selected.error} />}</div></aside></div>}
  </Page>;
}
function AuditJson({ title, value }: { title: string; value: unknown }) { let text: string; try { text = JSON.stringify(value, null, 2); } catch { text = String(value); } return <div>{title && <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>}<pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs leading-5">{text}</pre></div>; }
function formatAuditTime(timestamp: string): string { const date = new Date(timestamp); return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" }); }
function auditTitle(tool: string, arguments_: Record<string, unknown>): string { const priority = ["name", "id", "path", "url", "query", "command", "text", "selector", "filePath", "pageId"]; const key = priority.find((candidate) => Object.prototype.hasOwnProperty.call(arguments_, candidate)) ?? Object.keys(arguments_)[0]; if (!key) return tool; let value: string; try { value = typeof arguments_[key] === "string" ? arguments_[key] : JSON.stringify(arguments_[key]); } catch { value = String(arguments_[key]); } const preview = `${key}=${value}`; return `${tool} · ${preview.length > 80 ? `${preview.slice(0, 77)}…` : preview}`; }
function Brand({ inverse = false }: { inverse?: boolean }) { return <div className={cn("flex h-16 items-center gap-3 px-5", inverse && "px-0")}><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm"><Bot className="h-5 w-5" /></div><div><p className={cn("text-sm font-semibold tracking-tight", inverse && "text-white")}>ChatCodex</p><p className={cn("text-[11px] text-muted-foreground", inverse && "text-zinc-400")}>Local agent gateway</p></div></div>; }
function Splash() { return <div className="flex min-h-screen items-center justify-center bg-background"><div className="text-center"><div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground"><Bot className="h-5 w-5" /></div><RefreshCw className="mx-auto mt-5 h-4 w-4 animate-spin text-muted-foreground" /></div></div>; }
function Page({ title, description, actions, children }: { title: string; description: string; actions?: React.ReactNode; children: React.ReactNode }) { return <section><div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><h1 className="text-2xl font-semibold tracking-tight">{title}</h1><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>{actions}</div>{children}</section>; }
function Field({ label, hint, className, children }: { label: string; hint?: string; className?: string; children: React.ReactNode }) { return <div className={cn("space-y-2", className)}><Label>{label}</Label>{children}{hint && <p className="text-xs leading-5 text-muted-foreground">{hint}</p>}</div>; }
function SecretInput({ value, setValue, placeholder }: { value: string; setValue(v: string): void; placeholder: string }) { const [show, setShow] = useState(false); return <div className="relative"><Input type={show ? "text" : "password"} value={value} onChange={(e) => { setValue(e.target.value); }} placeholder={placeholder} className="pr-10 font-mono text-xs" /><Button type="button" variant="ghost" size="icon" className="absolute right-0 top-0 h-9 w-9" onClick={() => { setShow(!show); }}>{show ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</Button></div>; }
function SecretSetting({ value, onChange, placeholder }: { value: string; onChange(v: string): void; placeholder: string }) { const configured = value === "********"; return <SecretInput value={configured ? "" : (value ?? "")} setValue={onChange} placeholder={configured ? "已配置 · 留空保持现值" : placeholder} />; }
function SecurityBlock({ number, title, description, children }: { number: string; title: string; description: string; children: React.ReactNode }) { return <div className="grid gap-4 md:grid-cols-[180px_1fr]"><div><span className="font-mono text-xs text-primary">{number}</span><p className="mt-1 text-sm font-semibold">{title}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p></div><div>{children}</div></div>; }
function Boundary({ icon: Icon, title, value, detail }: { icon: React.ElementType; title: string; value: string; detail: string }) { return <div className="flex items-center gap-3 rounded-lg border p-3"><Icon className="h-4 w-4 text-primary" /><div className="min-w-0"><p className="text-sm font-medium">{title} <span className="text-muted-foreground">· {value}</span></p><p className="text-xs text-muted-foreground">{detail}</p></div></div>; }
function StatusLine({ label, on }: { label: string; on?: boolean }) { return <div className="flex items-center gap-2 py-1 text-xs"><span className={cn("h-2 w-2 rounded-full", on ? "bg-emerald-500" : "bg-muted-foreground/40")} /><span className="text-muted-foreground">{label}</span><span className="ml-auto font-medium">{on ? "在线" : "离线"}</span></div>; }
function MiniStatus({ label, on }: { label: string; on: boolean }) { return <div className="rounded-lg border p-2 text-center"><div className={cn("mx-auto mb-1 h-1.5 w-1.5 rounded-full", on ? "bg-emerald-500" : "bg-muted-foreground/40")} /><p className="text-[11px] text-muted-foreground">{label}</p></div>; }
function CopyValue({ value }: { value: string }) { const [copied, setCopied] = useState(false); return <div className="flex items-center gap-2 rounded-lg border bg-muted/40 p-2 pl-3"><code className="min-w-0 flex-1 break-all text-xs">{value}</code><Button size="icon" variant="ghost" className="shrink-0" onClick={async () => { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => { setCopied(false); }, 1200); }}>{copied ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}</Button></div>; }
function Empty({ icon: Icon, title, detail, action }: { icon: React.ElementType; title: string; detail: string; action?: React.ReactNode }) { return <div className="flex flex-col items-center px-4 py-8 text-center"><div className="mb-3 rounded-full bg-muted p-3 text-muted-foreground"><Icon className="h-5 w-5" /></div><p className="text-sm font-medium">{title}</p><p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">{detail}</p>{action && <div className="mt-4">{action}</div>}</div>; }
function Alert({ tone = "error", children }: { tone?: "error" | "warning"; children: React.ReactNode }) { return <div role="alert" className={cn("mb-4 rounded-lg border p-3 text-sm leading-6", tone === "warning" ? "border-amber-500/20 bg-amber-500/5 text-amber-800 dark:text-amber-200" : "border-destructive/20 bg-destructive/5 text-destructive")}>{children}</div>; }
function Loading({ text }: { text: string }) { return <div className="flex items-center gap-2 text-sm text-muted-foreground"><RefreshCw className="h-4 w-4 animate-spin" />{text}</div>; }
const mcpUrl = (url: string) => `${url.replace(/\/+$/, "")}/mcp`;

createRoot(document.getElementById("root")!).render(<App />);
