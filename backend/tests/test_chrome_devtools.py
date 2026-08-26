from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.mcp.chrome_devtools import ChromeDevToolsMCP, _split_command


def test_split_command_preserves_arguments() -> None:
    command, args = _split_command(
        'npx --yes chrome-devtools-mcp@latest --browserUrl "http://127.0.0.1:9222"'
    )
    assert command == "npx"
    assert args == [
        "--yes",
        "chrome-devtools-mcp@latest",
        "--browserUrl",
        "http://127.0.0.1:9222",
    ]


def test_disabled_client_does_not_connect() -> None:
    async def run() -> None:
        client = ChromeDevToolsMCP("this-command-does-not-exist", enabled=False)
        await client.ensure_connected()
        assert not client.connected
        assert client.last_error is None
        await client.close()

    asyncio.run(run())


def test_manifest_registration_does_not_connect() -> None:
    async def run() -> None:
        client = ChromeDevToolsMCP("this-command-does-not-exist", enabled=True)
        client.ensure_connected = lambda: (_ for _ in ()).throw(AssertionError("must not connect"))  # type: ignore[method-assign]
        fake_mcp = SimpleNamespace(_tool_manager=SimpleNamespace(_tools={}))
        client.register_manifest(fake_mcp, set())
        assert len(fake_mcp._tool_manager._tools) == 29
        assert not client.connected

    asyncio.run(run())


def test_tool_call_connects_lazily() -> None:
    async def run() -> None:
        client = ChromeDevToolsMCP("unused", enabled=True)
        calls: list[str] = []

        async def ensure() -> None:
            calls.append("connect")

            async def call_tool(name: str, args: dict[str, object]) -> None:
                calls.append(name)

            client._session = SimpleNamespace(call_tool=call_tool)

        client.ensure_connected = ensure  # type: ignore[method-assign]
        await client.call_tool("list_pages", {})
        assert calls == ["connect", "list_pages"]
        await client.close()

    asyncio.run(run())
