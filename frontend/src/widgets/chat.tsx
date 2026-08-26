import { useEffect, useRef, useState } from "react";
import { Bot, Maximize2 } from "lucide-react";
import "../styles.css";
import * as OA from "../lib/openai";
import { useHostContext, useIntrinsicHeight, useTheme, useToolOutput } from "../lib/hooks";
import {
  CodeBlock,
  EmptyState,
  Notice,
  Section,
  StatusRow,
  SurfaceHeader,
  WidgetShell,
  resolveSurface,
} from "../widget-ui";
import { mountWidget } from "../lib/mount";

interface ExecutionStatus {
  conversationId?: string;
  contextId?: string;
  contextVersion?: number;
  pending?: boolean;
  context?: { cwd?: string; workMode?: string; version?: number };
  capabilities?: {
    appServerMode?: string;
    standaloneFilesystem?: string;
    remoteFilesystemBoundary?: string;
    eventTransport?: string;
  };
  exitCode?: number;
  stdout?: string;
  stderr?: string;
}

function App() {
  useTheme();
  const host = useHostContext();
  const output = useToolOutput<ExecutionStatus>();
  const persisted = OA.widgetState<ExecutionStatus>() ?? {};
  const [snapshot, setSnapshot] = useState<ExecutionStatus>(output ?? persisted);
  const [error, setError] = useState("");
  const outputRef = useRef(output);
  const surface = resolveSurface(host.displayMode, host.view);
  const context = snapshot.context ?? {};
  const conversationId = snapshot.conversationId ?? output?.conversationId ?? persisted.conversationId ?? "";

  useIntrinsicHeight([surface, snapshot.exitCode, error]);

  useEffect(() => {
    if (!output || output === outputRef.current) return;
    outputRef.current = output;
    setSnapshot((current) => ({ ...current, ...output, conversationId: output.conversationId ?? current.conversationId }));
  }, [output]);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const next = await OA.callTool<ExecutionStatus>("execution_status", conversationId ? { conversationId } : {});
        if (stopped) return;
        setSnapshot((current) => ({ ...current, ...next, exitCode: current.exitCode, stdout: current.stdout, stderr: current.stderr }));
        OA.setWidgetState({ conversationId: next.conversationId, contextId: next.contextId, contextVersion: next.contextVersion, context: next.context, capabilities: next.capabilities });
        setError("");
        timer = window.setTimeout(refresh, next.pending ? 900 : 3500);
      } catch (cause) {
        if (stopped) return;
        setError(cause instanceof Error ? cause.message : String(cause));
        timer = window.setTimeout(refresh, 4000);
      }
    };
    timer = window.setTimeout(refresh, 150);
    return () => { stopped = true; if (timer) window.clearTimeout(timer); };
  }, [conversationId]);

  async function openDetails() {
    try { await OA.requestDisplayMode("fullscreen"); }
    catch { setError("当前宿主无法打开完整执行视图。"); }
  }

  const title = snapshot.exitCode === 0 ? "命令执行完成" : typeof snapshot.exitCode === "number" ? "命令执行失败" : "执行工作区已就绪";
  const description = conversationId ? `WebChat 执行上下文 · v${snapshot.contextVersion ?? context.version ?? 1}` : "正在读取当前 WebChat 执行上下文";

  if (surface === "inline") {
    return <WidgetShell surface="inline" className="chat-widget">
      <SurfaceHeader icon={<Bot aria-hidden="true" />} title={title} description={description} actions={<button type="button" className="widget-icon-button" onClick={openDetails}><Maximize2 aria-hidden="true" />详情</button>} />
      <div className="surface-body activity-summary">
        <CommandResult snapshot={snapshot} />
        {error && <Notice tone="danger" role="alert">状态刷新失败：{error}</Notice>}
      </div>
    </WidgetShell>;
  }

  return <WidgetShell surface={surface} className="chat-widget">
    <SurfaceHeader icon={<Bot aria-hidden="true" />} title={title} description={description} />
    <div className="surface-body chat-fullscreen-grid">
      <section className="activity-timeline" aria-label="执行结果">
        <div className="timeline-heading"><h2>执行状态</h2><span>{snapshot.exitCode === undefined ? "空闲" : "已完成"}</span></div>
        <CommandResult snapshot={snapshot} />
        {error && <Notice tone="danger" role="alert">{error}</Notice>}
      </section>
      <aside className="run-inspector">
        <Section title="执行上下文"><div className="inspector-facts"><Fact label="对话" value={compactId(conversationId)} /><Fact label="目录" value={context.cwd ?? "未配置"} sensitive /><Fact label="工作模式" value={context.workMode ?? "未记录"} /></div></Section>
        <Section title="运行能力"><div className="inspector-facts"><Fact label="App Server" value={snapshot.capabilities?.appServerMode ?? "未知"} /><Fact label="独立文件 RPC" value={snapshot.capabilities?.standaloneFilesystem ?? "未知"} /><Fact label="远端路径边界" value={snapshot.capabilities?.remoteFilesystemBoundary ?? "未知"} /><Fact label="事件" value={snapshot.capabilities?.eventTransport ?? "未知"} /></div></Section>
      </aside>
    </div>
  </WidgetShell>;
}

function CommandResult({ snapshot }: { snapshot: ExecutionStatus }) {
  if (typeof snapshot.exitCode !== "number") return <><StatusRow tone="neutral" title="独立执行通道就绪" detail="等待新的执行结果" /><EmptyState title="暂无命令输出" /></>;
  const succeeded = snapshot.exitCode === 0;
  const output = [snapshot.stdout, snapshot.stderr].filter(Boolean).join("\n");
  return <><StatusRow tone={succeeded ? "success" : "danger"} title={succeeded ? "命令执行完成" : "命令执行失败"} detail={`退出码 ${snapshot.exitCode}`} />{output && <CodeBlock label="命令输出" collapsed>{output}</CodeBlock>}</>;
}

function compactId(value: string) { return !value ? "—" : value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value; }

function Fact({ label, value, sensitive = false }: { label: string; value: string; sensitive?: boolean }) {
  if (sensitive) return <details className="inspector-fact sensitive"><summary><span>{label}</span><strong>显示</strong></summary><code>{value}</code></details>;
  return <div className="inspector-fact"><span>{label}</span><strong>{value}</strong></div>;
}

mountWidget(<App />);
