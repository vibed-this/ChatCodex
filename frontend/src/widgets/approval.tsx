import { useEffect, useState } from "react";
import { Check, ShieldAlert, X } from "lucide-react";
import "../styles.css";
import * as OA from "../lib/openai";
import { useHostContext, useIntrinsicHeight, useTheme, useToolInput, useToolOutput } from "../lib/hooks";
import { Notice, SurfaceFooter, SurfaceHeader, WidgetShell } from "../widget-ui";
import { mountWidget } from "../lib/mount";

function App() {
  useTheme();
  const host = useHostContext();
  const input = useToolInput() ?? {};
  const output = useToolOutput() ?? {};
  const request = input.request ?? input.approval ?? input.params ?? input;
  const requestId = String(request.requestId ?? request.id ?? output.requestId ?? "");
  const title = String(request.title ?? request.kind ?? "需要确认");
  const summary = String(request.summary ?? request.message ?? request.presentation?.message ?? "Codex 请求执行一项可能产生影响的操作。");
  const [busy, setBusy] = useState(false);
  const [terminal, setTerminal] = useState<"approved" | "declined" | null>(null);
  const [error, setError] = useState("");
  useIntrinsicHeight([host.displayMode, terminal, error, summary]);

  useEffect(() => {
    if (String(request.state ?? output.state).toLowerCase() === "resolved") {
      setTerminal(String(request.decision ?? output.decision).toLowerCase().includes("accept") ? "approved" : "declined");
    }
  }, [output.decision, output.state, request.decision, request.state]);

  async function decide(action: "accept" | "decline") {
    if (busy || terminal) return;
    setBusy(true);
    setError("");
    try {
      const prompt = action === "accept"
        ? `确认执行审批请求 ${requestId || "当前请求"}。`
        : `拒绝执行审批请求 ${requestId || "当前请求"}。`;
      await OA.sendFollowUpMessage(prompt);
      setTerminal(action === "accept" ? "approved" : "declined");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法提交审批决定");
    } finally {
      setBusy(false);
    }
  }

  if (terminal) {
    return (
      <WidgetShell surface="inline">
        <SurfaceHeader icon={terminal === "approved" ? <Check aria-hidden="true" /> : <X aria-hidden="true" />} title={terminal === "approved" ? "已批准" : "已拒绝"} description="审批结果已提交。" />
      </WidgetShell>
    );
  }

  return (
    <WidgetShell surface="inline">
      <SurfaceHeader icon={<ShieldAlert aria-hidden="true" />} title={title} description={summary} />
      {requestId && <div className="widget-muted">请求 ID：{requestId}</div>}
      {error && <Notice tone="danger">{error}</Notice>}
      <SurfaceFooter>
        <button type="button" className="widget-button widget-button-secondary" disabled={busy} onClick={() => void decide("decline")}><X aria-hidden="true" />拒绝</button>
        <button type="button" className="widget-button" disabled={busy} onClick={() => void decide("accept")}><Check aria-hidden="true" />批准</button>
      </SurfaceFooter>
    </WidgetShell>
  );
}

mountWidget(<App />);
