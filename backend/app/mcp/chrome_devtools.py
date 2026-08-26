# Copyright (c) 2026 ChatCodex contributors.
"""Bridge the Chrome DevTools MCP stdio server into the ChatCodex MCP server."""

from __future__ import annotations

import asyncio
import json
import shlex
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata
from pydantic import ConfigDict

if TYPE_CHECKING:
    from mcp.types import ToolAnnotations


class _ProxyArguments(ArgModelBase):
    """Accept the exact dynamic argument object supplied by an upstream MCP tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    def model_dump_one_level(self) -> dict[str, Any]:
        return {**super().model_dump_one_level(), **(self.model_extra or {})}


class ChromeDevToolsProxyTool(Tool):
    """Proxy one dynamically discovered Chrome DevTools MCP tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    client: ChromeDevToolsMCP
    upstream_name: str

    async def run(
        self, arguments: dict[str, Any], context: Any = None, convert_result: bool = False
    ) -> Any:
        return await self.client.call_tool(self.upstream_name, arguments)

    @classmethod
    def from_upstream(
        cls,
        client: ChromeDevToolsMCP,
        upstream_name: str,
        name: str,
        title: str | None,
        description: str,
        parameters: dict[str, Any],
        output_schema: dict[str, Any] | None,
        annotations: ToolAnnotations | None,
        meta: dict[str, Any],
    ) -> ChromeDevToolsProxyTool:
        async def proxy(**_kwargs: Any) -> None:
            return None

        return cls(
            fn=proxy,
            name=name,
            title=title,
            description=description,
            parameters=parameters,
            fn_metadata=FuncMetadata(
                arg_model=_ProxyArguments,
                output_schema=output_schema,
            ),
            is_async=True,
            context_kwarg=None,
            annotations=annotations,
            meta=meta,
            client=client,
            upstream_name=upstream_name,
        )


class ChromeDevToolsMCP:
    """Own a persistent stdio connection to chrome-devtools-mcp."""

    def __init__(self, command: str, *, enabled: bool) -> None:
        self.command = command.strip()
        self.enabled = enabled
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._lock = asyncio.Lock()
        self._tool_names: set[str] = set()
        self.last_error: str | None = None
        self._manifest = _load_manifest()

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def ensure_connected(self) -> None:
        if not self.enabled or self.connected:
            return
        async with self._lock:
            if not self.enabled or self.connected:
                return
            command, args = _split_command(self.command)
            if not command:
                message = "Chrome DevTools MCP command is empty"
                raise RuntimeError(message)
            server = StdioServerParameters(command=command, args=args)
            stack = AsyncExitStack()
            try:
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(server)
                )
                session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()
                self._stack = stack
                self._session = session
            except Exception:
                await stack.aclose()
                raise

    async def list_and_register(self, mcp: Any, reserved_names: set[str]) -> None:
        if not self.enabled:
            return
        self.register_manifest(mcp, reserved_names)

    def register_manifest(self, mcp: Any, reserved_names: set[str]) -> None:
        """Expose the known tool contract without starting the downstream process."""
        for upstream in self._manifest:
            self._register_tool(mcp, reserved_names, upstream)

    def _register_tool(self, mcp: Any, reserved_names: set[str], upstream: dict[str, Any]) -> None:
        upstream_name = str(upstream["name"])
        if upstream_name in self._tool_names:
            return
        name = f"chrome_{upstream_name}"
        if name in reserved_names:
            name = f"chrome_devtools_{upstream_name}"
        annotations = _annotations_from_dict(upstream.get("annotations"))
        tool = ChromeDevToolsProxyTool.from_upstream(
            client=self,
            upstream_name=upstream_name,
            name=name,
            title=upstream.get("title"),
            description=upstream.get("description") or f"Chrome DevTools MCP tool: {upstream_name}",
            parameters=upstream.get("inputSchema") or {"type": "object"},
            output_schema=upstream.get("outputSchema"),
            annotations=annotations,
            meta={
                **(upstream.get("meta") or {}),
                "chatcodex/upstream": "chrome-devtools-mcp",
                "chatcodex/upstreamTool": upstream_name,
            },
        )
        mcp._tool_manager._tools[name] = tool
        self._tool_names.add(upstream_name)

    async def refresh_manifest(self, mcp: Any, reserved_names: set[str]) -> None:
        """Refresh schemas after lazy startup, then keep the existing proxy names."""
        await self.ensure_connected()
        result = await self._require_session().list_tools()
        self._manifest = [
            {
                "name": t.name,
                "title": t.title,
                "description": t.description,
                "inputSchema": t.inputSchema,
                "outputSchema": t.outputSchema,
                "annotations": t.annotations.model_dump(mode="json") if t.annotations else None,
                "meta": t.meta,
            }
            for t in result.tools
        ]
        for upstream in self._manifest:
            self._tool_names.discard(str(upstream["name"]))
            self._register_tool(mcp, reserved_names, upstream)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self.ensure_connected()
        return await self._require_session().call_tool(name, arguments)

    async def close(self) -> None:
        async with self._lock:
            stack, self._stack = self._stack, None
            self._session = None
            self._tool_names.clear()
            if stack is not None:
                await stack.aclose()

    def _require_session(self) -> ClientSession:
        if self._session is None:
            message = "Chrome DevTools MCP is not connected"
            raise RuntimeError(message)
        return self._session


def _split_command(command: str) -> tuple[str, list[str]]:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        message = f"invalid Chrome DevTools MCP command: {exc}"
        raise ValueError(message) from exc
    if not parts:
        return "", []
    return parts[0], [part.strip('"') for part in parts[1:]]


def _annotations(value: ToolAnnotations | None) -> ToolAnnotations | None:
    return value.model_copy(deep=True) if value is not None else None


def _annotations_from_dict(value: dict[str, Any] | None) -> ToolAnnotations | None:
    if not value:
        return None
    from mcp.types import ToolAnnotations

    return ToolAnnotations.model_validate(value)


def _load_manifest() -> list[dict[str, Any]]:
    path = __import__("pathlib").Path(__file__).with_name("chrome_devtools_manifest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []
