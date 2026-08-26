"""Full-access MCP gateway aligned to opencode tools: read/write/edit/glob/grep/bash/apply_patch."""
from __future__ import annotations

import ipaddress
import json as _json
from typing import Any, Optional

from mcp import types as mtypes
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .config import Settings
from .execution import ExecutionError, ExecutionOrchestrator
from .oauth import Authenticator


def _transport_security(settings: Settings) -> TransportSecuritySettings:
    if settings.mcp_auth_mode == "noauth":
        host = str(settings.host or "").strip().strip("[]").rstrip(".").lower()
        try:
            loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("MCP noauth mode may only bind to a loopback host")
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=[
                "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
                "https://127.0.0.1:*", "https://localhost:*", "https://[::1]:*",
            ],
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


class _Verifier(TokenVerifier):
    def __init__(self, auth: Authenticator):
        self.auth = auth

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        principal = self.auth.authenticate(f"Bearer {token}", "127.0.0.1")
        if not principal:
            return None
        return AccessToken(token=token, client_id=principal.client_id or principal.user_id, scopes=principal.scopes or ["codex"], expires_at=None)


def tool_security_schemes(settings: Settings) -> list[dict[str, Any]]:
    if settings.mcp_auth_mode in ("oauth", "both"):
        return [{"type": "oauth2", "scopes": ["codex"]}]
    return [{"type": "noauth"}]


def _tool_result(data: dict[str, Any], summary: str) -> mtypes.CallToolResult:
    return mtypes.CallToolResult(content=[mtypes.TextContent(type="text", text=summary)], structuredContent=data)


def _dbg_in(name: str, payload: dict[str, Any]) -> None:
    try:
        txt = _json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        txt = str(payload)
    if len(txt) > 4000:
        txt = txt[:4000] + f" ...[truncated {len(txt)-4000} chars]"
    print(f"[mcp] {name} input: {txt}", flush=True)


def _dbg_out(name: str, payload: Any) -> None:
    try:
        txt = _json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        txt = str(payload)
    if len(txt) > 8000:
        txt = txt[:8000] + f" ...[truncated {len(txt)-8000} chars]"
    print(f"[mcp] {name} output: {txt}", flush=True)


def _dbg_err(name: str, err: Exception) -> None:
    print(f"[mcp] {name} error: {err}", flush=True)


def _output_schemas() -> dict[str, dict[str, Any]]:
    def obj(properties: dict[str, Any], required: Optional[list[str]] = None) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
        if required:
            schema["required"] = required
        return schema
    string = {"type": "string"}
    boolean = {"type": "boolean"}
    integer = {"type": "integer"}
    any_object = {"type": "object", "additionalProperties": True}
    nullable_string = {"anyOf": [string, {"type": "null"}]}
    nullable_integer = {"anyOf": [integer, {"type": "null"}]}
    return {
        # 新项目严格对齐：output_schema 与 execution.py 的实际返回值一一对应，additionalProperties:false，无兼容字段
        "read": obj({"title": string, "output": string, "metadata": any_object, "content": string, "entries": {"type": "array", "items": string}, "truncated": boolean, "totalLines": integer, "lineStart": integer, "lineEnd": integer, "totalEntries": integer, "dataBase64": string, "mime": string}, ["title", "output"]),
        "write": obj({"title": string, "output": string, "metadata": any_object, "path": string, "bytesWritten": integer, "written": boolean, "changed": boolean, "diff": string, "diffTruncated": boolean}, ["title", "output", "path", "bytesWritten", "written", "changed"]),
        "edit": obj({"title": string, "output": string, "metadata": any_object, "diff": string, "additions": integer, "deletions": integer}, ["title", "output"]),
        "glob": obj({"title": string, "output": string, "metadata": any_object, "files": {"type": "array", "items": any_object}, "truncated": boolean}, ["title", "output"]),
        "grep": obj({"title": string, "output": string, "metadata": any_object, "matches": integer, "truncated": boolean, "rows": {"type": "array", "items": any_object}}, ["title", "output"]),
        "bash": obj({"title": string, "output": string, "metadata": any_object, "exitCode": nullable_integer, "stdout": string, "stderr": string, "truncated": boolean, "outputPath": nullable_string}, ["title", "output"]),
        "apply_patch": obj({"title": string, "output": string, "metadata": any_object, "diff": string, "files": {"type": "array", "items": any_object}, "applied": boolean, "fileChanges": {"type": "array", "items": string}}, ["title", "output"]),
        "update_plan": obj({"updated": boolean, "explanation": string, "plan": {"type": "array", "items": any_object}}, ["updated", "explanation", "plan"]),
        "view_image": obj({"path": string, "mimeType": string, "sizeBytes": integer}, ["path", "mimeType", "sizeBytes"]),
        "request_user_input": obj({"action": string, "questions": {"type": "array", "items": any_object}}, ["action", "questions"]),
        "browse_dir": obj({"path": string, "parent": nullable_string, "entries": {"type": "array", "items": any_object}, "error": string}, ["path", "entries"]),
        "mcp_list_tools": obj({"servers": {"type": "array", "items": any_object}}, ["servers"]),
        "mcp_call_tool": obj({"server": string, "tool": string, "content": {"type": "array", "items": any_object}, "structuredContent": {"anyOf": [any_object, {"type": "null"}]}, "isError": boolean}, ["server", "tool", "content", "isError"]),
    }


