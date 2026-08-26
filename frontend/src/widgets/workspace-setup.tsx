import { useEffect, useMemo, useState } from "react";
import { Check, Folder, Loader2, Maximize2 } from "lucide-react";
import "../styles.css";
import * as OA from "../lib/openai";
import { useHostContext, useIntrinsicHeight, usePrivateCapabilities, useTheme, useToolInput, useToolOutput } from "../lib/hooks";
import { DirBrowser } from "../lib/DirBrowser";
import { ChoiceList, Notice, SurfaceFooter, SurfaceHeader, WidgetShell, resolveSurface } from "../widget-ui";
import { showToast, triggerHaptic } from "../lib/private-openai";
import { mountWidget } from "../lib/mount";

type WorkMode = "plan" | "agent";

const WORK_MODES: Array<{ value: WorkMode; title: string; description: string }> = [
  { value: "agent", title: "Agent", description: "执行任务、修改代码并验证结果" },
  { value: "plan", title: "Plan", description: "先分析并形成实施计划，支持向你追问" },
];

function App() {
  useTheme();
  const host = useHostContext();
  const privateCapabilities = usePrivateCapabilities();
  const output = useToolOutput<any>();
  const suggested = useToolInput<{ cwd?: string; workMode?: WorkMode }>() ?? {};
  const suggestedCwd = suggested.cwd ?? output?.suggestedCwd ?? "";
  const [cwd, setCwd] = useState(suggestedCwd);
  const [browserRoot, setBrowserRoot] = useState(suggestedCwd);
  const [mode, setMode] = useState<WorkMode>("agent");
  const [showBrowser, setShowBrowser] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [started, setStarted] = useState<any>(null);
  const surface = resolveSurface(host.displayMode, host.view);

  useIntrinsicHeight([surface, showBrowser, error, started, mode]);

  useEffect(() => {
    if (!cwd && suggestedCwd) {
      setCwd(suggestedCwd);
      setBrowserRoot(suggestedCwd);
    }
    const next = suggested.workMode ?? output?.suggestedWorkMode;
    if (next === "plan" || next === "agent") setMode(next);
  }, [cwd, output?.suggestedWorkMode, suggested.workMode, suggestedCwd]);

  const ready = started?.conversationId ? started : output?.conversationId ? output : null;
  const recentPaths = useMemo(() => Array.from(new Set([suggestedCwd].filter(Boolean))), [suggestedCwd]);

  async function openConfiguration() {
    try {
      const actual = await OA.requestDisplayMode("fullscreen");
      if (actual !== "fullscreen") setError("当前宿主不支持完整工作区配置视图。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "当前宿主不支持完整工作区配置视图。");
    }
  }

  async function submit() {
    if (!cwd.trim()) {
      setError("请选择工作目录");
      return;
    }
    if (privateCapabilities.haptic) void triggerHaptic("medium");
    setBusy(true);
    setError("");
    try {
      const result = await OA.callTool<any>("save_execution_context", { config: { cwd: cwd || undefined, workMode: mode } });
      if (result?.error) throw new Error(result.message ?? result.error);
      setStarted(result);
      OA.setWidgetState({ conversationId: result?.conversationId, contextId: result?.contextId, contextVersion: result?.contextVersion, cwd, workMode: mode, recentDirectories: recentPaths.slice(0, 5) });
      if (privateCapabilities.toast) void showToast({ level: "success", title: "执行工作区已连接", body: cwd });
      await OA.requestClose();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      if (privateCapabilities.toast) void showToast({ level: "danger", title: "无法保存工作区", body: message });
    } finally {
      setBusy(false);
    }
  }

  if (ready) return <WidgetShell surface="inline"><SurfaceHeader icon={<Check aria-hidden="true" />} title="执行工作区已连接" description="WebChat 可以使用本地执行工具。" /></WidgetShell>;

  return <WidgetShell surface={surface}>
    <SurfaceHeader icon={<Folder aria-hidden="true" />} title="选择执行工作区" description="配置本地目录和执行模式，不再在客户端管理权限策略。" actions={<button type="button" className="widget-icon-button" onClick={openConfiguration}><Maximize2 aria-hidden="true" />完整配置</button>} />
    <div className="surface-body workspace-setup-body">
      <section className="widget-section">
        <label className="widget-label" htmlFor="workspace-cwd">工作目录</label>
        <div className="workspace-path-row"><input id="workspace-cwd" className="widget-input" value={cwd} onChange={(event) => setCwd(event.target.value)} placeholder="C:\\repo" /><button type="button" className="widget-button widget-button-secondary" onClick={() => { setBrowserRoot(cwd); setShowBrowser((current) => !current); }}>{showBrowser ? "收起" : "浏览"}</button></div>
      </section>
      {showBrowser && <DirBrowser initialPath={browserRoot} selectedPath={cwd} recentPaths={recentPaths} onSelect={(path) => { setCwd(path); setShowBrowser(false); }} />}
      <section className="widget-section"><h2 className="widget-section-title">执行模式</h2><ChoiceList label="执行模式" value={mode} choices={WORK_MODES.map((item) => ({ value: item.value, title: item.title, description: item.description }))} onChange={(value) => setMode(value as WorkMode)} /></section>
      {error && <Notice tone="danger" role="alert">{error}</Notice>}
    </div>
    <SurfaceFooter><button type="button" className="widget-button widget-button-primary" disabled={busy} onClick={() => void submit()}>{busy && <Loader2 aria-hidden="true" className="animate-spin" />}保存工作区</button></SurfaceFooter>
  </WidgetShell>;
}

mountWidget(<App />);
