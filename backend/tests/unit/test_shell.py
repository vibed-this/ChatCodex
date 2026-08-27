from __future__ import annotations

import asyncio
import sys
import time
import unittest

import pytest

from app.config import Settings
from app.execution import ExecutionService


class ShellUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_shell_spawn_wait_and_output_file(self) -> None:
        service = ExecutionService(Settings())
        spawned = await service.shell_spawn(f'{sys.executable} -c "print(789)"')
        assert spawned["shellId"]
        assert spawned["running"] is True
        waited = await service.shell_wait(spawned["shellId"], timeout=5000)
        assert waited["running"] is False
        assert waited["exitCode"] == 0
        assert open(waited["outputPath"], encoding="utf-8").read().strip() == "789"

    async def test_background_wait_timeout_does_not_kill_shell(self) -> None:
        service = ExecutionService(Settings())
        command = "Start-Sleep -Seconds 1" if sys.platform == "win32" else "sleep 1"
        spawned = await service.shell_spawn(command)
        timed = await service.shell_wait(spawned["shellId"], timeout=20)
        assert timed["timedOut"] is True
        assert timed["running"] is True
        finished = await service.shell_wait(spawned["shellId"], timeout=5000)
        assert finished["running"] is False
        assert finished["exitCode"] == 0

    async def test_background_kill_terminates_shell(self) -> None:
        service = ExecutionService(Settings())
        command = "Start-Sleep -Seconds 10" if sys.platform == "win32" else "sleep 10"
        spawned = await service.shell_spawn(command)
        killed = await service.shell_kill(spawned["shellId"])
        assert killed["running"] is False
    async def test_command_and_workdir(self) -> None:
        service = ExecutionService(Settings())
        command = f'{sys.executable} -c "print(123)"'
        result = await service.bash(command, timeout=5000)
        assert result["exitCode"] == 0
        assert "123" in result["stdout"]

    async def test_large_output_is_tail_truncated_and_saved(self) -> None:
        service = ExecutionService(Settings())
        command = f'{sys.executable} -c "import sys;sys.stdout.write(chr(10).join(map(str,range(2105))))"'
        result = await service.bash(command, timeout=5000)

        assert result["exitCode"] == 0
        assert result["truncated"] is True
        output_path = result["outputPath"]
        assert isinstance(output_path, str) and output_path
        saved = open(output_path, encoding="utf-8").read()
        assert saved.splitlines()[0] == "0"
        assert saved.splitlines()[-1] == "2104"
        assert result["stdout"].splitlines()[0] == "105"
        assert result["stdout"].splitlines()[-1] == "2104"

    async def test_byte_limited_output_is_saved(self) -> None:
        service = ExecutionService(Settings())
        command = f'{sys.executable} -c "import sys;sys.stdout.write(chr(120)*60000)"'
        result = await service.bash(command, timeout=5000)

        assert result["exitCode"] == 0
        assert result["truncated"] is True
        output_path = result["outputPath"]
        assert isinstance(output_path, str) and output_path
        saved = open(output_path, encoding="utf-8").read()
        assert len(saved.encode("utf-8")) > 50 * 1024
        assert result["stdout"].startswith("x")

    async def test_timeout_terminates_process_tree(self) -> None:
        service = ExecutionService(Settings())
        command = "Start-Sleep -Seconds 10" if sys.platform == "win32" else "sleep 10"
        started = time.monotonic()
        result = await service.bash(command, timeout=100)
        assert result["exitCode"] is None
        assert result["truncated"] is False
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
        # Process startup on Windows can take several hundred milliseconds; the
        # important contract is that the quick command does not wait for the 1s command.
        assert elapsed < 0.9

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
