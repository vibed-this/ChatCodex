# Copyright (c) 2026 ChatCodex contributors.
"""Full-access MCP gateway aligned to opencode tools: read/write/edit/glob/grep/bash/apply_patch."""

from __future__ import annotations

import ipaddress
import json as _json
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any, TypeVar, cast

from mcp import types as mtypes
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AnyHttpUrl, Field, TypeAdapter

_F = TypeVar("_F", bound=Callable[..., Any])


class ContractFastMCP(FastMCP):
    """FastMCP adapter that exposes the transport-independent tool contracts."""

    def __init__(
        self,
        *args: Any,
        external_mcp: ExternalMcpManager | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.external_mcp = external_mcp

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.external_mcp is not None and self.external_mcp.owns_tool(name):
            return await record_mcp_tool_call(
                AUDIT_LOG,
                name,
                arguments,
                self.external_mcp.call_tool,
            )
        return await record_mcp_tool_call(
            AUDIT_LOG,
            name,
            arguments,
            super().call_tool,
        )

    async def list_tools(self) -> Any:
        tools = await super().list_tools()
        if self.external_mcp is not None:
            tools.extend(await self.external_mcp.list_tools())
        for tool in tools:
            definition = TOOL_DEFINITIONS.get(tool.name)
            if definition is not None:
                tool.inputSchema = definition.input_schema
                tool.description = definition.description
                if definition.output_schema is not None:
                    tool.outputSchema = definition.output_schema
        return tools



from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from app.execution import ExecutionError, ExecutionService

from .audit import AUDIT_LOG, record_mcp_tool_call
from .external import ExternalMcpManager
from .schemas import TOOL_DEFINITIONS

if TYPE_CHECKING:
    from app.config import Settings
    from app.oauth import Authenticator



def _transport_security(settings: Settings) -> TransportSecuritySettings:
    if settings.mcp_auth_mode == "noauth":
        host = str(settings.host or "").strip().strip("[]").rstrip(".").lower()
        try:
            loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            msg = "MCP noauth mode may only bind to a loopback host"
            raise ValueError(msg)
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
                "https://127.0.0.1:*",
                "https://localhost:*",
                "https://[::1]:*",
            ],
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


class _Verifier(TokenVerifier):
    def __init__(self, auth: Authenticator) -> None:
        self.auth = auth

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = self.auth.authenticate(f"Bearer {token}", "127.0.0.1")
        if not principal:
            return None
        # 兼容旧 token：codex 已在 oauth._verify 归一为 tools，此处再做一次兜底
        scopes = principal.scopes or ["tools"]
        scopes = ["tools" if s == "codex" else s for s in scopes]
        # 去重
        seen: set[str] = set()
        canon: list[str] = []
        for s in scopes:
            if s not in seen:
                seen.add(s)
                canon.append(s)
        return AccessToken(
            token=token,
            client_id=principal.client_id or principal.user_id,
            scopes=canon or ["tools"],
            expires_at=None,
        )


def tool_security_schemes(settings: Settings) -> list[dict[str, Any]]:
    if settings.mcp_auth_mode in ("oauth", "both"):
        return [{"type": "oauth2", "scopes": ["tools", "codex"]}]
    return [{"type": "noauth"}]


def _tool_result(data: dict[str, Any], summary: str) -> mtypes.CallToolResult:
    return mtypes.CallToolResult(
        content=[mtypes.TextContent(type="text", text=summary)], structuredContent=data
    )


def _dbg_in(name: str, payload: dict[str, Any]) -> None:
    try:
        txt = _json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        txt = str(payload)
    if len(txt) > 4000:
        txt = txt[:4000] + f" ...[truncated {len(txt) - 4000} chars]"


def _dbg_out(name: str, payload: Any) -> None:
    try:
        txt = _json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        txt = str(payload)
    if len(txt) > 8000:
        txt = txt[:8000] + f" ...[truncated {len(txt) - 8000} chars]"


def _dbg_err(name: str, err: Exception) -> None:
    pass


