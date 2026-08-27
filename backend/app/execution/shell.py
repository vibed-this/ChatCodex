# Copyright (c) 2026 ChatCodex contributors.
"""ShellService execution capability."""

from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from typing import Any

from ._common import *  # noqa: F403  # noqa: F403
from ._common import (
    DEFAULT_SHELL_TIMEOUT_MS,
    MAX_BYTES,
    MAX_LINES,
    ExecutionError,
    Optional,
    _resolve_absolute,
    _tail_output,
    _terminate_process_tree,
    os,
    subprocess,
    tempfile,
)


class ShellService:
    RETENTION_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._background: dict[str, BackgroundShell] = {}
        self._background_lock = asyncio.Lock()

    async def spawn(self, command: str, workdir: Optional[str] = None) -> dict[str, Any]:
        """Start a shell without waiting; stdout/stderr go directly to a temp file."""
        cwd = _resolve_absolute(workdir) if workdir else os.getcwd()
        if not os.path.isdir(cwd):
            raise ExecutionError("not_found", f"Workdir does not exist: {cwd}")
        shell = os.environ.get("SHELL", "/bin/sh" if os.name != "nt" else "cmd.exe")
        if os.name == "nt":
            import shutil
            pwsh = shutil.which("pwsh") or shutil.which("powershell")
            shell = pwsh or (shutil.which("cmd") or shell)
        is_pwsh = "pwsh" in shell.lower() or "powershell" in shell.lower()
        output_path = self._new_output_path()
        output_handle = open(output_path, "wb")
        creation_kwargs: dict[str, Any] = {"start_new_session": os.name != "nt"}
        if os.name == "nt":
            creation_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            if is_pwsh:
                proc = await asyncio.create_subprocess_exec(
                    shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command,
                    cwd=cwd, stdout=output_handle, stderr=subprocess.STDOUT, **creation_kwargs,
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command, cwd=cwd, stdout=output_handle, stderr=subprocess.STDOUT,
                    executable=shell or None, **creation_kwargs,
                )
        except Exception as exc:
            output_handle.close()
            try:
                os.remove(output_path)
            except OSError:
                pass
            raise ExecutionError("shell_spawn_error", str(exc)) from exc
        shell_id = uuid.uuid4().hex
        record = BackgroundShell(shell_id, command, output_path, proc, output_handle, time.time())
        async with self._background_lock:
            self._background[shell_id] = record
        asyncio.create_task(self._finalize_background(record))
        return {"shellId": shell_id, "pid": proc.pid, "command": command, "workdir": cwd,
                "outputPath": output_path, "running": proc.returncode is None}

    async def kill(self, shell_id: str) -> dict[str, Any]:
        record = await self._get_background(shell_id)
        if record.proc.returncode is None:
            await _terminate_process_tree(record.proc)
            try:
                await asyncio.wait_for(record.proc.wait(), timeout=3)
            except (TimeoutError, OSError):
                pass
        return self._background_status(record)

    async def wait(self, shell_id: str, timeout: Optional[int] = None) -> dict[str, Any]:
        if timeout is not None and (isinstance(timeout, bool) or timeout < 0):
            raise ExecutionError("invalid_timeout", "Timeout must be a non-negative integer.")
        record = await self._get_background(shell_id)
        if record.proc.returncode is None:
            try:
                if timeout is None:
                    await record.proc.wait()
                else:
                    await asyncio.wait_for(record.proc.wait(), timeout=timeout / 1000.0)
            except TimeoutError:
                return self._background_status(record, timed_out=True)
        return self._background_status(record)

    async def _get_background(self, shell_id: str) -> "BackgroundShell":
        async with self._background_lock:
            self._prune_finished_background_locked()
            record = self._background.get(shell_id)
        if record is None:
            raise ExecutionError("not_found", f"Background shell does not exist: {shell_id}")
        return record

    async def _finalize_background(self, record: "BackgroundShell") -> None:
        try:
            await record.proc.wait()
        finally:
            record.output_handle.close()
            record.finished_at = time.time()

    async def close(self) -> None:
        """Terminate all remaining background shells during application shutdown."""
        async with self._background_lock:
            records = list(self._background.values())
        for record in records:
            if record.proc.returncode is None:
                await _terminate_process_tree(record.proc)
        for record in records:
            if record.proc.returncode is None:
                try:
                    await asyncio.wait_for(record.proc.wait(), timeout=3)
                except (TimeoutError, OSError):
                    continue

    def _prune_finished_background_locked(self) -> None:
        cutoff = time.time() - self.RETENTION_SECONDS
        stale = [
            record
            for record in self._background.values()
            if record.finished_at is not None and record.finished_at < cutoff
        ]
        for record in stale:
            self._background.pop(record.shell_id, None)
            try:
                os.remove(record.output_path)
            except OSError:
                pass

    @staticmethod
    def _background_status(record: "BackgroundShell", timed_out: bool = False) -> dict[str, Any]:
        return {"shellId": record.shell_id, "pid": record.proc.pid, "command": record.command,
                "outputPath": record.output_path, "running": record.proc.returncode is None,
                "exitCode": record.proc.returncode, "timedOut": timed_out}

    def _new_output_path(self) -> str:
        self._prune_finished_background_locked()
        fd, path = tempfile.mkstemp(prefix="shell_", suffix=".log", dir=self._output_dir())
        os.close(fd)
        return path

    @classmethod
    def _output_dir(cls) -> str:
        path = os.path.join(tempfile.gettempdir(), "chatcodex-tool-output")
        os.makedirs(path, exist_ok=True)
        return path

    @classmethod
    def _cleanup_output_files(cls) -> None:
        directory = cls._output_dir()
        cutoff = time.time() - cls.RETENTION_SECONDS
        try:
            for entry in os.scandir(directory):
                if not entry.name.startswith("tool_") or not entry.is_file():
                    continue
                try:
                    if entry.stat().st_mtime < cutoff:
                        os.remove(entry.path)
                except OSError:
                    continue
        except OSError:
            return

    @classmethod
    def _save_output(cls, text: str) -> str:
        directory = cls._output_dir()
        fd, path = tempfile.mkstemp(prefix="tool_", suffix=".log", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.remove(path)
            except OSError:
                pass
            raise
        return path

    @staticmethod
    def _truncate_output(text: str, max_lines: int, max_bytes: int) -> tuple[str, bool, int, str]:
        lines = text.split("\n")
        total_bytes = len(text.encode("utf-8"))
        if len(lines) <= max_lines and total_bytes <= max_bytes:
            return text, False, 0, "lines"
        preview = _tail_output(text, max_lines, max_bytes)
        preview_bytes = len(preview.encode("utf-8"))
        if total_bytes > max_bytes:
            return preview, True, total_bytes - preview_bytes, "bytes"
        return preview, True, len(lines) - len(preview.split("\n")), "lines"

    def _format_result(
        self,
        command: str,
        raw: str,
        exit_code: int | None,
        meta: list[str],
        output_path: str | None = None,
        tail: str | None = None,
    ) -> dict[str, Any]:
        self._cleanup_output_files()
        max_lines = int(getattr(self.settings, "bash_max_lines", MAX_LINES))
        max_bytes = int(getattr(self.settings, "bash_max_bytes", MAX_BYTES))
        if output_path is not None:
            preview = _tail_output(tail or "", max_lines, max_bytes)
            truncated = True
        else:
            preview, truncated, _, _ = self._truncate_output(raw, max_lines, max_bytes)
            if truncated:
                output_path = self._save_output(raw)
        output = preview or "(no output)"
        if truncated and output_path:
            output = (
                "...output truncated...\n\n"
                f"Full output saved to: {output_path}\n\n"
                "Use Read with offset/limit to view specific sections or Grep to search the full content.\n\n"
                + output
            )
        if meta:
            output += "\n\n<shell_metadata>\n" + "\n".join(meta) + "\n</shell_metadata>"
        return {
            "title": command,
            "output": output,
            "metadata": {
                "output": output[-30000:],
                "exit": exit_code,
                "truncated": truncated,
                **({"outputPath": output_path} if output_path else {}),
            },
            "exitCode": exit_code,
            "stdout": preview,
            "stderr": "",
            "truncated": truncated,
            "outputPath": output_path,
        }

    async def execute(
        self, command: str, timeout: Optional[int] = None, workdir: Optional[str] = None
    ) -> dict[str, Any]:
        if timeout is not None and timeout < 0:
            msg = "invalid_timeout"
            raise ExecutionError(
                msg,
                f"Invalid timeout value: {timeout}. Timeout must be a positive number.",
            )
        eff_timeout = int(timeout) if timeout is not None else DEFAULT_SHELL_TIMEOUT_MS
        cwd = _resolve_absolute(workdir) if workdir else os.getcwd()
        if not os.path.isdir(cwd):
            msg = "not_found"
            raise ExecutionError(msg, f"Workdir does not exist: {cwd}")
        # directory verification: if command creates files, caller should verify parent; we just execute
        shell = os.environ.get("SHELL", "/bin/sh" if os.name != "nt" else "cmd.exe")
        # choose shell executable
        if os.name == "nt":
            # use pwsh if available else cmd
            import shutil

            pwsh = shutil.which("pwsh") or shutil.which("powershell")
            shell = pwsh or (shutil.which("cmd") or shell)
        is_pwsh = "pwsh" in shell.lower() or "powershell" in shell.lower()
        try:
            creation_kwargs: dict[str, Any] = {
                "start_new_session": os.name != "nt",
            }
            if os.name == "nt":
                creation_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            if is_pwsh:
                proc = await asyncio.create_subprocess_exec(
                    shell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    **creation_kwargs,
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    executable=shell or None,
                    **creation_kwargs,
                )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=eff_timeout / 1000.0
                )
                out = (stdout or b"").decode("utf-8", errors="replace")
            except TimeoutError:
                await _terminate_process_tree(proc)
                try:
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
                    out = (stdout or b"").decode("utf-8", errors="replace")
                except (TimeoutError, OSError):
                    out = ""
                meta = f"shell tool terminated command after exceeding timeout {eff_timeout} ms. If this command is expected to take longer and is not waiting for interactive input, retry with a larger timeout value in milliseconds."
                return self._format_result(command, out or "", None, [meta])
            except asyncio.CancelledError:
                await _terminate_process_tree(proc)
                try:
                    await asyncio.wait_for(proc.communicate(), timeout=3)
                except (TimeoutError, OSError):
                    pass
                raise
            code = proc.returncode
            return self._format_result(command, out or "", code, [])
        except ExecutionError:
            raise
        except Exception as e:
            msg = "bash_error"
            raise ExecutionError(msg, str(e))


@dataclasses.dataclass
class BackgroundShell:
    shell_id: str
    command: str
    output_path: str
    proc: Any
    output_handle: Any
    started_at: float
    finished_at: float | None = None
