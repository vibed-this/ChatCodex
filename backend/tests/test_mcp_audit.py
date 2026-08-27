from __future__ import annotations

import asyncio
import unittest
from typing import Any

from app.mcp.audit import MAX_RECORDS, McpAuditLog, McpToolCallRecord, record_mcp_tool_call


async def _result(name: str) -> dict[str, Any]:
    return {"tool": name}


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


    async def test_batch_children_have_parent_call_id(self) -> None:
        log = McpAuditLog()

        async def nested(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            await record_mcp_tool_call(log, "read", {"path": "a.txt"}, lambda n, a: _result(n))
            return {"results": []}

        await record_mcp_tool_call(log, "batch_call", {"calls": []}, nested)
        records = log.list()
        batch = next(record for record in records if record["tool"] == "batch_call")
        child = next(record for record in records if record["tool"] == "read")
        assert batch["callId"]
        assert child["parentCallId"] == batch["callId"]

    async def test_active_call_is_visible_until_completion(self) -> None:
        log = McpAuditLog()
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow(_: str, __: dict[str, Any]) -> dict[str, Any]:
            started.set()
            await release.wait()
            return {"ok": True}

        task = asyncio.create_task(record_mcp_tool_call(log, "slow", {}, slow))
        await started.wait()
        active = log.active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["tool"], "slow")
        self.assertTrue(active[0]["active"])
        self.assertFalse(active[0]["success"])
        self.assertEqual(log.list(), [])
        release.set()
        await task
        self.assertEqual(log.active(), [])
        self.assertFalse(log.list()[0]["active"])
