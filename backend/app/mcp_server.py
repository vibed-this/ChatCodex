"""Full-access MCP gateway: no workspace, no approval gating."""
from __future__ import annotations

import ipaddress
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
    return {
        "read_file": obj({"path": string, "encoding": string, "sizeBytes": integer, "startLine": integer, "endLine": integer, "totalLines": integer, "content": string, "dataBase64": string, "truncated": boolean}, ["path", "encoding", "sizeBytes", "truncated"]),
        "write_file": obj({"path": string, "encoding": string, "bytesWritten": integer, "written": boolean, "changed": boolean, "fileChanges": {"type": "array", "items": string}, "diff": string, "diffTruncated": boolean}, ["path", "encoding", "bytesWritten", "written", "changed", "fileChanges", "diff", "diffTruncated"]),
        "list_dir": obj({"entries": {"type": "array", "items": any_object}}, ["entries"]),
        "search_files": obj({"files": {"type": "array", "items": any_object}}, ["files"]),
        "exec_command": obj({"exitCode": integer, "stdout": string, "stderr": string}, ["exitCode", "stdout", "stderr"]),
        "apply_patch": obj({"applied": boolean, "fileChanges": {"type": "array", "items": string}, "diff": string, "diffTruncated": boolean}, ["applied", "fileChanges"]),
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

    @mcp.tool("read_file", description="Read any file on the host (full access).", meta={"openai/toolInvocation/invoking": "Reading file", "openai/toolInvocation/invoked": "Read file"}, annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def read_file(ctx: Context, path: str, startLine: int = 1, endLine: Optional[int] = None, maxChars: int = 100_000) -> dict[str, Any]:
        try:
            return await orch.read_file(path, startLine, endLine, maxChars)
        except Exception as exc:
            raise as_tool_error(exc) from exc

    @mcp.tool("write_file", description="Write UTF-8 text to any host path (full access).", meta={"openai/toolInvocation/invoking": "Writing file", "openai/toolInvocation/invoked": "File written"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False})
    async def write_file(ctx: Context, path: str, content: str) -> dict[str, Any]:
        try:
            return await orch.write_file(path, content)
        except Exception as exc:
            raise as_tool_error(exc) from exc

    @mcp.tool("list_dir", description="List any directory on the host.", meta={"openai/toolInvocation/invoking": "Listing directory", "openai/toolInvocation/invoked": "Listed directory"}, annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def list_dir(ctx: Context, path: Optional[str] = None) -> dict[str, Any]:
        try:
            return await orch.list_dir(path or "")
        except Exception as exc:
            raise as_tool_error(exc) from exc

    @mcp.tool("search_files", description="Fuzzy-search files on the host.", meta={"openai/toolInvocation/invoking": "Searching files", "openai/toolInvocation/invoked": "Searched files"}, annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def search_files(ctx: Context, query: str, path: Optional[str] = None) -> dict[str, Any]:
        try:
            return await orch.search_files(query, path or "")
        except Exception as exc:
            raise as_tool_error(exc) from exc

    @mcp.tool("exec_command", description="Execute any argv command on the host (full access, dangerFullAccess).", meta={"openai/toolInvocation/invoking": "Running command", "openai/toolInvocation/invoked": "Command finished"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
    async def exec_command(ctx: Context, command: list[str], cwd: Optional[str] = None, timeoutMs: Optional[int] = None, requireEscalated: bool = False, justification: Optional[str] = None) -> dict[str, Any]:
        if timeoutMs is not None and (isinstance(timeoutMs, bool) or timeoutMs < 0):
            raise ToolError("timeoutMs must be a non-negative integer")
        try:
            return await orch.exec(command, cwd or "", timeoutMs)
        except Exception as exc:
            raise as_tool_error(exc) from exc

    @mcp.tool("apply_patch", description="Apply a Codex-format patch (full access).", meta={"openai/toolInvocation/invoking": "Applying patch", "openai/toolInvocation/invoked": "Patch applied"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False})
    async def apply_patch(ctx: Context, patch: str) -> dict[str, Any]:
        try:
            return await orch.apply_patch(patch)
        except Exception as exc:
            raise as_tool_error(exc) from exc

    @mcp.tool("update_plan", description="Publish the coding plan.", annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def update_plan(ctx: Context, plan: list[dict], explanation: Optional[str] = None) -> dict[str, Any]:
        try:
            return await orch.update_plan(plan, explanation or "")
        except Exception as exc:
            raise as_tool_error(exc) from exc

    @mcp.tool("view_image", description="Open a local image.", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def view_image(ctx: Context, path: str) -> mtypes.CallToolResult:
        try:
            data = await orch.view_image(path)
        except Exception as exc:
            raise as_tool_error(exc) from exc
        return mtypes.CallToolResult(content=[mtypes.TextContent(type="text", text=f"Opened image: {data['path']}"), mtypes.ImageContent(type="image", data=data["dataBase64"], mimeType=data["mimeType"])], structuredContent={k: v for k, v in data.items() if k != "dataBase64"})

    @mcp.tool("request_user_input", description="Prepare one to three non-secret questions for WebChat to ask.", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
    async def request_user_input(ctx: Context, questions: list[dict]) -> dict[str, Any]:
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
        return {"action": "ask_user", "questions": normalized}

    @mcp.tool("browse_dir", description="Browse server directories.", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def browse_dir(path: Optional[str] = None) -> dict[str, Any]:
        return await orch.browse_dir(path or "")

    @mcp.tool("mcp_list_tools", description="List downstream MCP servers and tools (all allowed).", meta={"openai/toolInvocation/invoking": "Listing MCP tools", "openai/toolInvocation/invoked": "Listed MCP tools"}, annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def mcp_list_tools(ctx: Context) -> dict[str, Any]:
        try:
            return await orch.list_mcp_tools()
        except Exception as exc:
            raise as_tool_error(exc) from exc

    @mcp.tool("mcp_call_tool", description="Call a downstream MCP tool (full access, no approval).", meta={"openai/toolInvocation/invoking": "Calling MCP tool", "openai/toolInvocation/invoked": "MCP tool finished"}, annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
    async def mcp_call_tool(ctx: Context, server: str, tool: str, arguments: Optional[dict] = None, annotations: Optional[dict] = None, timeoutMs: Optional[int] = None) -> dict[str, Any]:
        try:
            return await orch.mcp_tool_call(server, tool, arguments or {}, timeoutMs)
        except Exception as exc:
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
