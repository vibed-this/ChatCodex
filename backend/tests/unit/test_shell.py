from __future__ import annotations

import sys
import time
import unittest

from app.config import Settings
from app.execution import ExecutionService


class ShellUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_and_workdir(self):
        service = ExecutionService(Settings())
        command = f'{sys.executable} -c "print(123)"'
        result = await service.bash(command, timeout=5000)
        self.assertEqual(result["exitCode"], 0)
        self.assertIn("123", result["stdout"])

    async def test_timeout_terminates_process_tree(self):
        service = ExecutionService(Settings())
        command = "Start-Sleep -Seconds 10" if sys.platform == "win32" else "sleep 10"
        started = time.monotonic()
        result = await service.bash(command, timeout=100)
        self.assertIsNone(result["exitCode"])
        self.assertTrue(result["truncated"])
        self.assertLess(time.monotonic() - started, 5)
