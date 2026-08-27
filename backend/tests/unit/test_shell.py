from __future__ import annotations

import asyncio
import sys
import time
import unittest

import pytest

from app.config import Settings
from app.execution import ExecutionService


class ShellUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_and_workdir(self) -> None:
        service = ExecutionService(Settings())
        command = f'{sys.executable} -c "print(123)"'
        result = await service.bash(command, timeout=5000)
        assert result["exitCode"] == 0
        assert "123" in result["stdout"]

    async def test_timeout_terminates_process_tree(self) -> None:
        service = ExecutionService(Settings())
        command = "Start-Sleep -Seconds 10" if sys.platform == "win32" else "sleep 10"
        started = time.monotonic()
        result = await service.bash(command, timeout=100)
        assert result["exitCode"] is None
        assert result["truncated"]
        assert time.monotonic() - started < 5

    async def test_long_running_command_does_not_block_other_tools(self) -> None:
        service = ExecutionService(Settings())
        if sys.platform == "win32":
            slow_command = "Start-Sleep -Seconds 1"
            quick_command = "Write-Output 456"
        else:
            slow_command = "sleep 1"
            quick_command = "printf 456"

        slow = asyncio.create_task(service.bash(slow_command, timeout=5000))
        await asyncio.sleep(0.05)
        started = time.monotonic()
        quick = await service.bash(quick_command, timeout=5000)
        elapsed = time.monotonic() - started

        result = await slow
        assert result["exitCode"] == 0
        assert quick["exitCode"] == 0
        assert "456" in quick["stdout"]
        assert elapsed < 0.5

    async def test_cancellation_terminates_process_tree(self) -> None:
        service = ExecutionService(Settings())
        command = "Start-Sleep -Seconds 10" if sys.platform == "win32" else "sleep 10"
        task = asyncio.create_task(service.bash(command, timeout=5000))
        await asyncio.sleep(0.05)
        started = time.monotonic()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert time.monotonic() - started < 3
