# Copyright (c) 2026 ChatCodex contributors.
"""SearchService execution capability."""

from __future__ import annotations

from typing import Any

from ._common import *  # noqa: F403  # noqa: F403
from ._common import (
    SEARCH_EXCLUDED_DIRS,
    SEARCH_FILE_LIMIT,
    SEARCH_FILE_SIZE_LIMIT,
    SEARCH_RESULT_LIMIT,
    ExecutionError,
    Optional,
    Path,
    _expand_include,
    _rel_title,
    _resolve_absolute,
    fnmatch,
    globlib,
    os,
    re,
    subprocess,
)


class SearchService:
    def __init__(self, settings: Any) -> None:
        self.settings = settings

    async def glob(self, pattern: str, path: Optional[str] = None) -> dict[str, Any]:
        search = _resolve_absolute(path) if path else os.getcwd()
        if os.path.isfile(search):
            msg = "invalid_path"
            raise ExecutionError(msg, f"glob path must be a directory: {search}")
        if not os.path.isdir(search):
            msg = "not_found"
            raise ExecutionError(msg, f"Directory not found: {search}")
        limit = 100
        # use globlib with recursive
        # ripgrep glob respects pattern relative to cwd
        # we emulate via pathlib
        base = Path(search)
        # handle pattern like **/*.js
        try:
            # use globlib.glob with recursive
            full_pattern = os.path.join(search, pattern)
            files = globlib.glob(full_pattern, recursive=True)
            # filter to files only, relative
            rel_files = []
            for f in files:
                # glob may return dirs; include all matching
                p = Path(f)
                if any(
                    part in SEARCH_EXCLUDED_DIRS
                    for part in p.relative_to(base).parts
                    if part not in {".", ".."}
                ):
                    continue
                # ensure inside search
                try:
                    rel_path = p.relative_to(base)
                except ValueError:
                    rel_path = Path(os.path.relpath(f, search))
                # ripgrep only returns files? but we include both
                rel_files.append((str(rel_path).replace("\\", "/"), f))
            # sort
            rel_files.sort(key=lambda x: x[0])
            # deduplicate and limit
            seen = set()
            out = []
            for _rel, abs_p in rel_files:
                if abs_p not in seen:
                    seen.add(abs_p)
                    out.append(os.path.abspath(abs_p))
                if len(out) >= limit:
                    break
            truncated = len(rel_files) >= limit or (
                len(out) == limit and len(rel_files) > limit
            )
            # if we limited, need to check if more
            if len(rel_files) > limit:
                truncated = True
            output = []
            if not out:
                output.append("No files found")
            else:
                output.extend(out)
                if truncated:
                    output.append("")
                    output.append(
                        f"(Results are truncated: showing first {limit} results. Consider using a more specific path or pattern.)"
                    )
            return {
                "title": _rel_title(search),
                "output": "\n".join(output),
                "metadata": {"count": len(out), "truncated": truncated},
                "files": [{"path": p} for p in out],
                "truncated": truncated,
            }
        except Exception as e:
            msg = "glob_error"
            raise ExecutionError(msg, str(e))

    async def grep(
        self, pattern: str, path: Optional[str] = None, include: Optional[str] = None
    ) -> dict[str, Any]:
        if not pattern:
            msg = "invalid_pattern"
            raise ExecutionError(msg, "pattern is required")
        try:
            regex = re.compile(pattern)
        except re.error as e:
            msg = "invalid_regex"
            raise ExecutionError(msg, f"Invalid regex: {e}")
        search = _resolve_absolute(path) if path else os.getcwd()
        target = search if os.path.isfile(search) else None
        cwd = search if os.path.isdir(search) else os.path.dirname(search)
        if not os.path.isdir(cwd):
            msg = "not_found"
            raise ExecutionError(msg, f"Path not found: {search}")
        limit = SEARCH_RESULT_LIMIT
        rows = []

        import shutil

        rg = shutil.which("rg")
        if rg:
            command = [
                rg,
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "--glob",
                "!.git/**",
            ]
            for excluded in sorted(SEARCH_EXCLUDED_DIRS - {".git"}):
                command.extend(["--glob", f"!**/{excluded}/**"])
            if include:
                command.extend(["--glob", include])
            command.extend([pattern, target or cwd])
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                msg = "search_timeout"
                raise ExecutionError(
                    msg, "rg search exceeded the 30 second resource limit"
                ) from exc
            if completed.returncode not in {0, 1}:
                msg = "search_error"
                raise ExecutionError(
                    msg, completed.stderr.strip() or "rg search failed"
                )
            for line in completed.stdout.splitlines():
                match = re.match(r"^(.*?):(\d+):(.*)$", line)
                if not match:
                    continue
                if any(
                    part in SEARCH_EXCLUDED_DIRS for part in Path(match.group(1)).parts
                ):
                    continue
                rows.append(
                    (
                        os.path.abspath(match.group(1)),
                        int(match.group(2)),
                        match.group(3)[:500],
                    )
                )
                if len(rows) >= limit:
                    break
        else:
            scanned = 0
            walk_roots = [os.path.dirname(target)] if target else [cwd]
            for root, dirs, files in os.walk(walk_roots[0]):
                dirs[:] = [d for d in dirs if d not in SEARCH_EXCLUDED_DIRS]
                for fname in files:
                    if scanned >= SEARCH_FILE_LIMIT:
                        break
                    fpath = os.path.join(root, fname)
                    if target and os.path.abspath(fpath) != os.path.abspath(target):
                        continue
                    if include and not any(
                        fnmatch.fnmatch(fname, inc) for inc in _expand_include(include)
                    ):
                        continue
                    try:
                        if os.path.getsize(fpath) > SEARCH_FILE_SIZE_LIMIT:
                            continue
                        scanned += 1
                        with open(fpath, encoding="utf-8", errors="strict") as fh:
                            for lineno, line in enumerate(fh, 1):
                                if regex.search(line):
                                    rows.append(
                                        (
                                            os.path.abspath(fpath),
                                            lineno,
                                            line.rstrip("\n")[:500],
                                        )
                                    )
                                    if len(rows) >= limit:
                                        break
                    except (OSError, UnicodeDecodeError):
                        continue
                    if len(rows) >= limit:
                        break
                if scanned >= SEARCH_FILE_LIMIT or len(rows) >= limit:
                    break
        if not rows:
            return {
                "title": pattern,
                "output": "No files found",
                "metadata": {"matches": 0, "truncated": False},
                "matches": 0,
                "truncated": False,
            }
        truncated = len(rows) == limit
        total = len(rows)
        out = [
            f"Found {total} matches{' (more matches available)' if truncated else ''}"
        ]
        cur = ""
        for p, lno, txt in rows:
            if cur != p:
                if cur != "":
                    out.append("")
                cur = p
                out.append(f"{p}:")
            out.append(f"  Line {lno}: {txt}")
        if truncated:
            out.append("")
            out.append(
                "(Results truncated. Consider using a more specific path or pattern.)"
            )
        return {
            "title": pattern,
            "output": "\n".join(out),
            "metadata": {"matches": total, "truncated": truncated},
            "matches": total,
            "truncated": truncated,
            "rows": [{"path": p, "line": line, "text": t} for p, line, t in rows],
        }