def build_mcp(
    settings: Settings,
    orch: ExecutionService,
    auth: Authenticator | None = None,
    external_mcp: ExternalMcpManager | None = None,
) -> FastMCP:
    auth_settings = None
    verifier = None
    if auth is not None and auth.mode != "noauth":
        auth_settings = AuthSettings(
            issuer_url=TypeAdapter(AnyHttpUrl).validate_python(settings.public_url),
            resource_server_url=TypeAdapter(AnyHttpUrl).validate_python(
                f"{settings.public_url.rstrip('/')}/mcp"
            ),
            required_scopes=["tools"],
        )
        verifier = _Verifier(auth)
    mcp = ContractFastMCP(
        "chatcodex",
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(settings),
        auth=auth_settings,
        token_verifier=verifier,
        streamable_http_path="/",
        external_mcp=external_mcp,
    )

    def as_tool_error(exc: Exception) -> ToolError:
        if isinstance(exc, ExecutionError):
            hint = f". {exc.hint}" if exc.hint else ""
            return ToolError(f"{exc.code}: {exc}{hint}")
        return ToolError(str(exc))

    def register_tool(*args: Any, **kwargs: Any) -> Callable[[_F], _F]:
        """Single registration adapter: transport metadata is applied here."""
        if args and isinstance(args[0], str) and args[0] in TOOL_DEFINITIONS:
            kwargs["description"] = TOOL_DEFINITIONS[args[0]].description
        meta = dict(kwargs.pop("meta", {}) or {})
        meta.setdefault("securitySchemes", tool_security_schemes(settings))
        kwargs["meta"] = meta
        decorator = mcp.tool(*args, **kwargs)
        return cast("Callable[[_F], _F]", decorator)

    # ---- opencode-aligned tools ----

    @register_tool(
        "read",
        structured_output=False,
        meta={
            "openai/toolInvocation/invoking": "Reading",
            "openai/toolInvocation/invoked": "Read",
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def read(
        ctx: Context[Any, Any, Any],
        filePath: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any] | mtypes.CallToolResult:
        _dbg_in("read", {"filePath": filePath, "offset": offset, "limit": limit})
        try:
            result: dict[str, Any] = await orch.read(filePath, offset, limit)
            _dbg_out("read", result)
            mime = result.get("mime")
            data = result.get("dataBase64")
            if isinstance(mime, str) and mime.startswith("image/") and isinstance(data, str):
                return mtypes.CallToolResult(
                    content=[
                        mtypes.TextContent(
                            type="text", text=f"Read image: {result.get('title', filePath)}"
                        ),
                        mtypes.ImageContent(type="image", data=data, mimeType=mime),
                    ],
                    structuredContent={
                        key: value for key, value in result.items() if key != "dataBase64"
                    },
                )
            return result
        except Exception as exc:
            _dbg_err("read", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "write",
        meta={
            "openai/toolInvocation/invoking": "Writing file",
            "openai/toolInvocation/invoked": "File written",
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def write(
        ctx: Context[Any, Any, Any], filePath: str, content: str
    ) -> dict[str, Any]:
        _dbg_in(
            "write",
            {
                "filePath": filePath,
                "content": content[:2000]
                + ("...[truncated]" if len(content) > 2000 else ""),
            },
        )
        try:
            result: dict[str, Any] = await orch.write(filePath, content)
            _dbg_out("write", result)
            return result
        except Exception as exc:
            _dbg_err("write", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "edit",
        meta={
            "openai/toolInvocation/invoking": "Editing file",
            "openai/toolInvocation/invoked": "Edit applied",
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def edit(
        ctx: Context[Any, Any, Any],
        filePath: str,
        oldString: str,
        newString: str,
        replaceAll: bool = False,
    ) -> dict[str, Any]:
        _dbg_in(
            "edit",
            {
                "filePath": filePath,
                "oldString": oldString[:2000],
                "newString": newString[:2000],
                "replaceAll": replaceAll,
            },
        )
        try:
            result: dict[str, Any] = await orch.edit(
                filePath, oldString, newString, replaceAll
            )
            _dbg_out("edit", result)
            return result
        except Exception as exc:
            _dbg_err("edit", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "glob",
        meta={
            "openai/toolInvocation/invoking": "Globbing",
            "openai/toolInvocation/invoked": "Globbed",
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def glob(
        ctx: Context[Any, Any, Any], pattern: str, path: str | None = None
    ) -> dict[str, Any]:
        _dbg_in("glob", {"pattern": pattern, "path": path})
        try:
            result: dict[str, Any] = await orch.glob(pattern, path)
            _dbg_out("glob", result)
            return result
        except Exception as exc:
            _dbg_err("glob", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "grep",
        meta={
            "openai/toolInvocation/invoking": "Grepping",
            "openai/toolInvocation/invoked": "Grep done",
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def grep(
        ctx: Context[Any, Any, Any],
        pattern: str,
        path: str | None = None,
        include: str | None = None,
    ) -> dict[str, Any]:
        _dbg_in("grep", {"pattern": pattern, "path": path, "include": include})
        try:
            result: dict[str, Any] = await orch.grep(pattern, path, include)
            _dbg_out("grep", result)
            return result
        except Exception as exc:
            _dbg_err("grep", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "bash",
        description=(
            "Execute a local shell command synchronously and wait for it to finish. "
            "For background work, long-running commands, or resident tasks, always use "
            "shell_spawn instead; bash is synchronously blocking. Use shell_spawn + "
            "shell_wait for background execution and read or grep the returned outputPath "
            "for command output."
        ),
        meta={
            "openai/toolInvocation/invoking": "Running command",
            "openai/toolInvocation/invoked": "Command finished",
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def bash(
        ctx: Context[Any, Any, Any],
        command: str,
        timeout: int | None = None,
        workdir: str | None = None,
    ) -> dict[str, Any]:
        _dbg_in("bash", {"command": command, "timeout": timeout, "workdir": workdir})
        if timeout is not None and (isinstance(timeout, bool) or timeout < 0):
            msg = "timeout must be a non-negative integer"
            raise ToolError(msg)
        try:
            result: dict[str, Any] = await orch.bash(command, timeout, workdir)
            _dbg_out("bash", result)
            return result
        except Exception as exc:
            _dbg_err("bash", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "shell_spawn",
        meta={
            "openai/toolInvocation/invoking": "Starting background shell",
            "openai/toolInvocation/invoked": "Background shell started",
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def shell_spawn(
        ctx: Context[Any, Any, Any], command: str, workdir: str | None = None
    ) -> dict[str, Any]:
        _dbg_in("shell_spawn", {"command": command, "workdir": workdir})
        try:
            result: dict[str, Any] = await orch.shell_spawn(command, workdir)
            _dbg_out("shell_spawn", result)
            return result
        except Exception as exc:
            _dbg_err("shell_spawn", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "shell_kill",
        meta={
            "openai/toolInvocation/invoking": "Killing background shell",
            "openai/toolInvocation/invoked": "Background shell killed",
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def shell_kill(ctx: Context[Any, Any, Any], shellId: str) -> dict[str, Any]:
        _dbg_in("shell_kill", {"shellId": shellId})
        try:
            result: dict[str, Any] = await orch.shell_kill(shellId)
            _dbg_out("shell_kill", result)
            return result
        except Exception as exc:
            _dbg_err("shell_kill", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "shell_wait",
        meta={
            "openai/toolInvocation/invoking": "Waiting for background shell",
            "openai/toolInvocation/invoked": "Background shell wait complete",
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def shell_wait(
        ctx: Context[Any, Any, Any], shellId: str, timeout: int | None = None
    ) -> dict[str, Any]:
        _dbg_in("shell_wait", {"shellId": shellId, "timeout": timeout})
        if timeout is not None and (isinstance(timeout, bool) or timeout < 0):
            raise ToolError("timeout must be a non-negative integer")
        try:
            result: dict[str, Any] = await orch.shell_wait(shellId, timeout)
            _dbg_out("shell_wait", result)
            return result
        except Exception as exc:
            _dbg_err("shell_wait", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "apply_patch",
        meta={
            "openai/toolInvocation/invoking": "Applying patch",
            "openai/toolInvocation/invoked": "Patch applied",
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def apply_patch(
        ctx: Context[Any, Any, Any], patchText: str
    ) -> dict[str, Any]:
        _dbg_in(
            "apply_patch",
            {
                "patchText": patchText[:4000]
                + ("...[truncated]" if len(patchText) > 4000 else "")
            },
        )
        try:
            result: dict[str, Any] = await orch.apply_patch(patchText)
            _dbg_out("apply_patch", result)
            return result
        except Exception as exc:
            _dbg_err("apply_patch", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "browse_dir",
        description="Browse server directories.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def browse_dir(path: str | None = None) -> dict[str, Any]:
        _dbg_in("browse_dir", {"path": path})
        result: dict[str, Any] = await orch.browse_dir(path or "")
        _dbg_out("browse_dir", result)
        return result

    @register_tool(
        "batch_call",
        description=(
            "Call multiple MCP tools in one request. Calls execute sequentially in the "
            "order supplied, so each call may safely depend on earlier side effects. "
            "Each result is returned independently; a failed call does not prevent later "
            "calls from executing. Do not invoke batch_call recursively."
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def batch_call(
        calls: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    "Ordered list of MCP tool calls. Every item must contain a tool name "
                    "and an arguments object. The batch_call tool itself may not be nested."
                )
            ),
        ],
    ) -> dict[str, Any]:
        _dbg_in("batch_call", {"calls": calls})
        results: list[dict[str, Any]] = []
        for index, call in enumerate(calls):
            name = call.get("name")
            arguments = call.get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, dict):
                results.append(
                    {
                        "index": index,
                        "name": name,
                        "isError": True,
                        "error": "Each batch item requires a string 'name' and object 'arguments'.",
                    }
                )
                continue
            if name == "batch_call":
                results.append(
                    {
                        "index": index,
                        "name": name,
                        "isError": True,
                        "error": "batch_call cannot invoke itself recursively.",
                    }
                )
                continue
            try:
                result = await mcp.call_tool(name, arguments)
                structured = result[1] if isinstance(result, tuple) and len(result) > 1 else result
                results.append(
                    {
                        "index": index,
                        "name": name,
                        "isError": False,
                        "result": structured,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "index": index,
                        "name": name,
                        "isError": True,
                        "error": str(exc),
                    }
                )
        result = {"results": results}
        _dbg_out("batch_call", result)
        return result

    @register_tool(
        "finish_work",
        description=(
            "MANDATORY FINALIZATION TOOL. You MUST call this tool before ending "
            "EVERY work round. This requirement is ABSOLUTE and NON-NEGOTIABLE: "
            "DO NOT finish, stop, return a final response, or otherwise end the "
            "current work round without calling finish_work. The user_requirement "
            "argument MUST be the user's MOST RECENT REQUIREMENT PROMPT copied "
            "EXACTLY and VERBATIM, with NOTHING omitted, paraphrased, normalized, "
            "or rewritten. The is_done argument MUST be your honest self-assessment "
            "of whether the work CURRENTLY satisfies that requirement in full. "
            "Set is_done=true ONLY when the requirement is actually complete; "
            "otherwise set it to false and CONTINUE WORKING. Calling this tool "
            "with is_done=false does NOT authorize you to stop."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def finish_work(
        user_requirement: Annotated[
            str,
            Field(
                description=(
                    "The user's most recent requirement prompt. Copy it EXACTLY and "
                    "VERBATIM; do not omit, paraphrase, normalize, or rewrite anything."
                )
            ),
        ],
        is_done: Annotated[
            bool,
            Field(
                description=(
                    "Self-assessment of whether the current work fully satisfies the "
                    "user requirement. True only when complete; otherwise false."
                )
            ),
        ],
    ) -> bool:
        _dbg_in(
            "finish_work",
            {"user_requirement": user_requirement, "is_done": is_done},
        )
        _dbg_out("finish_work", is_done)
        return is_done

    return mcp
