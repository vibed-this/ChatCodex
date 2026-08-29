# Copyright (c) 2026 ChatCodex contributors.
"""FilesystemService execution capability."""

from __future__ import annotations

from typing import Any

from ._common import *  # noqa: F403  # noqa: F403
from ._common import (
    DEFAULT_READ_LIMIT,
    MAX_BYTES,
    MAX_BYTES_LABEL,
    MAX_LINE_LENGTH,
    MAX_LINE_SUFFIX,
    MAX_WIDGET_DIFF_CHARS,
    SAMPLE_BYTES,
    SUPPORTED_IMAGE_MIMES,
    ExecutionError,
    Optional,
    _atomic_write_bytes,
    _is_binary_file,
    _join_bom,
    _rel_title,
    _replace_content,
    _resolve_absolute,
    _strip_bom,
    base64,
    difflib,
    mimetypes,
    os,
    trim_diff,
)


class FilesystemService:
    def __init__(self, settings: Any) -> None:
        self.settings = settings

    @staticmethod
    def _detect_image_mime(sample: bytes) -> str | None:
        if sample.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if sample.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if sample.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"WEBP":
            return "image/webp"
        return None

    async def read(
        self, filePath: str, offset: Optional[int] = None, limit: Optional[int] = None
    ) -> dict[str, Any]:
        # opencode: filePath absolute, offset 1-indexed, limit default 2000
        resolved = _resolve_absolute(filePath)
        if not os.path.exists(resolved):
            # suggest similar
            dirp = os.path.dirname(resolved)
            base = os.path.basename(resolved)
            sugg = []
            try:
                for e in os.listdir(dirp):
                    if base.lower() in e.lower() or e.lower() in base.lower():
                        sugg.append(os.path.join(dirp, e))
                        if len(sugg) >= 3:
                            break
            except OSError:
                pass
            if sugg:
                msg = "not_found"
                raise ExecutionError(
                    msg,
                    f"File not found: {resolved}\n\nDid you mean one of these?\n"
                    + "\n".join(sugg),
                )
            msg = "not_found"
            raise ExecutionError(msg, f"File not found: {resolved}")
        os.stat(resolved)
        is_dir = os.path.isdir(resolved)
        if is_dir:
            entries = []
            try:
                with os.scandir(resolved) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                target = (
                                    os.stat(entry.path)
                                    if os.path.exists(entry.path)
                                    else None
                                )
                                if target and os.path.isdir(entry.path):
                                    entries.append(entry.name + "/")
                                else:
                                    entries.append(entry.name)
                            elif entry.is_dir(follow_symlinks=False):
                                entries.append(entry.name + "/")
                            else:
                                entries.append(entry.name)
                        except OSError:
                            entries.append(entry.name)
            except Exception as e:
                msg = "read_error"
                raise ExecutionError(msg, str(e))
            entries.sort(key=lambda x: x.lower())
            lim = int(limit) if limit is not None else DEFAULT_READ_LIMIT
            off = int(offset) if offset else 1
            start = off - 1
            sliced = entries[start : start + lim]
            truncated = start + len(sliced) < len(entries)
            title = _rel_title(resolved).replace("\\", "/")
            out_lines = [
                f"<path>{resolved}</path>",
                "<type>directory</type>",
                "<entries>",
                "\n".join(sliced),
            ]
            if truncated:
                out_lines.append(
                    f"\n(Showing {len(sliced)} of {len(entries)} entries. Use 'offset' parameter to read beyond entry {off + len(sliced)})"
                )
            else:
                out_lines.append(f"\n({len(entries)} entries)")
            out_lines.append("</entries>")
            return {
                "title": title,
                "output": "\n".join(out_lines),
                "metadata": {"preview": "\n".join(sliced[:20]), "truncated": truncated},
                "entries": sliced,
                "truncated": truncated,
                "content": None,
                "mime": None,
                "dataBase64": None,
                "totalEntries": len(entries),
            }

        # file
        # sample for binary / mime
        try:
            with open(resolved, "rb") as f:
                sample = f.read(SAMPLE_BYTES)
                f.seek(0, os.SEEK_END)
                size = f.tell()
        except Exception as e:
            msg = "read_error"
            raise ExecutionError(msg, str(e))
        mime = mimetypes.guess_type(resolved)[0] or ""
        detected_image_mime = self._detect_image_mime(sample)
        is_image = mime in SUPPORTED_IMAGE_MIMES or detected_image_mime is not None
        if detected_image_mime is not None:
            mime = detected_image_mime
        is_pdf = mime == "application/pdf"
        if is_image or is_pdf:
            try:
                with open(resolved, "rb") as f:
                    data = f.read()
                b64 = base64.b64encode(data).decode()
                msg = "PDF read successfully" if is_pdf else "Image read successfully"
                return {
                    "title": _rel_title(resolved),
                    "output": msg,
                    "metadata": {"preview": msg, "truncated": False},
                    "content": None,
                    "truncated": False,
                    "entries": None,
                    "mime": mime,
                    "dataBase64": b64,
                    "totalEntries": None,
                }
            except Exception as e:
                msg_0 = "read_error"
                raise ExecutionError(msg_0, str(e))
        if _is_binary_file(resolved, sample):
            try:
                with open(resolved, "rb") as f:
                    data = f.read()
                binary_mime = mime or "application/octet-stream"
                return {
                    "title": _rel_title(resolved),
                    "output": "Binary resource read successfully",
                    "metadata": {"preview": binary_mime, "truncated": False},
                    "mime": binary_mime,
                    "dataBase64": base64.b64encode(data).decode(),
                    "sizeBytes": size,
                }
            except OSError as exc:
                msg_0 = "read_error"
                raise ExecutionError(msg_0, str(exc)) from exc
        # text file read with limits
        lim = int(limit) if limit is not None else DEFAULT_READ_LIMIT
        off = int(offset) if offset else 1
        raw: list[str] = []
        count = 0
        cut = False
        more = False
        done = False
        bytes_used = 0
        try:
            with open(resolved, encoding="utf-8", errors="strict") as f:
                for line in f:
                    count += 1
                    if count < off:
                        continue
                    if len(raw) >= lim:
                        more = True
                        continue
                    text = line.rstrip("\r\n")
                    if len(text) > MAX_LINE_LENGTH:
                        text = text[:MAX_LINE_LENGTH] + MAX_LINE_SUFFIX
                    sz = len(text.encode("utf-8")) + (1 if raw else 0)
                    if bytes_used + sz <= MAX_BYTES:
                        raw.append(text)
                        bytes_used += sz
                    else:
                        cut = True
                        more = True
                        done = True
                        break
                # count remaining lines if not truncated due to limit
                if not done:
                    # we already counted lines read; need total lines
                    # if we broke early due to more, count is already at limit start, but need total
                    # continue counting without storing
                    if more and len(raw) >= lim:
                        # need to count total
                        # we already have count = off+len(raw)-1 plus remaining
                        # continue reading
                        for _ in f:
                            count += 1
        except UnicodeDecodeError:
            msg_0 = "binary"
            raise ExecutionError(msg_0, f"Cannot read binary file: {resolved}")
        except Exception as e:
            msg_0 = "read_error"
            raise ExecutionError(msg_0, str(e))
        if count < off and not (count == 0 and off == 1):
            msg_0 = "out_of_range"
            raise ExecutionError(
                msg_0, f"Offset {off} is out of range for this file ({count} lines)"
            )
        last = off + len(raw) - 1 if raw else off - 1
        nxt = last + 1
        truncated = more or cut
        out = [f"<path>{resolved}</path>", "<type>file</type>", "<content>\n"]
        out.append("\n".join(f"{i + off}: {line}" for i, line in enumerate(raw)))
        if cut:
            out.append(
                f"\n\n(Output capped at {MAX_BYTES_LABEL}. Showing lines {off}-{last}. Use offset={nxt} to continue.)"
            )
        elif more:
            out.append(
                f"\n\n(Showing lines {off}-{last} of {count}. Use offset={nxt} to continue.)"
            )
        else:
            out.append(f"\n\n(End of file - total {count} lines)")
        out.append("\n</content>")
        output = "\n".join(out)
        return {
            "title": _rel_title(resolved),
            "output": output,
            "metadata": {"preview": "\n".join(raw[:20]), "truncated": truncated},
            "content": "\n".join(raw),
            "truncated": truncated,
            "totalLines": count,
            "lineStart": off,
            "lineEnd": last,
        }

    async def write(self, filePath: str, content: str) -> dict[str, Any]:
        resolved = _resolve_absolute(filePath)
        existed = os.path.exists(resolved)
        old_text = ""
        old_bytes = b""
        bom = False
        if existed:
            try:
                with open(resolved, "rb") as f:
                    old_bytes = f.read()
                # decode with BOM handling
                text = old_bytes.decode("utf-8")
                bom, old_text = _strip_bom(text)
            except UnicodeDecodeError:
                # binary previous - treat as empty for diff
                old_text = ""
                bom = False
                old_bytes = b""
            except Exception as e:
                msg = "read_error"
                raise ExecutionError(msg, str(e))
        # desired BOM
        has_new_bom, new_stripped = _strip_bom(content)
        desired_bom = bom or has_new_bom
        new_text = new_stripped
        new_bytes = _join_bom(new_text, desired_bom).encode("utf-8")
        diff = trim_diff(
            (
                difflib.unified_diff(
                    old_text.splitlines(),
                    new_text.splitlines(),
                    fromfile=resolved,
                    tofile=resolved,
                    lineterm="",
                )
                and "\n".join(
                    [f"diff --git a/{resolved} b/{resolved}"]
                    + (["new file mode 100644"] if not existed else [])
                    + list(
                        difflib.unified_diff(
                            old_text.splitlines(),
                            new_text.splitlines(),
                            fromfile=resolved if existed else "/dev/null",
                            tofile=resolved,
                            lineterm="",
                        )
                    )
                    + [""]
                )
            )
            or ""
        )
        # actually generate diff correctly
        try:
            old_lines = old_text.splitlines()
            new_lines = new_text.splitlines()
            body = list(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=resolved if existed else "/dev/null",
                    tofile=resolved,
                    lineterm="",
                )
            )
            if body:
                header = [f"diff --git a/{resolved} b/{resolved}"]
                if not existed:
                    header.append("new file mode 100644")
                diff = "\n".join(header + body + [""])
            else:
                diff = ""
            diff = trim_diff(diff) if diff else ""
        except (OSError, ValueError):
            diff = ""
        # write
        try:
            _atomic_write_bytes(resolved, new_bytes)
        except Exception as e:
            msg = "write_error"
            raise ExecutionError(msg, str(e))
        return {
            "title": _rel_title(resolved),
            "output": "Wrote file successfully.",
            "metadata": {"filepath": resolved, "exists": existed},
            "path": resolved,
            "bytesWritten": len(new_bytes),
            "written": True,
            "changed": old_bytes != new_bytes,
            "diff": diff,
            "diffTruncated": len(diff) > MAX_WIDGET_DIFF_CHARS,
        }

    async def edit(
        self, filePath: str, oldString: str, newString: str, replaceAll: bool = False
    ) -> dict[str, Any]:
        if oldString == newString:
            msg = "invalid_edit"
            raise ExecutionError(
                msg, "No changes to apply: oldString and newString are identical."
            )
        resolved = _resolve_absolute(filePath)
        if oldString == "":
            existed = os.path.exists(resolved)
            if existed:
                msg = "invalid_edit"
                raise ExecutionError(
                    msg,
                    "oldString cannot be empty when editing an existing file. Provide the exact text to replace, or use write for an intentional full-file replacement.",
                )
            # create new file
            has_bom, new_text = _strip_bom(newString)
            diff = trim_diff(
                "\n".join(
                    [
                        f"diff --git a/{resolved} b/{resolved}",
                        "new file mode 100644",
                        *list(
                            difflib.unified_diff(
                                [],
                                [new_text],
                                fromfile="/dev/null",
                                tofile=resolved,
                                lineterm="",
                            )
                        ),
                        "",
                    ]
                )
            )
            try:
                _atomic_write_bytes(
                    resolved, _join_bom(new_text, has_bom).encode("utf-8")
                )
            except Exception as e:
                msg = "write_error"
                raise ExecutionError(msg, str(e))
            return {
                "title": _rel_title(resolved),
                "output": "Edit applied successfully.",
                "metadata": {"diff": diff},
                "diff": diff,
            }
        # existing file
        if not os.path.exists(resolved):
            msg = "not_found"
            raise ExecutionError(msg, f"File {resolved} not found")
        if os.path.isdir(resolved):
            msg = "is_directory"
            raise ExecutionError(msg, f"Path is a directory, not a file: {resolved}")
        try:
            with open(resolved, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            msg = "binary"
            raise ExecutionError(msg, f"Cannot edit binary file: {resolved}")
        except Exception as e:
            msg = "read_error"
            raise ExecutionError(msg, str(e))
        has_bom, old_text = _strip_bom(text)
        # line ending detection
        ending = "\r\n" if "\r\n" in old_text else "\n"

        def norm(t: str) -> str:
            return t.replace("\r\n", "\n")

        def to_ending(t: str, e: str) -> str:
            return t.replace("\n", e) if e == "\r\n" else t

        old_norm = to_ending(norm(oldString), ending)
        new_norm = to_ending(norm(newString), ending)
        # perform replace
        new_content_norm = _replace_content(
            norm(old_text), norm(old_norm), norm(new_norm), bool(replaceAll)
        )
        # convert back? keep \n normalized then re-apply ending
        if ending == "\r\n":
            new_content = new_content_norm.replace("\n", "\r\n")
        else:
            new_content = new_content_norm
        # BOM handling
        _, new_stripped = _strip_bom(new_content)
        desired_bom = has_bom or newString.startswith("\ufeff")
        final_bytes = _join_bom(new_stripped, desired_bom).encode("utf-8")
        # diff
        try:
            body = list(
                difflib.unified_diff(
                    norm(old_text).splitlines(),
                    norm(new_content).splitlines(),
                    fromfile=resolved,
                    tofile=resolved,
                    lineterm="",
                )
            )
            diff = (
                "\n".join([f"diff --git a/{resolved} b/{resolved}", *body, ""])
                if body
                else ""
            )
            diff = trim_diff(diff)
        except (OSError, ValueError):
            diff = ""
        try:
            _atomic_write_bytes(resolved, final_bytes)
        except Exception as e:
            msg = "write_error"
            raise ExecutionError(msg, str(e))
        # diff stats
        adds = dels = 0
        import difflib as _d

        for line in _d.unified_diff(old_text.splitlines(), new_content.splitlines()):
            if line.startswith("+") and not line.startswith("+++"):
                adds += 1
            if line.startswith("-") and not line.startswith("---"):
                dels += 1
        return {
            "title": _rel_title(resolved),
            "output": "Edit applied successfully.",
            "metadata": {"diff": diff},
            "diff": diff,
            "additions": adds,
            "deletions": dels,
        }

    async def delete(self, filePath: str) -> dict[str, Any]:
        resolved = _resolve_absolute(filePath)
        if not os.path.exists(resolved):
            msg = "not_found"
            raise ExecutionError(msg, f"Path {resolved} not found")
        try:
            if os.path.isdir(resolved):
                os.rmdir(resolved)
            else:
                os.remove(resolved)
        except PermissionError as exc:
            msg = "permission_denied"
            raise ExecutionError(msg, str(exc)) from exc
        except OSError as exc:
            msg = "delete_error"
            raise ExecutionError(msg, str(exc)) from exc
        return {
            "title": _rel_title(resolved),
            "output": "Deleted successfully.",
            "path": resolved,
            "deleted": True,
        }

    async def browse_dir(self, path: str = "") -> dict[str, Any]:
        target = os.path.realpath(
            os.path.abspath(os.path.expanduser(path or os.getcwd()))
        )
        if not os.path.isdir(target):
            return {
                "path": target,
                "parent": None,
                "entries": [],
                "error": "directory does not exist",
            }
        entries = []
        try:
            with os.scandir(target) as it:
                for entry in sorted(
                    it,
                    key=lambda x: (not x.is_dir(follow_symlinks=False), x.name.lower()),
                )[:200]:
                    entries.append(
                        {
                            "name": entry.name,
                            "path": entry.path,
                            "isDirectory": entry.is_dir(follow_symlinks=False),
                        }
                    )
        except OSError as exc:
            return {"path": target, "parent": None, "entries": [], "error": str(exc)}
        parent = os.path.dirname(target)
        return {
            "path": target,
            "parent": parent if parent != target else None,
            "entries": entries,
        }
