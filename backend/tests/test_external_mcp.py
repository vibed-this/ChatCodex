import asyncio

import pytest
from mcp import types

from app.mcp.external import ExternalMcpManager, _normalize_config


def test_normalize_external_mcp_config() -> None:
    config = _normalize_config({"name": "GitHub MCP", "transport": "stdio", "command": "npx", "args": ["-y", "server"]})
    assert config["id"] == "GitHub_MCP"
    assert config["enabled"] is True
    assert config["args"] == ["-y", "server"]


def test_normalize_rejects_unknown_transport() -> None:
    with pytest.raises(ValueError, match="transport"):
        _normalize_config({"id": "x", "transport": "websocket"})


def test_external_tools_are_namespaced_and_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        manager = ExternalMcpManager([{"id": "demo", "transport": "streamable_http", "url": "https://example.test/mcp"}])
        calls: list[tuple[str, dict]] = []
    
        class Session:
            tools = [types.Tool(name="search", description="Search", inputSchema={"type": "object"})]
    
            async def list_tools(self):
                return types.ListToolsResult(tools=self.tools)
    
            async def call_tool(self, name: str, arguments: dict):
                calls.append((name, arguments))
                return types.CallToolResult(content=[types.TextContent(type="text", text="ok")])
    
        class Connection:
            session = Session()
            tools = Session.tools
    
        async def get_connection(_server_id: str):
            return Connection()
    
        monkeypatch.setattr(manager, "_get_connection", get_connection)
        tools = await manager.list_tools()
        assert [tool.name for tool in tools] == ["demo__search"]
        assert tools[0].meta["chatcodex/external"] == {"server": "demo", "tool": "search"}
        await manager.call_tool("demo__search", {"query": "test"})
        assert calls == [("search", {"query": "test"})]
    asyncio.run(scenario())

