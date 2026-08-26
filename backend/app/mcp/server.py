# Copyright (c) 2026 ChatCodex contributors.
"""Full-access MCP gateway aligned to opencode tools: read/write/edit/glob/grep/bash/apply_patch."""

from __future__ import annotations

import ipaddress
import json as _json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

from mcp import types as mtypes
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AnyHttpUrl, TypeAdapter

_F = TypeVar("_F", bound=Callable[..., Any])


class ContractFastMCP(FastMCP):
    """FastMCP adapter that exposes the transport-independent tool contracts."""

    def __init__(
        self,
        *args: Any,
        chrome_devtools: ChromeDevToolsMCP | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.chrome_devtools = chrome_devtools

    async def list_tools(self) -> Any:
        if self.chrome_devtools is not None and self.chrome_devtools.enabled:
            try:
                await self.chrome_devtools.list_and_register(
                    self, set(TOOL_DEFINITIONS)
                )
                self.chrome_devtools.last_error = None
            except Exception as exc:
                self.chrome_devtools.last_error = str(exc)
        tools = await super().list_tools()
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

from .schemas import TOOL_DEFINITIONS

if TYPE_CHECKING:
    from app.config import Settings
    from app.oauth import Authenticator

    from .chrome_devtools import ChromeDevToolsMCP


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
    chrome_devtools: ChromeDevToolsMCP | None = None,
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
        chrome_devtools=chrome_devtools,
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(settings),
        auth=auth_settings,
        token_verifier=verifier,
        streamable_http_path="/",
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
    ) -> dict[str, Any]:
        _dbg_in("read", {"filePath": filePath, "offset": offset, "limit": limit})
        try:
            result: dict[str, Any] = await orch.read(filePath, offset, limit)
            _dbg_out("read", result)
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
        "update_plan",
        description="Publish the coding plan.",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def update_plan(
        ctx: Context[Any, Any, Any],
        plan: list[dict[str, Any]],
        explanation: str | None = None,
    ) -> dict[str, Any]:
        _dbg_in("update_plan", {"plan": plan, "explanation": explanation})
        try:
            result: dict[str, Any] = await orch.update_plan(plan, explanation or "")
            _dbg_out("update_plan", result)
            return result
        except Exception as exc:
            _dbg_err("update_plan", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "view_image",
        description="Open a local image.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def view_image(
        ctx: Context[Any, Any, Any], path: str
    ) -> mtypes.CallToolResult:
        _dbg_in("view_image", {"path": path})
        try:
            data = await orch.view_image(path)
            _dbg_out(
                "view_image",
                {
                    k: v if k != "dataBase64" else f"<base64 {len(v)} chars>"
                    for k, v in data.items()
                },
            )
            return mtypes.CallToolResult(
                content=[
                    mtypes.TextContent(
                        type="text", text=f"Opened image: {data['path']}"
                    ),
                    mtypes.ImageContent(
                        type="image", data=data["dataBase64"], mimeType=data["mimeType"]
                    ),
                ],
                structuredContent={k: v for k, v in data.items() if k != "dataBase64"},
            )
        except Exception as exc:
            _dbg_err("view_image", exc)
            raise as_tool_error(exc) from exc

    @register_tool(
        "request_user_input",
        description="Prepare one to three non-secret questions for WebChat to ask.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def request_user_input(
        ctx: Context[Any, Any, Any], questions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        _dbg_in("request_user_input", {"questions": questions})
        if not 1 <= len(questions) <= 3:
            msg = "questions must contain between one and three items"
            raise ToolError(msg)
        normalized = []
        seen = set()
        for index, question in enumerate(questions):
            if question.get("is_secret") or question.get("isSecret"):
                msg = "request_user_input cannot collect secrets"
                raise ToolError(msg)
            question_id = str(question.get("id") or f"question_{index + 1}")
            if (
                not question_id.isidentifier()
                or question_id.startswith("_")
                or question_id in seen
            ):
                msg = f"invalid or duplicate question id: {question_id}"
                raise ToolError(msg)
            seen.add(question_id)
            normalized.append(
                {
                    "id": question_id,
                    "header": str(question.get("header") or ""),
                    "question": str(
                        question.get("question")
                        or question.get("header")
                        or question_id
                    ),
                    "options": [
                        {
                            "label": str(
                                option.get("label") or option.get("value") or ""
                            ),
                            "description": str(option.get("description") or ""),
                        }
                        for option in (question.get("options") or [])
                        if str(option.get("label") or option.get("value") or "")
                    ],
                    "is_other": bool(
                        question.get("is_other") or question.get("isOther")
                    ),
                    "is_secret": False,
                }
            )
        result = {"action": "ask_user", "questions": normalized}
        _dbg_out("request_user_input", result)
        return result

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

    return mcp
