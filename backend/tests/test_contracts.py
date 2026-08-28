from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, cast

from mcp import types as mtypes
from app.config import Settings
from app.mcp.schemas import CORE_TOOL_NAMES, TOOL_DEFINITIONS
from app.mcp.server import build_mcp


class FakeExecutionService:
    async def read(self, *args: Any) -> dict[str, Any]:
        return {"title": "read", "output": ""}

    async def write(self, *args: Any) -> dict[str, Any]:
        return {
            "title": "write",
            "output": "",
            "path": args[0],
            "bytesWritten": 0,
            "written": True,
            "changed": False,
        }

    async def edit(self, *args: Any) -> dict[str, Any]:
        return {"title": "edit", "output": ""}

    async def glob(self, *args: Any) -> dict[str, Any]:
        return {"title": "glob", "output": "", "files": [], "truncated": False}

    async def grep(self, *args: Any) -> dict[str, Any]:
        return {
            "title": "grep",
            "output": "",
            "matches": 0,
            "truncated": False,
            "rows": [],
        }

    async def bash(self, *args: Any) -> dict[str, Any]:
        return {
            "title": "bash",
            "output": "",
            "exitCode": 0,
            "stdout": "",
            "stderr": "",
            "truncated": False,
            "outputPath": None,
        }

    async def shell_spawn(self, *args: Any) -> dict[str, Any]:
        return {"shellId": "shell-1", "pid": 1, "command": args[0], "outputPath": "C:/tmp/shell.log", "running": True}

    async def shell_kill(self, *args: Any) -> dict[str, Any]:
        return {"shellId": args[0], "pid": 1, "outputPath": "C:/tmp/shell.log", "running": False, "exitCode": -9, "timedOut": False}

    async def shell_wait(self, *args: Any) -> dict[str, Any]:
        return {"shellId": args[0], "pid": 1, "outputPath": "C:/tmp/shell.log", "running": False, "exitCode": 0, "timedOut": False}

    async def apply_patch(self, *args: Any) -> dict[str, Any]:
        return {
            "title": "apply_patch",
            "output": "",
            "diff": "",
            "files": [],
            "applied": True,
            "fileChanges": [],
        }

    async def browse_dir(self, *args: Any) -> dict[str, Any]:
        return {"path": args[0] if args else "", "parent": None, "entries": []}

    async def list_mcp_tools(self) -> dict[str, Any]:
        return {"conversationId": "", "servers": []}

    async def mcp_tool_call(self, *args: Any) -> dict[str, Any]:
        return {
            "conversationId": "",
            "server": args[0],
            "tool": args[1],
            "content": [],
            "structuredContent": None,
            "isError": False,
        }


class ToolContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_tools_match_baseline(self) -> None:
        server = build_mcp(
            Settings(mcp_auth_mode="noauth"), cast("Any", FakeExecutionService())
        )
        tools = await server.list_tools()
        names = sorted(tool.name for tool in tools)
        baseline = json.loads(
            (Path(__file__).parent / "fixtures" / "mcp_baseline.json").read_text(
                encoding="utf-8"
            )
        )
        assert names == sorted(baseline["tools"])
        assert set(baseline["core_tools"]) == CORE_TOOL_NAMES
        assert set(names) & CORE_TOOL_NAMES == CORE_TOOL_NAMES
        assert "view_image" not in names

    async def test_contract_does_not_use_fastmcp_private_registry(self) -> None:
        source = (Path(__file__).parents[1] / "app" / "mcp" / "server.py").read_text(
            encoding="utf-8"
        )
        assert "_tool_manager._tools" not in source
        assert "_chatcodex_orch" not in source
        assert "_chatcodex_approval" not in source

    async def test_core_tool_schemas_exactly_match_definitions(self) -> None:
        server = build_mcp(
            Settings(mcp_auth_mode="noauth"), cast("Any", FakeExecutionService())
        )
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name, definition in TOOL_DEFINITIONS.items():
            assert tools[name].inputSchema == definition.input_schema, name

    async def test_core_output_schemas_match_definitions(self) -> None:
        server = build_mcp(
            Settings(mcp_auth_mode="noauth"), cast("Any", FakeExecutionService())
        )
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name, definition in TOOL_DEFINITIONS.items():
            assert tools[name].outputSchema == definition.output_schema, name

    async def test_core_registry_is_the_registered_contract_source(self) -> None:
        server = build_mcp(
            Settings(mcp_auth_mode="noauth"), cast("Any", FakeExecutionService())
        )
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name, definition in TOOL_DEFINITIONS.items():
            assert name in tools
            assert tools[name].description == definition.description
            assert set(tools[name].inputSchema.get("properties", {})) == set(
                definition.input_schema["properties"]
            )

    async def test_read_image_returns_mcp_image_content(self) -> None:
        class ImageExecutionService(FakeExecutionService):
            async def read(self, *args: Any) -> dict[str, Any]:
                return {
                    "title": "image.png",
                    "output": "Image read successfully",
                    "mime": "image/png",
                    "dataBase64": "iVBORw0KGgo=",
                    "sizeBytes": 8,
                }

        server = build_mcp(
            Settings(mcp_auth_mode="noauth"), cast("Any", ImageExecutionService())
        )
        result = await server.call_tool(
            "read", {"filePath": "image.png"}
        )
        assert isinstance(result, mtypes.CallToolResult)
        content = result.content
        assert any(
            isinstance(item, mtypes.ImageContent)
            for item in content
        )
        assert result.structuredContent == {
            "title": "image.png",
            "output": "Image read successfully",
            "mime": "image/png",
            "sizeBytes": 8,
        }

    async def test_batch_call_contract_is_strict(self) -> None:
        server = build_mcp(
            Settings(mcp_auth_mode="noauth"), cast("Any", FakeExecutionService())
        )
        tool = {tool.name: tool for tool in await server.list_tools()}["batch_call"]
        definition = TOOL_DEFINITIONS["batch_call"]
        assert tool.inputSchema == definition.input_schema
        assert tool.outputSchema == definition.output_schema

    async def test_batch_call_executes_in_order_and_isolates_errors(self) -> None:
        server = build_mcp(
            Settings(mcp_auth_mode="noauth"), cast("Any", FakeExecutionService())
        )
        result = await server.call_tool(
            "batch_call",
            {
                "calls": [
                    {"name": "read", "arguments": {"filePath": "a.txt"}},
                    {"name": "missing_tool", "arguments": {}},
                    {"name": "write", "arguments": {"filePath": "b.txt", "content": "x"}},
                ]
            },
        )
        assert isinstance(result, tuple)
        payload = cast("dict[str, Any]", result[1])
        results = cast("list[dict[str, Any]]", payload["results"])
        assert [item["index"] for item in results] == [0, 1, 2]
        assert results[0]["isError"] is False
        assert results[1]["isError"] is True
        assert results[2]["isError"] is False

    async def test_batch_call_rejects_recursive_batch(self) -> None:
        server = build_mcp(
            Settings(mcp_auth_mode="noauth"), cast("Any", FakeExecutionService())
        )
        result = await server.call_tool(
            "batch_call",
            {"calls": [{"name": "batch_call", "arguments": {"calls": []}}]},
        )
        assert isinstance(result, tuple)
        payload = cast("dict[str, Any]", result[1])
        item = cast("list[dict[str, Any]]", payload["results"])[0]
        assert item["isError"] is True

    async def test_background_shell_tools_are_registered(self) -> None:
        server = build_mcp(Settings(mcp_auth_mode="noauth"), cast("Any", FakeExecutionService()))
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name in ("shell_spawn", "shell_kill", "shell_wait"):
            assert name in tools
            assert tools[name].inputSchema == TOOL_DEFINITIONS[name].input_schema
            assert tools[name].outputSchema == TOOL_DEFINITIONS[name].output_schema


if __name__ == "__main__":
    unittest.main()