def build_mcp(settings: Settings, orch: ExecutionOrchestrator, approval: Any, auth: Optional[Authenticator] = None) -> FastMCP:
    auth_settings = None
    verifier = None
    if auth is not None and auth.mode != "noauth":
        auth_settings = AuthSettings(issuer_url=settings.public_url, resource_server_url=f"{settings.public_url.rstrip('/')}/mcp", required_scopes=["codex"])
        verifier = _Verifier(auth)
    mcp = FastMCP("chatcodex", stateless_http=True, json_response=True, transport_security=_transport_security(settings), auth=auth_settings, token_verifier=verifier, streamable_http_path="/")

    def as_tool_error(exc: Exception) -> ToolError:
        if isinstance(exc, ExecutionError):
            hint = f". {exc.hint}" if exc.hint else ""
            return ToolError(f"{exc.code}: {exc}{hint}")
        return ToolError(str(exc))

    # ---- opencode-aligned tools ----

    @mcp.tool("read", description="Read a file or directory from the local filesystem. If the path does not exist, an error is returned. Usage: filePath must be absolute. By default returns up to 2000 lines. Use offset (1-indexed) and limit. Contents returned with line numbers as `<line>: <content>`. For directories entries returned one per line with trailing '/' for subdirs. Lines >2000 chars truncated. Can read images/PDFs.", meta={"openai/toolInvocation/invoking": "Reading", "openai/toolInvocation/invoked": "Read"}, annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def read(ctx: Context, filePath: str, offset: Optional[int] = None, limit: Optional[int] = None) -> dict[str, Any]:
        _dbg_in("read", {"filePath": filePath, "offset": offset, "limit": limit})
        try:
            result = await orch.read(filePath, offset, limit)
            _dbg_out("read", result)
            return result
        except Exception as exc:
            _dbg_err("read", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("write", description="Writes a file to the local filesystem. Usage: will overwrite existing file. Prefer edit for existing files. NEVER proactively create docs unless requested. Only use emojis if requested.", meta={"openai/toolInvocation/invoking": "Writing file", "openai/toolInvocation/invoked": "File written"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False})
    async def write(ctx: Context, filePath: str, content: str) -> dict[str, Any]:
        _dbg_in("write", {"filePath": filePath, "content": content[:2000] + ("...[truncated]" if len(content) > 2000 else "")})
        try:
            result = await orch.write(filePath, content)
            _dbg_out("write", result)
            return result
        except Exception as exc:
            _dbg_err("write", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("edit", description="Performs exact string replacements in files. Usage: must read first. Preserve indentation after line-number prefix. Will FAIL if oldString not found or multiple matches. Use replaceAll for renaming.", meta={"openai/toolInvocation/invoking": "Editing file", "openai/toolInvocation/invoked": "Edit applied"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False})
    async def edit(ctx: Context, filePath: str, oldString: str, newString: str, replaceAll: bool = False) -> dict[str, Any]:
        _dbg_in("edit", {"filePath": filePath, "oldString": oldString[:2000], "newString": newString[:2000], "replaceAll": replaceAll})
        try:
            result = await orch.edit(filePath, oldString, newString, replaceAll)
            _dbg_out("edit", result)
            return result
        except Exception as exc:
            _dbg_err("edit", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("glob", description="Fast file pattern matching tool that works with any codebase size. Supports glob patterns like \"**/*.js\" or \"src/**/*.ts\". Returns matching file paths.", meta={"openai/toolInvocation/invoking": "Globbing", "openai/toolInvocation/invoked": "Globbed"}, annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def glob(ctx: Context, pattern: str, path: Optional[str] = None) -> dict[str, Any]:
        _dbg_in("glob", {"pattern": pattern, "path": path})
        try:
            result = await orch.glob(pattern, path)
            _dbg_out("glob", result)
            return result
        except Exception as exc:
            _dbg_err("glob", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("grep", description="Fast content search tool that works with any codebase size. Searches file contents using regex. Supports full regex syntax (e.g. \"log.*Error\", \"function\\\\s+\\\\w+\"). Filter files with include (e.g. \"*.js\"). Returns file paths and line numbers.", meta={"openai/toolInvocation/invoking": "Grepping", "openai/toolInvocation/invoked": "Grep done"}, annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def grep(ctx: Context, pattern: str, path: Optional[str] = None, include: Optional[str] = None) -> dict[str, Any]:
        _dbg_in("grep", {"pattern": pattern, "path": path, "include": include})
        try:
            result = await orch.grep(pattern, path, include)
            _dbg_out("grep", result)
            return result
        except Exception as exc:
            _dbg_err("grep", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("bash", description="Executes a given bash command with optional timeout, ensuring proper handling. All commands run in cwd by default. Use workdir instead of cd. Always quote paths with spaces. If output exceeds limits it is truncated and full output saved to file. Avoid using bash with find/grep/cat/head/tail/sed/awk/echo unless needed - use dedicated tools. Use workdir param not `cd`.", meta={"openai/toolInvocation/invoking": "Running command", "openai/toolInvocation/invoked": "Command finished"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
    async def bash(ctx: Context, command: str, timeout: Optional[int] = None, workdir: Optional[str] = None) -> dict[str, Any]:
        _dbg_in("bash", {"command": command, "timeout": timeout, "workdir": workdir})
        if timeout is not None and (isinstance(timeout, bool) or timeout < 0):
            raise ToolError("timeout must be a non-negative integer")
        try:
            result = await orch.bash(command, timeout, workdir)
            _dbg_out("bash", result)
            return result
        except Exception as exc:
            _dbg_err("bash", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("apply_patch", description="Use apply_patch to edit files. Your patch language is a stripped-down, file-oriented diff format. Envelope: *** Begin Patch ... *** End Patch with headers *** Add File: <path>, *** Delete File: <path>, *** Update File: <path> (+ optional *** Move to: <path>) and hunks with @@ and +/-/  lines.", meta={"openai/toolInvocation/invoking": "Applying patch", "openai/toolInvocation/invoked": "Patch applied"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False})
    async def apply_patch(ctx: Context, patchText: str) -> dict[str, Any]:
        _dbg_in("apply_patch", {"patchText": patchText[:4000] + ("...[truncated]" if len(patchText) > 4000 else "")})
        try:
            result = await orch.apply_patch(patchText)
            _dbg_out("apply_patch", result)
            return result
        except Exception as exc:
            _dbg_err("apply_patch", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("update_plan", description="Publish the coding plan.", annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def update_plan(ctx: Context, plan: list[dict], explanation: Optional[str] = None) -> dict[str, Any]:
        _dbg_in("update_plan", {"plan": plan, "explanation": explanation})
        try:
            result = await orch.update_plan(plan, explanation or "")
            _dbg_out("update_plan", result)
            return result
        except Exception as exc:
            _dbg_err("update_plan", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("view_image", description="Open a local image.", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def view_image(ctx: Context, path: str) -> mtypes.CallToolResult:
        _dbg_in("view_image", {"path": path})
        try:
            data = await orch.view_image(path)
            _dbg_out("view_image", {k: v if k != "dataBase64" else f"<base64 {len(v)} chars>" for k, v in data.items()})
            return mtypes.CallToolResult(content=[mtypes.TextContent(type="text", text=f"Opened image: {data['path']}"), mtypes.ImageContent(type="image", data=data["dataBase64"], mimeType=data["mimeType"])], structuredContent={k: v for k, v in data.items() if k != "dataBase64"})
        except Exception as exc:
            _dbg_err("view_image", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("request_user_input", description="Prepare one to three non-secret questions for WebChat to ask.", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
    async def request_user_input(ctx: Context, questions: list[dict]) -> dict[str, Any]:
        _dbg_in("request_user_input", {"questions": questions})
        if not 1 <= len(questions) <= 3:
            raise ToolError("questions must contain between one and three items")
        normalized = []
        seen = set()
        for index, question in enumerate(questions):
            if question.get("is_secret") or question.get("isSecret"):
                raise ToolError("request_user_input cannot collect secrets")
            question_id = str(question.get("id") or f"question_{index + 1}")
            if not question_id.isidentifier() or question_id.startswith("_") or question_id in seen:
                raise ToolError(f"invalid or duplicate question id: {question_id}")
            seen.add(question_id)
            normalized.append({"id": question_id, "header": str(question.get("header") or ""), "question": str(question.get("question") or question.get("header") or question_id), "options": [{"label": str(option.get("label") or option.get("value") or ""), "description": str(option.get("description") or "")} for option in (question.get("options") or []) if str(option.get("label") or option.get("value") or "")], "is_other": bool(question.get("is_other") or question.get("isOther")), "is_secret": False})
        result = {"action": "ask_user", "questions": normalized}
        _dbg_out("request_user_input", result)
        return result

    @mcp.tool("browse_dir", description="Browse server directories.", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def browse_dir(path: Optional[str] = None) -> dict[str, Any]:
        _dbg_in("browse_dir", {"path": path})
        result = await orch.browse_dir(path or "")
        _dbg_out("browse_dir", result)
        return result

    @mcp.tool("mcp_list_tools", description="List downstream MCP servers and tools (all allowed).", meta={"openai/toolInvocation/invoking": "Listing MCP tools", "openai/toolInvocation/invoked": "Listed MCP tools"}, annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def mcp_list_tools(ctx: Context) -> dict[str, Any]:
        _dbg_in("mcp_list_tools", {})
        try:
            result = await orch.list_mcp_tools()
            _dbg_out("mcp_list_tools", result)
            return result
        except Exception as exc:
            _dbg_err("mcp_list_tools", exc)
            raise as_tool_error(exc) from exc

    @mcp.tool("mcp_call_tool", description="Call a downstream MCP tool (full access, no approval).", meta={"openai/toolInvocation/invoking": "Calling MCP tool", "openai/toolInvocation/invoked": "MCP tool finished"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
    async def mcp_call_tool(ctx: Context, server: str, tool: str, arguments: Optional[dict] = None, annotations: Optional[dict] = None, timeoutMs: Optional[int] = None) -> dict[str, Any]:
        _dbg_in("mcp_call_tool", {"server": server, "tool": tool, "arguments": arguments, "timeoutMs": timeoutMs})
        try:
            result = await orch.mcp_tool_call(server, tool, arguments or {}, timeoutMs)
            _dbg_out("mcp_call_tool", result)
            return result
        except Exception as exc:
            _dbg_err("mcp_call_tool", exc)
            raise as_tool_error(exc) from exc

    def _normalize_tool_contracts(mcp: FastMCP, settings: Settings) -> None:
        from mcp.types import ToolAnnotations
        schemas = _output_schemas()
        for name, tool in mcp._tool_manager._tools.items():  # noqa: SLF001
            if not tool.title:
                tool.title = name.replace("_", " ").title()
            old = tool.annotations or ToolAnnotations()
            read_only = bool(old.readOnlyHint) if old.readOnlyHint is not None else False
            tool.annotations = ToolAnnotations(title=old.title or tool.title, readOnlyHint=read_only, destructiveHint=bool(old.destructiveHint) if old.destructiveHint is not None else not read_only, idempotentHint=bool(old.idempotentHint) if old.idempotentHint is not None else False, openWorldHint=bool(old.openWorldHint) if old.openWorldHint is not None else True)
            tool.meta = dict(tool.meta or {})
            tool.meta.setdefault("securitySchemes", tool_security_schemes(settings))
            if name in schemas:
                tool.output_schema = schemas[name]

    mcp._chatcodex_orch = orch  # noqa: SLF001
    mcp._chatcodex_approval = approval  # noqa: SLF001
    _normalize_tool_contracts(mcp, settings)
    return mcp
