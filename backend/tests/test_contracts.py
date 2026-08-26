from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.config import Settings
from app.mcp.server import build_mcp
from app.mcp.schemas import CORE_TOOL_NAMES, TOOL_DEFINITIONS


class FakeExecutionService:
    async def read(self, *args): return {"title": "read", "output": ""}
    async def write(self, *args): return {"title": "write", "output": "", "path": args[0], "bytesWritten": 0, "written": True, "changed": False}
    async def edit(self, *args): return {"title": "edit", "output": ""}
    async def glob(self, *args): return {"title": "glob", "output": "", "files": [], "truncated": False}
    async def grep(self, *args): return {"title": "grep", "output": "", "matches": 0, "truncated": False, "rows": []}
    async def bash(self, *args): return {"title": "bash", "output": "", "exitCode": 0, "stdout": "", "stderr": "", "truncated": False, "outputPath": None}
    async def apply_patch(self, *args): return {"title": "apply_patch", "output": "", "diff": "", "files": [], "applied": True, "fileChanges": []}
    async def update_plan(self, *args): return {"updated": True, "explanation": "", "plan": []}
    async def view_image(self, *args): return {"path": args[0], "mimeType": "image/png", "sizeBytes": 0, "dataBase64": ""}
    async def browse_dir(self, *args): return {"path": args[0] if args else "", "parent": None, "entries": []}
    async def list_mcp_tools(self): return {"conversationId": "", "servers": []}
    async def mcp_tool_call(self, *args): return {"conversationId": "", "server": args[0], "tool": args[1], "content": [], "structuredContent": None, "isError": False}


class ToolContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_tools_match_baseline(self):
        server = build_mcp(Settings(mcp_auth_mode="noauth"), FakeExecutionService())
        tools = await server.list_tools()
        names = sorted(tool.name for tool in tools)
        baseline = json.loads((Path(__file__).parent / "fixtures" / "mcp_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(names, sorted(baseline["tools"]))
        self.assertEqual(set(baseline["core_tools"]), CORE_TOOL_NAMES)
        self.assertEqual(set(names) & CORE_TOOL_NAMES, CORE_TOOL_NAMES)

    async def test_contract_does_not_use_fastmcp_private_registry(self):
        source = (Path(__file__).parents[1] / "app" / "mcp" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("_tool_manager._tools", source)
        self.assertNotIn("_chatcodex_orch", source)
        self.assertNotIn("_chatcodex_approval", source)

    async def test_core_tool_schemas_exactly_match_definitions(self):
        server = build_mcp(Settings(mcp_auth_mode="noauth"), FakeExecutionService())
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name, definition in TOOL_DEFINITIONS.items():
            self.assertEqual(tools[name].inputSchema, definition.input_schema, name)

    async def test_core_output_schemas_match_definitions(self):
        server = build_mcp(Settings(mcp_auth_mode="noauth"), FakeExecutionService())
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name, definition in TOOL_DEFINITIONS.items():
            self.assertEqual(tools[name].outputSchema, definition.output_schema, name)

    async def test_core_registry_is_the_registered_contract_source(self):
        server = build_mcp(Settings(mcp_auth_mode="noauth"), FakeExecutionService())
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name, definition in TOOL_DEFINITIONS.items():
            self.assertIn(name, tools)
            self.assertEqual(tools[name].description, definition.description)
            self.assertEqual(set(tools[name].inputSchema.get("properties", {})), set(definition.input_schema["properties"]))


if __name__ == "__main__":
    unittest.main()
