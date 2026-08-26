from __future__ import annotations

import sys
import time
import unittest

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
