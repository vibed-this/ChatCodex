# Copyright (c) 2026 ChatCodex contributors.
"""External MCP client manager and gateway-side tool federation."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shlex
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, types
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client


SUPPORTED_TRANSPORTS = {"stdio", "sse", "streamable_http"}


def _safe_name(value: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in value.strip())
    return out.strip("_") or "server"


def _as_headers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    server_id = _safe_name(str(config.get("id") or config.get("name") or "server"))
    if "__" in server_id:
        raise ValueError("external MCP server id must not contain __")
    transport = str(config.get("transport") or "streamable_http").lower()
    if transport not in SUPPORTED_TRANSPORTS:
        raise ValueError(f"transport must be one of: {", ".join(sorted(SUPPORTED_TRANSPORTS))}")
    out = dict(config)
    out["id"] = server_id
    out["name"] = str(config.get("name") or server_id)
    out["transport"] = transport
    out["enabled"] = bool(config.get("enabled", True))
    out["url"] = str(config.get("url") or "")
    out["command"] = str(config.get("command") or "")
    out["args"] = [str(x) for x in config.get("args", [])] if isinstance(config.get("args", []), list) else []
    out["cwd"] = str(config.get("cwd") or "")
    out["env"] = {str(k): str(v) for k, v in (config.get("env") or {}).items()} if isinstance(config.get("env") or {}, dict) else {}
    out["headers"] = _as_headers(config.get("headers"))
    return out


@dataclass
class _Connection:
    config: dict[str, Any]
    session: ClientSession
    stack: Any
    tools: list[types.Tool] = field(default_factory=list)


class ExternalMcpManager:
    """Own external MCP client sessions and federate their tools into ChatCodex."""

    def __init__(self, configs: list[dict[str, Any]] | None = None) -> None:
        self._configs: dict[str, dict[str, Any]] = {}
        for config in configs or []:
            normalized = _normalize_config(config)
            self._configs[normalized["id"]] = normalized
        self._connections: dict[str, _Connection] = {}
        self._lock = asyncio.Lock()

    def configs(self) -> list[dict[str, Any]]:
        return [dict(value) for value in self._configs.values()]

    def set_configs(self, configs: list[dict[str, Any]]) -> None:
        normalized = {}
        for config in configs:
            item = _normalize_config(config)
            normalized[item["id"]] = item
        self._configs = normalized

    async def replace_configs(self, configs: list[dict[str, Any]]) -> None:
        normalized = {}
        for config in configs:
            item = _normalize_config(config)
            normalized[item["id"]] = item
        async with self._lock:
            removed = set(self._connections) - set(normalized)
            changed = {
                server_id for server_id in set(self._connections) & set(normalized)
                if self._connection_fingerprint(self._configs[server_id]) != self._connection_fingerprint(normalized[server_id])
            }
            for server_id in removed | changed:
                await self._close_locked(server_id)
            self._configs = normalized

    @staticmethod
    def _connection_fingerprint(config: dict[str, Any]) -> str:
        return json.dumps(
            {k: config.get(k) for k in ("transport", "url", "command", "args", "cwd", "env", "headers", "enabled")},
            sort_keys=True, ensure_ascii=False,
        )

    async def _connect_locked(self, server_id: str) -> _Connection:
        existing = self._connections.get(server_id)
        if existing is not None:
            return existing
        config = self._configs.get(server_id)
        if config is None:
            raise KeyError(f"unknown external MCP server: {server_id}")
        if not config.get("enabled", True):
            raise RuntimeError(f"external MCP server is disabled: {server_id}")
        stack = contextlib.AsyncExitStack()
        try:
            transport = config["transport"]
            headers = _as_headers(config.get("headers"))
            if transport == "stdio":
                command = config.get("command", "")
                if not command:
                    raise ValueError("stdio MCP server requires command")
                args = list(config.get("args", []))
                if not args and any(ch.isspace() for ch in command.strip()):
                    parts = shlex.split(command, posix=False)
                    command, args = parts[0], parts[1:]
                params = StdioServerParameters(
                    command=command, args=args, env=_as_headers(config.get("env")) or None, cwd=config.get("cwd") or None,
                )
                read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
            elif transport == "sse":
                url = config.get("url", "")
                if not url:
                    raise ValueError("sse MCP server requires url")
                read_stream, write_stream = await stack.enter_async_context(sse_client(url, headers=headers or None))
            else:
                url = config.get("url", "")
                if not url:
                    raise ValueError("streamable_http MCP server requires url")
                read_stream, write_stream, _ = await stack.enter_async_context(streamablehttp_client(url, headers=headers or None))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            result = await session.list_tools()
            connection = _Connection(config=config, session=session, stack=stack, tools=list(result.tools))
            self._connections[server_id] = connection
            return connection
        except BaseException:
            await stack.aclose()
            raise

    async def _get_connection(self, server_id: str) -> _Connection:
        async with self._lock:
            return await self._connect_locked(server_id)

    @staticmethod
    def public_tool(server_id: str, tool: types.Tool) -> types.Tool:
        config_name = _safe_name(server_id)
        meta = dict(tool.meta or {})
        meta["chatcodex/external"] = {"server": server_id, "tool": tool.name}
        return types.Tool(
            name=f"{config_name}__{tool.name}",
            title=tool.title,
            description=tool.description,
            inputSchema=tool.inputSchema,
            outputSchema=tool.outputSchema,
            icons=tool.icons,
            annotations=tool.annotations,
            _meta=meta,
        )

    async def list_tools(self) -> list[types.Tool]:
        result: list[types.Tool] = []
        for server_id, config in self._configs.items():
            if not config.get("enabled", True):
                continue
            try:
                connection = await self._get_connection(server_id)
                refreshed = await connection.session.list_tools()
                connection.tools = list(refreshed.tools)
                result.extend(self.public_tool(server_id, tool) for tool in connection.tools)
            except Exception as exc:
                # A broken optional server must not take down ChatCodex's own tools.
                config["lastError"] = str(exc)
        return result

    def owns_tool(self, public_name: str) -> bool:
        if "__" not in public_name:
            return False
        server_id, tool_name = public_name.split("__", 1)
        connection = self._connections.get(server_id)
        return connection is not None and any(tool.name == tool_name for tool in connection.tools)

    async def call_tool(self, public_name: str, arguments: dict[str, Any]) -> Any:
        if "__" not in public_name:
            raise KeyError(public_name)
        server_id, tool_name = public_name.split("__", 1)
        connection = await self._get_connection(server_id)
        return await connection.session.call_tool(tool_name, arguments)

    async def close_server(self, server_id: str) -> None:
        async with self._lock:
            await self._close_locked(server_id)

    async def _close_locked(self, server_id: str) -> None:
        connection = self._connections.pop(server_id, None)
        if connection is not None:
            await connection.stack.aclose()

    async def close(self) -> None:
        async with self._lock:
            for server_id in list(self._connections):
                await self._close_locked(server_id)

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": config["id"],
                "name": config["name"],
                "transport": config["transport"],
                "enabled": config.get("enabled", True),
                "connected": config["id"] in self._connections,
                "toolCount": len(self._connections[config["id"]].tools) if config["id"] in self._connections else 0,
                "lastError": config.get("lastError", ""),
            }
            for config in self._configs.values()
        ]

