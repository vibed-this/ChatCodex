from __future__ import annotations

import unittest
from typing import Any

from app.mcp.audit import MAX_RECORDS, McpAuditLog, McpToolCallRecord, record_mcp_tool_call


class McpAuditTests(unittest.IsolatedAsyncioTestCase):
    def test_audit_log_is_bounded_and_newest_first(self) -> None:
        log = McpAuditLog()
        for index in range(MAX_RECORDS + 25):
            log.append(
                McpToolCallRecord(
                    timestamp=str(index),
                    tool="test",
                    arguments={"index": index},
                    success=True,
                    duration_ms=1,
                )
            )
        records = log.list()
        self.assertEqual(len(records), MAX_RECORDS)
        self.assertEqual(records[0]["arguments"], {"index": MAX_RECORDS + 24})
        self.assertEqual(records[-1]["arguments"], {"index": 25})

    async def test_recorder_records_success_and_errors(self) -> None:
        log = McpAuditLog()

        async def success(_: str, __: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        result = await record_mcp_tool_call(log, "example", {"value": 1}, success)
        self.assertEqual(result, {"ok": True})
        records = log.list()
        self.assertEqual(records[0]["tool"], "example")
        self.assertEqual(records[0]["arguments"], {"value": 1})
        self.assertTrue(records[0]["success"])
        self.assertEqual(records[0]["result"], {"ok": True})

        async def failure(_: str, __: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            await record_mcp_tool_call(log, "example", {}, failure)
        records = log.list()
        self.assertFalse(records[0]["success"])
        self.assertEqual(records[0]["error"], "boom")
