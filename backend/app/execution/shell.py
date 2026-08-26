"""ShellService execution capability."""
from __future__ import annotations
from typing import Any
from ._common import *  # noqa: F401,F403

class ShellService:
    def __init__(self, settings: Any):
        self.settings=settings

    async def execute(self, command: str, timeout: Optional[int] = None, workdir: Optional[str] = None) -> dict[str, Any]:
        if timeout is not None and timeout < 0:
            raise ExecutionError("invalid_timeout", f"Invalid timeout value: {timeout}. Timeout must be a positive number.")
        eff_timeout = int(timeout) if timeout is not None else DEFAULT_SHELL_TIMEOUT_MS
        cwd=_resolve_absolute(workdir) if workdir else os.getcwd()
        if not os.path.isdir(cwd):
            raise ExecutionError("not_found", f"Workdir does not exist: {cwd}")
        # directory verification: if command creates files, caller should verify parent; we just execute
        shell = os.environ.get("SHELL", "/bin/sh" if os.name!="nt" else "cmd.exe")
        # choose shell executable
        if os.name=="nt":
            # use pwsh if available else cmd
            import shutil
            pwsh=shutil.which("pwsh") or shutil.which("powershell")
            if pwsh:
                shell=pwsh
            else:
                shell=shutil.which("cmd") or shell
        is_pwsh = "pwsh" in shell.lower() or "powershell" in shell.lower()
        try:
            creation_kwargs = {
                "start_new_session": os.name != "nt",
            }
            if os.name == "nt":
                creation_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            if is_pwsh:
                proc=subprocess.Popen([shell, "-NoLogo","-NoProfile","-NonInteractive","-Command", command], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **creation_kwargs)
            else:
                proc=subprocess.Popen(command, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", executable=shell if shell else None, **creation_kwargs)
            try:
                out, _ = proc.communicate(timeout=(eff_timeout+100)/1000.0)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(proc)
                try:
                    out, _ = proc.communicate(timeout=3)
                except (subprocess.TimeoutExpired, OSError):
                    out = ""
                meta = f"shell tool terminated command after exceeding timeout {eff_timeout} ms. If this command is expected to take longer and is not waiting for interactive input, retry with a larger timeout value in milliseconds."
                # tail/truncate
                truncated_output=_tail_output(out or "", MAX_LINE_FALLBACK, MAX_BYTES_FALLBACK)
                truncated=True
                # file fallback
                fpath=""
                if len((out or "").encode("utf-8")) > MAX_BYTES_FALLBACK:
                    fd, fpath=tempfile.mkstemp(prefix="bash-", suffix=".log")
                    os.write(fd, (out or "").encode("utf-8"))
                    os.close(fd)
                output=truncated_output
                if truncated and fpath:
                    output=f"...output truncated...\n\nFull output saved to: {fpath}\n\n"+output
                output+=f"\n\n<shell_metadata>\n{meta}\n</shell_metadata>"
                return {"title": command, "output": output, "metadata": {"output": output[-30000:], "exit": None, "truncated": True, "outputPath": fpath}, "exitCode": None, "stdout": out or "", "stderr": "", "truncated": True}
            code=proc.returncode
            raw=out or ""
            # truncate handling similar to opencode
            limits_max_bytes=MAX_BYTES_FALLBACK
            limits_max_lines=MAX_LINE_FALLBACK*2
            truncated=False
            fpath=""
            if len(raw.encode("utf-8")) > limits_max_bytes or len(raw.splitlines())>limits_max_lines:
                truncated=True
                # write full to file
                fd, fpath=tempfile.mkstemp(prefix="bash-", suffix=".log")
                os.write(fd, raw.encode("utf-8"))
                os.close(fd)
                # tail
                raw=_tail_output(raw, limits_max_lines, limits_max_bytes)
            if not raw:
                raw="(no output)"
            if truncated and fpath:
                raw=f"...output truncated...\n\nFull output saved to: {fpath}\n\n"+raw
            return {"title": command, "output": raw, "metadata": {"output": raw[-30000:], "exit": code, "truncated": truncated, **({"outputPath": fpath} if truncated and fpath else {})}, "exitCode": code, "stdout": out or "", "stderr": "", "truncated": truncated, "outputPath": fpath if truncated else None}
        except ExecutionError:
            raise
        except Exception as e:
            raise ExecutionError("bash_error", str(e))
