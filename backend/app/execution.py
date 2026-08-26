"""Full-access execution: no workspace, no approval, direct App Server passthrough."""
from __future__ import annotations

import base64
import difflib
import mimetypes
import os
from typing import Any, Optional


MAX_WIDGET_DIFF_CHARS = 200_000
MCP_TOOL_TIMEOUT_MS = 120_000


class ExecutionError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.hint = hint


def _resolve_full_access(path: str) -> str:
    """Resolve any path without workspace containment checks."""
    if not path:
        return os.path.abspath(os.getcwd())
    # Expand ~ and resolve to absolute; no containment check.
    candidate = os.path.expanduser(path)
    if not os.path.isabs(candidate):
        candidate = os.path.join(os.getcwd(), candidate)
    return os.path.abspath(candidate)


def _write_file_diff(path: str, before: bytes, after: bytes, existed: bool) -> tuple[str, bool]:
    if existed and before == after:
        return "", False
    old_name = f"a/{path}"
    new_name = f"b/{path}"
    header = [f"diff --git {old_name} {new_name}"]
    if not existed:
        header.append("new file mode 100644")
    try:
        before_text = before.decode("utf-8")
        after_text = after.decode("utf-8")
    except UnicodeDecodeError:
        diff = "\n".join([*header, f"Binary files {old_name} and {new_name} differ", ""])
    else:
        body = difflib.unified_diff(
            before_text.splitlines(), after_text.splitlines(),
            fromfile=old_name if existed else "/dev/null",
            tofile=new_name, lineterm="",
        )
        diff = "\n".join([*header, *body, ""])
    if len(diff) <= MAX_WIDGET_DIFF_CHARS:
        return diff, False
    suffix = "\n… Diff truncated for display …\n"
    return diff[:MAX_WIDGET_DIFF_CHARS - len(suffix)] + suffix, True


def _is_missing_file_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    message = str(exc).lower()
    return any(m in message for m in ("no such file", "cannot find the file", "cannot find the path", "os error 2", "找不到文件", "找不到指定的路径"))


