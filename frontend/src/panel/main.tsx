import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bot, ChevronDown, ChevronRight, Check, Gauge, KeyRound, LockKeyhole, LogOut, Menu, Moon, PanelLeftClose, PanelLeftOpen, RefreshCw, Save, Settings2, Square, Sun, Search, Trash2, X, Terminal, Plug, Plus,
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

type Tab = "overview" | "settings" | "external-mcp" | "mcp-audit" | "shells";
const NAV: Array<{ id: Tab; label: string; icon: React.ElementType }> = [
  { id: "overview", label: "概览", icon: Gauge },
  { id: "settings", label: "设置", icon: Settings2 },
  { id: "external-mcp", label: "External MCP", icon: Plug },
  { id: "mcp-audit", label: "MCP 调用审计", icon: Search },
  { id: "shells", label: "Shell 任务", icon: Terminal },
];

function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<any>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);
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
    const load = () => Promise.all([api.overview(""), api.shells("")]).then(([value, shells]) => setOverview({ ...value, shells: { runningCount: shells.shells.filter((shell: ShellRecord) => shell.running).length } })).catch((e) => {
      if (String(e).startsWith("Error: 401")) setAuthenticated(false);
    });
    load(); const timer = window.setInterval(load, 5000); return () => { clearInterval(timer); };
  }, [authenticated]);

  if (authenticated === null) return <Splash />;
  if (!authenticated) return <Login onSuccess={() => { setAuthenticated(true); }} dark={dark} setDark={setDark} />;

  const selectTab = (value: Tab) => { setTab(value); setNavOpen(false); };
  return (
    <div className="min-h-screen bg-muted/35 text-foreground">
      <aside className={cn("fixed inset-y-0 left-0 z-40 flex flex-col overflow-hidden border-r bg-background transition-[width,transform] duration-200", navCollapsed ? "w-16" : "w-64", navOpen ? "translate-x-0" : "-translate-x-full", "lg:translate-x-0")}>
        <div className={cn("flex items-center p-3", navCollapsed ? "justify-center" : "justify-between")}>
          {!navCollapsed && <Brand />}
          <Button variant="ghost" size="icon" aria-label={navCollapsed ? "展开侧边栏" : "折叠侧边栏"} onClick={() => { setNavCollapsed(!navCollapsed); }}>
            {navCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </Button>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-4">
          {!navCollapsed && <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[.14em] text-muted-foreground">Workspace</p>}
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => { selectTab(id); }} aria-label={label} title={navCollapsed ? label : undefined} className={cn("flex h-10 w-full items-center rounded-lg text-sm font-medium transition-colors", navCollapsed ? "justify-center px-0" : "gap-3 px-3", tab === id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground")}>
              <span className="relative"><Icon className="h-4 w-4" />{id === "shells" && (overview?.shells?.runningCount ?? 0) > 0 && <span className="absolute -right-2 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[9px] font-bold leading-none text-destructive-foreground">{overview.shells.runningCount}</span>}</span>{!navCollapsed && label}
            </button>
          ))}
        </nav>
        <div className={cn("flex items-center gap-1 border-t p-3", navCollapsed && "flex-col")}>
          <Button variant="ghost" size="icon" aria-label="切换主题" onClick={() => { setDark(!dark); }}>{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
          <Button variant="ghost" size={navCollapsed ? "icon" : "default"} className={cn(!navCollapsed && "ml-auto text-muted-foreground")} aria-label="退出" title={navCollapsed ? "退出" : undefined} onClick={async () => { await api.logout(); setAuthenticated(false); }}><LogOut className="h-4 w-4" />{!navCollapsed && "退出"}</Button>
        </div>
      </aside>
      {navOpen && <button aria-label="关闭导航" className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={() => { setNavOpen(false); }} />}

      <div className={cn("transition-[padding] duration-200", navCollapsed ? "lg:pl-16" : "lg:pl-64")}>
        <Button variant="outline" size="icon" className="fixed left-4 top-4 z-20 lg:hidden" aria-label="打开侧边栏" onClick={() => { setNavOpen(true); }}><Menu className="h-5 w-5" /></Button>
        <main className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
          {tab === "overview" && <Overview data={overview} />}
          {tab === "settings" && <Settings />}
          {tab === "external-mcp" && <ExternalMcp />}
          {tab === "mcp-audit" && <McpAudit />}
          {tab === "shells" && <Shells />}
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

function Overview({ data }: { data: any }) {
  if (!data) return <Loading text="读取 Gateway 状态" />;
  return (
    <Page title="运行概览" description="Gateway、MCP 与后台执行状态。">
      <div className="grid gap-6 xl:grid-cols-2">
        <Card><CardHeader><CardTitle>Gateway</CardTitle><CardDescription>当前服务与认证状态。</CardDescription></CardHeader><CardContent className="space-y-3"><Boundary icon={LockKeyhole} title="Web" value="Access Token" detail="控制台登录" /><Boundary icon={KeyRound} title="MCP" value={data.auth?.mcp ?? "—"} detail="MCP 工具调用" /></CardContent></Card>
        <Card><CardHeader><CardTitle>执行</CardTitle><CardDescription>当前 Gateway 的执行能力。</CardDescription></CardHeader><CardContent>{Object.entries(data.executionCapabilities ?? {}).map(([key, value]) => <div key={key} className="flex items-center justify-between border-b py-2 last:border-b-0"><span className="text-sm text-muted-foreground">{key}</span><code className="text-xs">{String(value)}</code></div>)}</CardContent></Card>
      </div>
    </Page>
  );
}

function ExternalMcp() {
  type Server = { id: string; name: string; transport: string; enabled: boolean; url?: string; command?: string; args?: string[]; cwd?: string; env?: Record<string, string>; headers?: Record<string, string>; connected?: boolean; toolCount?: number; lastError?: string };
  const blank = (): Server => ({ id: "", name: "", transport: "streamable_http", enabled: true, url: "", command: "", args: [], cwd: "", env: {}, headers: {} });
  const [servers, setServers] = useState<Server[]>([]);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const load = () => api.externalMcp("").then((data) => { setServers(data.servers ?? []); if ((data.servers ?? []).length) setSelected((value: number) => Math.min(value, data.servers.length - 1)); }).catch((e) => setError(String(e)));
  useEffect(() => { load(); }, []);
  const current = servers[selected];
  function update(patch: Partial<Server>) { setServers((items) => items.map((item, index) => index === selected ? { ...item, ...patch } : item)); setMessage(""); }
  function add() { setServers((items) => [...items, blank()]); setSelected(servers.length); setMessage(""); setError(""); }
  function remove() { if (!current) return; setServers((items) => items.filter((_, index) => index !== selected)); setSelected(Math.max(0, Math.min(selected, servers.length - 2))); }
  function parseJson(value: string, label: string): Record<string, string> { if (!value.trim()) return {}; const parsed = JSON.parse(value); if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error(`${label} must be a JSON object`); return Object.fromEntries(Object.entries(parsed).map(([key, item]) => [key, String(item)])); }
  async function save() {
    setBusy(true); setError(""); setMessage("");
    try {
      const prepared = servers.map((server) => ({ ...server, id: server.id.trim(), name: server.name.trim() || server.id.trim() }));
      if (prepared.some((server) => !server.id)) throw new Error("Every external MCP server needs an id.");
      const result = await api.setExternalMcp("", prepared);
      setServers(result.servers ?? prepared); setMessage("External MCP configuration saved.");
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function test() {
    if (!current) return; setTesting(true); setError(""); setMessage("");
    try {
      const payload = { ...current, headers: parseJson(String((current as any).headersText ?? JSON.stringify(current.headers ?? {})), "headers"), env: parseJson(String((current as any).envText ?? JSON.stringify(current.env ?? {})), "env") };
      const result = await api.testExternalMcp("", payload);
      if (!result.ok) throw new Error(result.error || "Connection failed");
      setMessage(`Connection successful. ${result.tools?.length ?? 0} tool(s) discovered.`);
    } catch (e) { setError(String(e)); } finally { setTesting(false); }
  }
  if (!current) return <Page title="External MCP" description="Connect external MCP servers and federate their tools through ChatCodex." actions={<Button onClick={add}><Plus className="h-4 w-4" />Add server</Button>}><Empty icon={Plug} title="No external MCP servers" detail="Add an MCP server to make its tools available through ChatCodex." /></Page>;
  const headersText = (current as any).headersText ?? JSON.stringify(current.headers ?? {}, null, 2);
  const envText = (current as any).envText ?? JSON.stringify(current.env ?? {}, null, 2);
  return <Page title="External MCP" description="Connect stdio, SSE, or Streamable HTTP MCP servers and expose their tools from the same ChatCodex endpoint." actions={<div className="flex gap-2"><Button variant="outline" onClick={add}><Plus className="h-4 w-4" />Add server</Button><Button onClick={save} disabled={busy}>{busy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}Save</Button></div>}>
    {error && <Alert>{error}</Alert>}{message && <div role="status" className="mb-4 rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm text-primary">{message}</div>}
    <div className="grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)]">
      <Card><CardHeader><CardTitle>Servers</CardTitle><CardDescription>{servers.length} configured</CardDescription></CardHeader><CardContent className="p-2">{servers.map((server, index) => <button key={`${server.id}-${index}`} onClick={() => setSelected(index)} className={cn("w-full rounded-lg p-3 text-left transition", selected === index ? "bg-primary/10" : "hover:bg-accent")}><div className="flex items-center gap-2"><span className={cn("h-2 w-2 rounded-full", server.connected ? "bg-emerald-500" : server.lastError ? "bg-destructive" : "bg-muted-foreground/40")} /><span className="min-w-0 flex-1 truncate text-sm font-medium">{server.name || server.id || "Unnamed server"}</span><Badge variant="outline">{server.transport}</Badge></div><p className="mt-1 truncate pl-4 text-xs text-muted-foreground">{server.toolCount ?? 0} tools{server.lastError ? " · error" : ""}</p></button>)}</CardContent></Card>
      <Card><CardHeader><div className="flex items-start justify-between gap-4"><div><CardTitle>{current.name || current.id || "New server"}</CardTitle><CardDescription>Server configuration stays local to the ChatCodex Gateway.</CardDescription></div><Button variant="ghost" size="icon" aria-label="Remove server" onClick={remove}><Trash2 className="h-4 w-4" /></Button></div></CardHeader><CardContent className="space-y-5">
        <div className="grid gap-4 md:grid-cols-2"><Field label="ID"><Input value={current.id} onChange={(e) => update({ id: e.target.value })} placeholder="github" className="font-mono" /></Field><Field label="Display name"><Input value={current.name} onChange={(e) => update({ name: e.target.value })} placeholder="GitHub MCP" /></Field></div>
        <Field label="Transport"><Select value={current.transport} onValueChange={(value) => update({ transport: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="streamable_http">Streamable HTTP</SelectItem><SelectItem value="sse">SSE</SelectItem><SelectItem value="stdio">stdio</SelectItem></SelectContent></Select></Field>
        {current.transport === "stdio" ? <div className="grid gap-4 md:grid-cols-2"><Field label="Command"><Input value={current.command ?? ""} onChange={(e) => update({ command: e.target.value })} placeholder="npx" className="font-mono" /></Field><Field label="Arguments" hint='JSON array, e.g. ["-y", "@modelcontextprotocol/server-github"]'><Input value={JSON.stringify(current.args ?? [])} onChange={(e) => { try { update({ args: JSON.parse(e.target.value) }); } catch { update({ args: e.target.value.split(/\s+/).filter(Boolean) }); } }} className="font-mono text-xs" /></Field><Field label="Working directory"><Input value={current.cwd ?? ""} onChange={(e) => update({ cwd: e.target.value })} placeholder="Optional" /></Field></div> : <Field label="Server URL"><Input value={current.url ?? ""} onChange={(e) => update({ url: e.target.value })} placeholder="https://example.com/mcp" className="font-mono" /></Field>}
        <div className="grid gap-4 md:grid-cols-2"><Field label="HTTP headers" hint="JSON object. Values may contain credentials; they are masked after save."><textarea value={headersText} onChange={(e) => update({ headers: (() => { try { return parseJson(e.target.value, "headers"); } catch { return current.headers ?? {}; } })(), ...( { headersText: e.target.value } as any) })} className="min-h-32 w-full rounded-md border bg-background px-3 py-2 font-mono text-xs" /></Field><Field label="stdio environment" hint="JSON object. Values may contain credentials; they are masked after save."><textarea value={envText} onChange={(e) => update({ env: (() => { try { return parseJson(e.target.value, "env"); } catch { return current.env ?? {}; } })(), ...( { envText: e.target.value } as any) })} className="min-h-32 w-full rounded-md border bg-background px-3 py-2 font-mono text-xs" /></Field></div>
        <div className="flex items-center justify-between rounded-lg border p-3"><div><Label>Enabled</Label><p className="mt-1 text-xs text-muted-foreground">Enabled servers are connected on demand and their tools are exposed as <code>server__tool</code>.</p></div><Switch checked={current.enabled} onCheckedChange={(value) => update({ enabled: value })} /></div>
        {current.lastError && <Alert>{current.lastError}</Alert>}
        <div className="flex gap-2"><Button variant="outline" onClick={test} disabled={testing}>{testing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Plug className="h-4 w-4" />}Test connection</Button><Badge variant={current.connected ? "success" : "secondary"} className="self-center">{current.connected ? `${current.toolCount ?? 0} tools connected` : "Not connected"}</Badge></div>
      </CardContent></Card>
    </div>
  </Page>;
}

function Settings() {
  const [cfg, setCfg] = useState<Record<string, any>>({}); const [audit, setAudit] = useState<any>(null); const [saved, setSaved] = useState(false); const [saving, setSaving] = useState(false); const [copiedLaunch, setCopiedLaunch] = useState(false); const [error, setError] = useState("");
  useEffect(() => { api.settings("").then((d) => { setCfg(d.settings ?? {}); }); api.oauthMetadataAudit("").then(setAudit).catch(() => {}); }, []);
  const set = (key: string, value: any) => { setCfg((now) => ({ ...now, [key]: value })); setSaved(false); };
  async function save() { setSaving(true); setError(""); const payload = { ...cfg }; for (const key of ["web_access_token", "mcp_access_token", "oauth_password"]) if (!payload[key] || payload[key] === "********") delete payload[key]; try { const result = await api.setSettings("", payload); setCfg(result.settings ?? cfg); setSaved(true); api.oauthMetadataAudit("").then(setAudit).catch(() => {}); } catch (e) { setError(String(e)); } finally { setSaving(false); } }
  const launchCommand = buildLaunchCommand(cfg);
  async function copyLaunchCommand() { await navigator.clipboard.writeText(launchCommand); setCopiedLaunch(true); window.setTimeout(() => setCopiedLaunch(false), 1200); }
  return <Page title="Gateway 设置" description="认证、连接方式与公网入口配置。" actions={<div className="flex gap-2"><Button variant="outline" onClick={copyLaunchCommand} disabled={!launchCommand}><Terminal className="h-4 w-4" />{copiedLaunch ? "Copied" : "Copy launch command"}</Button><Button onClick={save} disabled={saving}>{saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : saved ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}{saved ? "已保存" : "保存更改"}</Button></div>}>
    {error && <Alert>{error}</Alert>}
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-6">
        <Card><CardHeader><CardTitle className="flex items-center gap-2"><LockKeyhole className="h-4 w-4 text-primary" />访问与认证</CardTitle><CardDescription>Web 与 MCP 凭据相互独立，更改后需重启 Gateway。</CardDescription></CardHeader><CardContent className="space-y-6"><SecurityBlock number="01" title="Web Access Token" description="仅用于登录本控制台。"><SecretSetting value={cfg.web_access_token} onChange={(v) => { set("web_access_token", v); }} placeholder="输入新的 Web Access Token" /></SecurityBlock><Separator /><SecurityBlock number="02" title="MCP 认证" description="保护 /mcp 工具调用。Token 适合本机调用；OAuth 需要可公开访问的 HTTPS 地址。"><div className="space-y-4"><Field label="认证模式"><Select value={cfg.mcp_auth_mode ?? "token"} onValueChange={(v) => { set("mcp_auth_mode", v); }}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="token">仅 Token</SelectItem><SelectItem value="both">Token + OAuth（需公网 issuer）</SelectItem><SelectItem value="oauth">仅 OAuth（需公网 issuer）</SelectItem><SelectItem value="noauth">无认证（仅本机）</SelectItem></SelectContent></Select></Field>{["token", "both"].includes(cfg.mcp_auth_mode ?? "token") && <Field label="MCP Access Token" hint="仅用于 /mcp；不要填入 Web 登录框。"><SecretSetting value={cfg.mcp_access_token} onChange={(v) => { set("mcp_access_token", v); }} placeholder="输入新的 MCP Access Token" /></Field>}{["oauth", "both"].includes(cfg.mcp_auth_mode) && <Field label="OAuth 授权密码" hint="连接时在授权页输入。"><SecretSetting value={cfg.oauth_password} onChange={(v) => { set("oauth_password", v); }} placeholder="输入新的 OAuth 授权密码" /></Field>}<Field label="固定公网 URL" hint="OAuth 需要这里的固定 HTTPS 根地址。"><Input value={cfg.public_url ?? ""} onChange={(e) => { set("public_url", e.target.value); }} placeholder="https://example.com" /></Field><div className="flex items-center justify-between rounded-lg border p-3"><div><Label>OAuth 回调保护（高级）</Label><p className="mt-1 text-xs text-muted-foreground">仅允许 https://chatgpt.com/connector/oauth/*。</p></div><Switch checked={cfg.oauth_callback_protection ?? false} onCheckedChange={(v) => { set("oauth_callback_protection", v); }} /></div><div className="flex items-center justify-between rounded-lg border p-3"><div><Label>MCP localhost 免密访问</Label><p className="mt-1 text-xs text-muted-foreground">启用后来自 127.0.0.1 / ::1 的 MCP 请求无需认证。</p></div><Switch checked={cfg.mcp_localhost_noauth ?? false} onCheckedChange={(v) => { set("mcp_localhost_noauth", v); }} /></div></div></SecurityBlock></CardContent></Card>

      </div>
      <div className="space-y-4 xl:sticky xl:top-24 xl:h-fit"><Card><CardHeader><CardTitle>OAuth Metadata 自检</CardTitle><CardDescription>检查当前运行实例的 OAuth 配置是否完整。</CardDescription></CardHeader><CardContent className="space-y-3"><Badge variant={audit?.complete ? "success" : audit?.enabled ? "warning" : "secondary"}>{audit?.complete ? "配置完整" : audit?.enabled ? "需要修复" : "OAuth 未启用"}</Badge>{audit?.issues?.map((issue: string) => <p key={issue} className="text-xs leading-5 text-destructive">{issue}</p>)}</CardContent></Card><Alert tone="warning">认证类改动需重启 Gateway 才会生效；修改 Web Token 后需重新登录。</Alert></div>
    </div>
  </Page>;
}

type AuditRecord = { timestamp: string; tool: string; arguments: Record<string, unknown>; success: boolean; active?: boolean; durationMs: number; result: unknown; error: string | null; callId?: string; parentCallId?: string | null };

function McpAudit() {
  const [data, setData] = useState<{ records: AuditRecord[]; active: AuditRecord[]; count: number; maxRecords: number } | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<AuditRecord | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = () => api.mcpAudit("").then((value) => { setData(value); setSelected((current) => { if (!current?.callId) return current; return [...value.active, ...value.records].find((record) => record.callId === current.callId) ?? null; }); }).catch((e) => { setError(String(e)); });
  useEffect(() => { load(); const timer = setInterval(load, 1500); return () => { clearInterval(timer); }; }, []);
  const matches = (record: AuditRecord) => {
    const needle = query.trim().toLowerCase();
    return !needle || record.tool.toLowerCase().includes(needle) || JSON.stringify(record.arguments).toLowerCase().includes(needle) || JSON.stringify(record.result).toLowerCase().includes(needle) || (record.error ?? "").toLowerCase().includes(needle);
  };
  const allRecords = [...(data?.active ?? []), ...(data?.records ?? [])];
  const childrenByParent = new Map<string, AuditRecord[]>();
  for (const record of allRecords) {
    if (!record.parentCallId || !matches(record)) continue;
    const children = childrenByParent.get(record.parentCallId) ?? [];
    children.push(record);
    childrenByParent.set(record.parentCallId, children);
  }
  for (const children of childrenByParent.values()) children.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  const roots = allRecords.filter((record) => !record.parentCallId && (matches(record) || (record.callId ? (childrenByParent.get(record.callId) ?? []).length > 0 : false)));
  function toggle(record: AuditRecord) {
    if (!record.callId) return;
    setExpanded((current) => { const next = new Set(current); if (next.has(record.callId!)) next.delete(record.callId!); else next.add(record.callId!); return next; });
  }
  async function clear() { setBusy(true); setError(""); try { await api.clearMcpAudit(""); setSelected(null); setExpanded(new Set()); await load(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <Page title="MCP 调用审计" description="查看当前 Gateway 进程内最近的 MCP tool 调用；batch_call 会将内部调用折叠到批次中。" actions={<Button variant="outline" onClick={clear} disabled={busy || !data?.count}><Trash2 className="h-4 w-4" />清空</Button>}>
    {error && <Alert>{error}</Alert>}
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center"><div><CardTitle>调用记录</CardTitle><CardDescription>{data?.count ?? 0} / {data?.maxRecords ?? 1000} 条原始记录，界面按批次聚合</CardDescription></div><div className="relative sm:ml-auto sm:w-80"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><Input aria-label="筛选 MCP 调用" value={query} onChange={(e) => { setQuery(e.target.value); }} placeholder="按 tool、参数或结果筛选" className="pl-9" /></div></div>
      </CardHeader>
      <CardContent className="p-0">
        {roots.length === 0 ? <Empty icon={Search} title={query ? "没有匹配记录" : "暂无 MCP tool 调用"} detail={query ? "调整筛选条件后重试。" : "调用 MCP tool 后，记录会立即出现在这里。"} /> : <div className="divide-y">{roots.map((record, index) => { const children = record.callId ? (childrenByParent.get(record.callId) ?? []) : []; const isExpanded = !!record.callId && expanded.has(record.callId); return <div key={`${record.timestamp}-${record.tool}-${index}`}><div className="flex items-center"><button type="button" onClick={() => { if (record.tool === "batch_call" && children.length > 0) toggle(record); else setSelected(record); }} className={cn("min-w-0 flex-1 px-5 py-4 text-left transition-colors hover:bg-accent/60", selected === record && "bg-accent")}><div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"><div className="min-w-0"><div className="flex items-center gap-2"><Badge variant={record.active ? "warning" : record.success ? "success" : "destructive"}>{record.active ? "执行中" : record.success ? "成功" : "失败"}</Badge><code className="truncate text-sm font-semibold">{record.tool === "batch_call" ? batchToolSummary(record.arguments) : auditTitle(record.tool, record.arguments)}</code>{children.length > 0 && <span className="text-xs text-muted-foreground">{children.length} 个子调用</span>}</div><p className="mt-1 truncate text-xs text-muted-foreground">{formatAuditTime(record.timestamp)}</p></div><span className="text-xs text-muted-foreground">{auditDuration(record)}</span></div></button>{children.length > 0 && <Button variant="ghost" size="icon" className="mr-3" aria-label={isExpanded ? "收起子调用" : "展开子调用"} onClick={() => { toggle(record); }}>{isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</Button>}</div>{isExpanded && <div className="border-t bg-muted/20">{children.map((child, childIndex) => <button type="button" key={`${child.timestamp}-${child.tool}-${childIndex}`} onClick={() => { setSelected(child); }} className={cn("flex w-full items-center gap-3 border-b px-5 py-3 pl-12 text-left last:border-b-0 hover:bg-accent/60", selected === child && "bg-accent")}><span className="text-muted-foreground">↳</span><Badge variant={child.active ? "warning" : child.success ? "success" : "destructive"}>{child.active ? "执行中" : child.success ? "成功" : "失败"}</Badge><code className="min-w-0 flex-1 truncate text-xs font-semibold">{auditTitle(child.tool, child.arguments)}</code><span className="text-xs text-muted-foreground">{auditDuration(child)}</span></button>)}</div>}</div>; })}</div>}
      </CardContent>
    </Card>
    {selected && <div className="fixed inset-0 z-50" role="presentation"><button type="button" aria-label="关闭详情" className="absolute inset-0 bg-black/30" onClick={() => { setSelected(null); }} /><aside role="dialog" aria-modal="true" aria-label="MCP 调用详情" className="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l bg-background shadow-2xl"><div className="flex items-start gap-4 border-b p-5"><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><Badge variant={selected.active ? "warning" : selected.success ? "success" : "destructive"}>{selected.active ? "执行中" : selected.success ? "成功" : "失败"}</Badge><code className="truncate text-sm font-semibold">{auditTitle(selected.tool, selected.arguments)}</code></div><p className="mt-1 text-xs text-muted-foreground">{formatAuditTime(selected.timestamp)} · {formatDuration(selected.durationMs)}</p></div><Button variant="ghost" size="icon" aria-label="关闭详情" onClick={() => { setSelected(null); }}><X className="h-4 w-4" /></Button></div><div className="flex-1 space-y-5 overflow-y-auto p-5"><AuditJson title="Arguments" value={selected.arguments} />{selected.active ? <Loading text="tool 执行中..." /> : <AuditJson title="Result" value={selected.result} />}{selected.error && <AuditJson title="Error" value={selected.error} />}</div></aside></div>}
  </Page>;
}
type ShellRecord = { shellId: string; pid: number | null; command: string; outputPath: string; running: boolean; exitCode: number | null; timedOut: boolean; terminationReason: string; terminationDetail?: string; startedAt: number; finishedAt: number | null };
type ShellWait = { waitId: string; shellId: string; timeout: number | null; startedAt: number; cancelable: boolean };

function Shells() {
  const [data, setData] = useState<{ shells: ShellRecord[]; waits: ShellWait[] } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [waitReason, setWaitReason] = useState("");
  const [cancelTarget, setCancelTarget] = useState<ShellWait | null>(null);
  const load = () => api.shells("").then(setData).catch((e) => { setError(String(e)); });
  useEffect(() => { load(); const timer = setInterval(load, 1000); return () => { clearInterval(timer); }; }, []);
  async function kill(shellId: string) {
    setBusy((current) => new Set(current).add(`shell:${shellId}`));
    try { await api.killShell("", shellId); await load(); } catch (e) { setError(String(e)); }
    finally { setBusy((current) => { const next = new Set(current); next.delete(`shell:${shellId}`); return next; }); }
  }
  async function cancelWait() {
    if (!cancelTarget) return;
    const wait = cancelTarget;
    setBusy((current) => new Set(current).add(`wait:${wait.waitId}`));
    try { await api.cancelShellWait("", wait.waitId, waitReason); setCancelTarget(null); setWaitReason(""); await load(); } catch (e) { setError(String(e)); }
    finally { setBusy((current) => { const next = new Set(current); next.delete(`wait:${wait.waitId}`); return next; }); }
  }
  return <Page title="Shell 任务" description="查看当前后台 Shell、正在进行的 wait，并从管理页面安全终止进程或等待。">
    {error && <Alert>{error}</Alert>}
    <div className="grid gap-6">
      <Card>
        <CardHeader><div className="flex items-center justify-between gap-3"><div><CardTitle>正在执行的 Shell</CardTitle><CardDescription>{data?.shells.filter((shell) => shell.running).length ?? 0} 个进程运行中</CardDescription></div><Badge variant={data?.shells.some((shell) => shell.running) ? "warning" : "secondary"}>{data?.shells.some((shell) => shell.running) ? "运行中" : "空闲"}</Badge></div></CardHeader>
        <CardContent className="p-0">
          {!data?.shells.length ? <Empty icon={Terminal} title="没有后台 Shell" detail="使用 shell_spawn 创建后台任务后，它们会出现在这里。" /> : <div className="divide-y">{data.shells.map((shell) => <div key={shell.shellId} className="space-y-3 p-5"><div className="flex flex-wrap items-start gap-3"><Badge variant={shell.running ? "warning" : shell.terminationReason === "user_terminated_process" ? "destructive" : "success"}>{shell.running ? "运行中" : shell.terminationReason === "user_terminated_process" ? "用户终止" : "已结束"}</Badge><code className="min-w-0 flex-1 break-all text-sm font-semibold">{shell.command}</code>{shell.running && <Button size="sm" variant="destructive" disabled={busy.has(`shell:${shell.shellId}`)} onClick={() => { void kill(shell.shellId); }}><Square className="h-3.5 w-3.5" />终止进程</Button>}</div><div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2"><div>Shell ID <code>{shell.shellId}</code></div><div>PID <code>{shell.pid ?? "—"}</code></div><div className="sm:col-span-2">输出文件 <code className="break-all">{shell.outputPath}</code></div><div>开始 {formatAuditTime(new Date(shell.startedAt * 1000).toISOString())}</div><div>{shell.running ? "状态：运行中" : `退出码：${shell.exitCode ?? "—"}`}</div></div>{!shell.running && <div className="rounded-lg bg-muted/50 p-3 text-xs">结束理由：<code>{shell.terminationReason}</code>{shell.terminationDetail && <span> · {shell.terminationDetail}</span>}</div>}{data.waits.filter((wait) => wait.shellId === shell.shellId).map((wait) => <div key={wait.waitId} className="rounded-lg border bg-muted/30 p-3"><div className="flex flex-wrap items-center gap-2"><Badge variant="outline">Shell wait</Badge><code className="text-xs">{wait.waitId}</code><span className="text-xs text-muted-foreground">{wait.timeout == null ? "No timeout" : `${wait.timeout} ms timeout`}</span><Button size="sm" variant="outline" className="ml-auto" disabled={busy.has(`wait:${wait.waitId}`)} onClick={() => { setCancelTarget(wait); }}>Cancel wait</Button></div><p className="mt-2 text-xs text-muted-foreground">Started {formatAuditTime(new Date(wait.startedAt * 1000).toISOString())}</p></div>)}</div>)}</div>}
        </CardContent>
      </Card>

    </div>
    {cancelTarget && <div className="fixed inset-0 z-50" role="presentation"><button type="button" aria-label="关闭" className="absolute inset-0 bg-black/30" onClick={() => { setCancelTarget(null); }} /><div role="dialog" aria-modal="true" aria-label="终止 Shell wait" className="absolute left-1/2 top-1/2 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-background p-5 shadow-2xl"><h2 className="text-lg font-semibold">终止等待</h2><p className="mt-1 text-sm text-muted-foreground">仅终止这个 wait，不会终止 Shell 进程。可选填写理由，理由会返回给 MCP 调用方。</p><div className="mt-4 space-y-2"><Label htmlFor="wait-reason">理由（可选）</Label><Input id="wait-reason" autoFocus value={waitReason} onChange={(e) => { setWaitReason(e.target.value); }} placeholder="例如：管理员取消等待" /></div><div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => { setCancelTarget(null); }}>取消</Button><Button variant="destructive" disabled={busy.has(`wait:${cancelTarget.waitId}`)} onClick={() => { void cancelWait(); }}>终止等待</Button></div></div></div>}
  </Page>;
}

function AuditJson({ title, value }: { title: string; value: unknown }) { let text: string; try { text = JSON.stringify(value, null, 2); } catch { text = String(value); } return <div>{title && <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>}<pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs leading-5">{text}</pre></div>; }
function formatDuration(ms: number): string { const value = Math.max(0, ms); if (value < 1000) return `${value.toFixed(1)} ms`; if (value < 60_000) return `${(value / 1000).toFixed(2)} s`; if (value < 3_600_000) return `${Math.floor(value / 60_000)} min ${(value % 60_000 / 1000).toFixed(1)} s`; if (value < 86_400_000) return `${Math.floor(value / 3_600_000)} h ${(value % 3_600_000 / 60_000).toFixed(1)} min`; return `${(value / 86_400_000).toFixed(1)} d`; } function auditDuration(record: AuditRecord): string { if (!record.active) return formatDuration(record.durationMs); const elapsed = Math.max(0, Date.now() - new Date(record.timestamp).getTime()); return formatDuration(Math.max(record.durationMs, elapsed)); }
function formatAuditTime(timestamp: string): string { const date = new Date(timestamp); return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" }); }
function batchToolSummary(arguments_: Record<string, unknown>): string { const calls = Array.isArray(arguments_.calls) ? arguments_.calls : []; const names = calls.map((call) => { if (call && typeof call === "object" && "name" in call && typeof call.name === "string") return call.name; return "?"; }); const parts: string[] = []; for (const name of names) { const previous = parts[parts.length - 1]; if (previous && previous.startsWith(`${name}×`)) { const count = Number(previous.slice(name.length + 1)) + 1; parts[parts.length - 1] = `${name}×${count}`; } else if (previous === name) { parts[parts.length - 1] = `${name}×2`; } else { parts.push(name); } } return `batch_call · ${parts.join("、") || "batch_call"}`; }

function auditTitle(tool: string, arguments_: Record<string, unknown>): string { const priority = ["name", "id", "path", "url", "query", "command", "text", "selector", "filePath", "pageId"]; const key = priority.find((candidate) => Object.prototype.hasOwnProperty.call(arguments_, candidate)) ?? Object.keys(arguments_)[0]; if (!key) return tool; let value: string; try { value = typeof arguments_[key] === "string" ? arguments_[key] : JSON.stringify(arguments_[key]); } catch { value = String(arguments_[key]); } const preview = `${key}=${value}`; return `${tool} · ${preview.length > 80 ? `${preview.slice(0, 77)}…` : preview}`; }
function Brand({ inverse = false }: { inverse?: boolean }) { return <div className={cn("flex h-16 items-center gap-3 px-5", inverse && "px-0")}><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm"><Bot className="h-5 w-5" /></div><div><p className={cn("text-sm font-semibold tracking-tight", inverse && "text-white")}>ChatCodex</p><p className={cn("text-[11px] text-muted-foreground", inverse && "text-zinc-400")}>Local agent gateway</p></div></div>; }
function Splash() { return <div className="flex min-h-screen items-center justify-center bg-background"><div className="text-center"><div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground"><Bot className="h-5 w-5" /></div><RefreshCw className="mx-auto mt-5 h-4 w-4 animate-spin text-muted-foreground" /></div></div>; }
function Page({ title, description, actions, children }: { title: string; description: string; actions?: React.ReactNode; children: React.ReactNode }) { return <section><div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><h1 className="text-2xl font-semibold tracking-tight">{title}</h1><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>{actions}</div>{children}</section>; }
function Field({ label, hint, className, children }: { label: string; hint?: string; className?: string; children: React.ReactNode }) { return <div className={cn("space-y-2", className)}><Label>{label}</Label>{children}{hint && <p className="text-xs leading-5 text-muted-foreground">{hint}</p>}</div>; }
function shellQuote(value: string): string { return "'" + String(value).replace(/'/g, "''") + "'"; }
function buildLaunchCommand(cfg: Record<string, any>): string {
  const args: string[] = ["python", "-m", "app.main"];
  if (cfg.web_access_token && cfg.web_access_token !== "********") args.push("--web-token", shellQuote(String(cfg.web_access_token)));
  const mode = String(cfg.mcp_auth_mode || "token");
  args.push("--mcp-auth-mode", mode);
  if (["token", "both"].includes(mode) && cfg.mcp_access_token && cfg.mcp_access_token !== "********") args.push("--mcp-token", shellQuote(String(cfg.mcp_access_token)));
  return args.join(" ");
}

function SecretInput({ value, setValue, placeholder }: { value: string; setValue(v: string): void; placeholder: string }) { return <Input type="text" value={value} onChange={(e) => { setValue(e.target.value); }} placeholder={placeholder} className="font-mono text-xs" />; }
function SecretSetting({ value, onChange, placeholder }: { value: string; onChange(v: string): void; placeholder: string }) { return <SecretInput value={value ?? ""} setValue={onChange} placeholder={placeholder} />; }
function SecurityBlock({ number, title, description, children }: { number: string; title: string; description: string; children: React.ReactNode }) { return <div className="grid gap-4 md:grid-cols-[180px_1fr]"><div><span className="font-mono text-xs text-primary">{number}</span><p className="mt-1 text-sm font-semibold">{title}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p></div><div>{children}</div></div>; }
function Boundary({ icon: Icon, title, value, detail }: { icon: React.ElementType; title: string; value: string; detail: string }) { return <div className="flex items-center gap-3 rounded-lg border p-3"><Icon className="h-4 w-4 text-primary" /><div className="min-w-0"><p className="text-sm font-medium">{title} <span className="text-muted-foreground">· {value}</span></p><p className="text-xs text-muted-foreground">{detail}</p></div></div>; }
function Empty({ icon: Icon, title, detail, action }: { icon: React.ElementType; title: string; detail: string; action?: React.ReactNode }) { return <div className="flex flex-col items-center px-4 py-8 text-center"><div className="mb-3 rounded-full bg-muted p-3 text-muted-foreground"><Icon className="h-5 w-5" /></div><p className="text-sm font-medium">{title}</p><p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">{detail}</p>{action && <div className="mt-4">{action}</div>}</div>; }
function Alert({ tone = "error", children }: { tone?: "error" | "warning"; children: React.ReactNode }) { return <div role="alert" className={cn("mb-4 rounded-lg border p-3 text-sm leading-6", tone === "warning" ? "border-amber-500/20 bg-amber-500/5 text-amber-800 dark:text-amber-200" : "border-destructive/20 bg-destructive/5 text-destructive")}>{children}</div>; }
function Loading({ text }: { text: string }) { return <div className="flex items-center gap-2 text-sm text-muted-foreground"><RefreshCw className="h-4 w-4 animate-spin" />{text}</div>; }

createRoot(document.getElementById("root")!).render(<App />);
