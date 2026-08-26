from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, cast

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

    async def apply_patch(self, *args: Any) -> dict[str, Any]:
        return {
            "title": "apply_patch",
            "output": "",
            "diff": "",
            "files": [],
            "applied": True,
            "fileChanges": [],
        }

    async def update_plan(self, *args: Any) -> dict[str, Any]:
        return {"updated": True, "explanation": "", "plan": []}

    async def view_image(self, *args: Any) -> dict[str, Any]:
        return {
            "path": args[0],
            "mimeType": "image/png",
            "sizeBytes": 0,
            "dataBase64": "",
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


if __name__ == "__main__":
    unittest.main()