class ExecutionOrchestrator:
    """Stateless orchestrator: every tool operates on the host filesystem directly."""

    def __init__(self, settings: Any, appserver: Any, *ignored: Any):
        self.settings = settings
        self.appserver = appserver
        # Keep compatibility attributes accessed elsewhere
        self.store = None
        self.registry = None
        from .operations import OperationRouter
        self.router = OperationRouter(appserver, settings)
        self._carrier = None
        try:
            from .appserver.mcp_carrier import McpCarrier
            self._carrier = McpCarrier(appserver)
        except Exception:
            pass

    # ---- filesystem ----

    async def read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None, max_chars: int = 100_000) -> dict[str, Any]:
        resolved = _resolve_full_access(path)
        result = await self.appserver.fs_read_file(resolved)
        raw = base64.b64decode((result or {}).get("dataBase64") or "")
        try:
            text = raw.decode("utf-8")
            lines = text.splitlines()
            start = max(1, int(start_line or 1))
            end = min(len(lines), int(end_line or len(lines)))
            content = "\n".join(lines[start - 1:end])
            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars]
            return {"path": resolved, "encoding": "utf-8", "sizeBytes": len(raw), "startLine": start, "endLine": end, "totalLines": len(lines), "content": content, "dataBase64": "", "truncated": truncated}
        except UnicodeDecodeError:
            return {"path": resolved, "encoding": "base64", "sizeBytes": len(raw), "startLine": 0, "endLine": 0, "totalLines": 0, "content": "", "dataBase64": base64.b64encode(raw).decode(), "truncated": False}

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        resolved = _resolve_full_access(path)
        encoded = content.encode("utf-8")
        existed = True
        try:
            previous = await self.appserver.fs_read_file(resolved)
            previous_bytes = base64.b64decode((previous or {}).get("dataBase64") or "", validate=True)
        except Exception as exc:
            if not _is_missing_file_error(exc):
                raise ExecutionError("write_file_diff_failed", f"could not read previous file contents: {exc}") from exc
            existed = False
            previous_bytes = b""
        diff, diff_truncated = _write_file_diff(resolved, previous_bytes, encoded, existed)
        changed = not existed or previous_bytes != encoded
        await self.appserver.fs_write_file(resolved, base64.b64encode(encoded).decode())
        return {"conversationId": "", "path": resolved, "encoding": "utf-8", "bytesWritten": len(encoded), "written": True, "changed": changed, "fileChanges": [resolved] if changed else [], "diff": diff, "diffTruncated": diff_truncated}

    async def list_dir(self, path: str = "") -> dict[str, Any]:
        resolved = _resolve_full_access(path) if path else os.path.abspath(os.getcwd())
        return await self.appserver.fs_read_directory(resolved)

    async def search_files(self, query: str, path: str = "") -> dict[str, Any]:
        target = _resolve_full_access(path) if path else os.path.abspath(os.getcwd())
        q = str(query or "").strip()
        if not q:
            # 空查询：直接列目录，避免 fuzzy_search 返回 []
            dir_data = await self.appserver.fs_read_directory(target)
            entries = (dir_data or {}).get("entries") or []
            files = []
            for e in entries[:200]:
                if isinstance(e, dict):
                    p = e.get("path") or e.get("name") or ""
                    is_dir = e.get("isDirectory", False)
                else:
                    p = str(e)
                    is_dir = False
                files.append({"path": str(p), "score": 1.0, "isDirectory": bool(is_dir)})
            return {"files": files, "query": q, "path": target}
        result = await self.appserver.fuzzy_search(q, [target])
        files = (result or {}).get("files") or []
        files.sort(key=lambda item: ("__pycache__" in str(item.get("path", "")).lower() or str(item.get("path", "")).lower().endswith((".pyc", ".pyo")), -float(item.get("score") or 0)))
        if isinstance(result, dict):
            result["files"] = files
        return result

    async def exec(self, command: list[str], cwd: str, timeout_ms: Optional[int]) -> dict[str, Any]:
        if not command or not all(isinstance(p, str) and p for p in command):
            raise ExecutionError("invalid_command", "command must be a non-empty argv array")
        resolved_cwd = _resolve_full_access(cwd) if cwd else os.path.abspath(os.getcwd())
        # Full access: always dangerFullAccess, no sandbox branching
        return await self.appserver.exec_command(command, resolved_cwd, timeout_ms, {"type": "dangerFullAccess"})

    async def apply_patch(self, patch: str) -> dict[str, Any]:
        if not patch.startswith("*** Begin Patch") or "*** End Patch" not in patch:
            raise ExecutionError("invalid_patch", "patch must use Codex apply_patch format")
        # No path containment check in full-access mode; just extract file list for response
        import re
        changes: list[str] = []
        for m in re.finditer(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$|^\*\*\* Move to:\s*(.+?)\s*$", patch, flags=re.MULTILINE):
            candidate = next(g for g in m.groups() if g is not None)
            if candidate not in changes:
                changes.append(candidate)
        if not changes:
            raise ExecutionError("invalid_patch", "patch contains no file operation headers")
        resolver = getattr(self.appserver, "codex_command_for_exec", None)
        executable = resolver() if callable(resolver) else ""
        executable = str(executable or self.settings.codex_command or "codex")
        result = await self.appserver.exec_command([executable, "--codex-run-as-apply-patch", patch], os.path.abspath(os.getcwd()), 120_000, {"type": "dangerFullAccess"})
        exit_code = int((result or {}).get("exitCode", -1))
        if exit_code != 0:
            detail = (result or {}).get("stderr") or (result or {}).get("stdout") or f"Codex apply_patch exited with {exit_code}"
            raise ExecutionError("apply_patch_failed", str(detail)[-4000:])
        diff = patch
        diff_truncated = False
        if len(diff) > MAX_WIDGET_DIFF_CHARS:
            suffix = "\n… Diff truncated for display …\n"
            diff = diff[:MAX_WIDGET_DIFF_CHARS - len(suffix)] + suffix
            diff_truncated = True
        return {"conversationId": "", "applied": True, "fileChanges": changes, "diff": diff, "diffTruncated": diff_truncated}

    async def view_image(self, path: str) -> dict[str, Any]:
        resolved = _resolve_full_access(path)
        data = await self.appserver.fs_read_file(resolved)
        raw = base64.b64decode((data or {}).get("dataBase64") or "")
        mime = mimetypes.guess_type(resolved)[0] or "application/octet-stream"
        if not mime.startswith("image/"):
            raise ExecutionError("not_an_image", f"unsupported image type: {mime}")
        return {"path": resolved, "mimeType": mime, "sizeBytes": len(raw), "dataBase64": base64.b64encode(raw).decode()}

    async def browse_dir(self, path: str = "") -> dict[str, Any]:
        target = os.path.realpath(os.path.abspath(os.path.expanduser(path or os.getcwd())))
        if not os.path.isdir(target):
            return {"path": target, "parent": None, "entries": [], "error": "directory does not exist"}
        entries = []
        try:
            with os.scandir(target) as it:
                for entry in sorted(it, key=lambda x: (not x.is_dir(follow_symlinks=False), x.name.lower()))[:200]:
                    entries.append({"name": entry.name, "path": entry.path, "isDirectory": entry.is_dir(follow_symlinks=False)})
        except OSError as exc:
            return {"path": target, "parent": None, "entries": [], "error": str(exc)}
        parent = os.path.dirname(target)
        return {"path": target, "parent": parent if parent != target else None, "entries": entries}

    # ---- downstream MCP tools: full access, no policy ----

    async def list_mcp_tools(self) -> dict[str, Any]:
        response: dict[str, Any] = {}
        try:
            response = await self.appserver.mcp_server_status_list()
        except Exception:
            if self._carrier is not None:
                try:
                    carrier = await self._carrier.thread_id("__full_access__")
                    response = await self.appserver.mcp_server_status_list(carrier)
                except Exception:
                    response = {}
        servers = (response or {}).get("data") or []
        out: list[dict[str, Any]] = []
        for server in servers:
            name = str(server.get("name") or "")
            raw_tools = server.get("tools") or {}
            tool_items = list(raw_tools.values()) if isinstance(raw_tools, dict) else list(raw_tools or [])
            tools: list[dict[str, Any]] = []
            for tool in tool_items:
                tool_name = str(tool.get("name") or "")
                ann = tool.get("annotations") or {}
                tools.append({"name": tool_name, "description": str(tool.get("description") or ""), "inputSchema": tool.get("inputSchema") or tool.get("input_schema") or {}, "readOnly": bool(ann.get("readOnlyHint")), "policy": "allow"})
            tools.sort(key=lambda x: x["name"])
            out.append({"name": name, "authStatus": str(server.get("authStatus") or ""), "tools": tools})
        out.sort(key=lambda x: x["name"])
        return {"conversationId": "", "servers": out}

    async def mcp_tool_call(self, server: str, tool: str, arguments: Optional[dict], timeout_ms: Optional[int] = None) -> dict[str, Any]:
        effective_timeout = timeout_ms if isinstance(timeout_ms, int) and timeout_ms > 0 else MCP_TOOL_TIMEOUT_MS
        # Always use a shared carrier in full-access mode
        carrier = None
        if self._carrier is not None:
            try:
                carrier = await self._carrier.thread_id("__full_access__")
            except Exception:
                carrier = None
        # Prefer carrier-bound call if available, else direct
        result = None
        if carrier:
            try:
                result = await self.appserver.mcp_tool_call(carrier, server, tool, arguments or {}, timeout=max(1.0, effective_timeout / 1000.0))
            except Exception:
                result = None
        if result is None:
            # Fallback: try without carrier if appserver supports it
            try:
                result = await self.appserver.mcp_tool_call("__full_access__", server, tool, arguments or {}, timeout=max(1.0, effective_timeout / 1000.0))
            except Exception as exc:
                raise ExecutionError("mcp_tool_failed", str(exc)) from exc
        return {"conversationId": "", "server": server, "tool": tool, "content": (result or {}).get("content") or [], "structuredContent": (result or {}).get("structuredContent"), "isError": bool((result or {}).get("isError"))}

    async def update_plan(self, plan: list[dict], explanation: str = "") -> dict[str, Any]:
        statuses = [str(item.get("status") or "pending") for item in plan]
        if any(s not in {"pending", "in_progress", "completed"} for s in statuses):
            raise ExecutionError("invalid_plan", "unsupported plan status")
        if statuses.count("in_progress") > 1:
            raise ExecutionError("invalid_plan", "at most one plan item may be in_progress")
        return {"conversationId": "", "updated": True, "plan": plan, "explanation": explanation}

    # Compatibility shims for legacy callers
    def mcp_tool_policies(self) -> dict[str, str]:
        return {}

    def set_mcp_tool_policy(self, policies: dict[str, str]) -> dict[str, str]:
        return {}
