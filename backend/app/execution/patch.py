"""PatchService execution capability."""
from __future__ import annotations
from typing import Any
from ._common import *  # noqa: F401,F403

class PatchService:
    def __init__(self, settings: Any):
        self.settings=settings

    async def apply(self, patchText: str) -> dict[str, Any]:
        if not patchText:
            raise ExecutionError("invalid_patch", "patchText is required")
        try:
            hunks=_parse_patch(patchText)
        except Exception as e:
            raise ExecutionError("invalid_patch", f"apply_patch verification failed: {e}")
        if not hunks:
            norm=patchText.replace("\r\n","\n").replace("\r","\n").strip()
            if norm=="*** Begin Patch\n*** End Patch":
                raise ExecutionError("invalid_patch", "patch rejected: empty patch")
            raise ExecutionError("invalid_patch", "apply_patch verification failed: no hunks found")
        file_changes=[]
        total_diff=""
        for hunk in hunks:
            fpath=_resolve_absolute(hunk["path"])
            typ=hunk["type"]
            if typ=="add":
                old=""
                new=hunk["contents"]
                if new and not new.endswith("\n"):
                    new+="\n"
                _, stripped=_strip_bom(new)
                bom=new.startswith("\ufeff")
                body=list(difflib.unified_diff([], stripped.splitlines(), fromfile=fpath, tofile=fpath, lineterm=""))
                diff="\n".join([f"diff --git a/{fpath} b/{fpath}","new file mode 100644"]+body+[""]) if body else f"diff --git a/{fpath} b/{fpath}\nnew file mode 100644\n"
                diff=trim_diff(diff)
                total_diff+=diff+"\n"
                adds=len(stripped.splitlines())
                file_changes.append({"filePath": fpath, "oldContent": old, "newContent": stripped, "type": "add", "diff": diff, "additions": adds, "deletions": 0, "bom": bom, "rel": _rel_title(fpath).replace("\\","/")})
            elif typ=="update":
                if not os.path.exists(fpath) or os.path.isdir(fpath):
                    raise ExecutionError("invalid_patch", f"apply_patch verification failed: Failed to read file to update: {fpath}")
                try:
                    with open(fpath, "rb") as fh:
                        raw=fh.read()
                    orig_text=raw.decode("utf-8")
                except Exception as e:
                    raise ExecutionError("invalid_patch", f"apply_patch verification failed: {e}")
                try:
                    new_text, bom = _derive_new_contents(fpath, hunk.get("chunks",[]), orig_text)
                except Exception as e:
                    raise ExecutionError("invalid_patch", f"apply_patch verification failed: {e}")
                # diff
                _, old_stripped=_strip_bom(orig_text)
                _, new_stripped=_strip_bom(new_text)
                body=list(difflib.unified_diff(old_stripped.splitlines(), new_stripped.splitlines(), fromfile=fpath, tofile=fpath, lineterm=""))
                diff="\n".join([f"diff --git a/{fpath} b/{fpath}"]+body+[""]) if body else ""
                diff=trim_diff(diff)
                total_diff+=diff+"\n"
                adds=dels=0
                for l in difflib.unified_diff(old_stripped.splitlines(), new_stripped.splitlines(), lineterm=""):
                    if l.startswith("+") and not l.startswith("+++"):
                        adds+=1
                    if l.startswith("-") and not l.startswith("---"):
                        dels+=1
                move_path=None
                if hunk.get("move_path"):
                    move_path=_resolve_absolute(hunk["move_path"])
                file_changes.append({"filePath": fpath, "oldContent": old_stripped, "newContent": new_stripped, "type": "move" if move_path else "update", "movePath": move_path, "diff": diff, "additions": adds, "deletions": dels, "bom": bom, "rel": _rel_title(move_path or fpath).replace("\\","/")})
            elif typ=="delete":
                if not os.path.exists(fpath):
                    raise ExecutionError("invalid_patch", f"apply_patch verification failed: Failed to read file to delete: {fpath}")
                try:
                    with open(fpath, "rb") as fh:
                        raw=fh.read()
                    text=raw.decode("utf-8")
                    _, stripped=_strip_bom(text)
                except Exception as e:
                    raise ExecutionError("invalid_patch", f"apply_patch verification failed: {e}")
                body=list(difflib.unified_diff(stripped.splitlines(), [], fromfile=fpath, tofile=fpath, lineterm=""))
                diff="\n".join([f"diff --git a/{fpath} b/{fpath}"]+body+[""]) if body else ""
                diff=trim_diff(diff)
                total_diff+=diff+"\n"
                dels=len(stripped.splitlines())
                file_changes.append({"filePath": fpath, "oldContent": stripped, "newContent": "", "type": "delete", "diff": diff, "additions": 0, "deletions": dels, "bom": False, "rel": _rel_title(fpath).replace("\\","/")})
        # Commit only after every hunk above has been parsed, validated, and
        # materialized. Keep byte snapshots so a later filesystem failure can
        # restore already committed paths as far as the host filesystem allows.
        snapshots: dict[str, bytes | None] = {}
        affected: set[str] = set()
        for ch in file_changes:
            affected.add(ch["filePath"])
            if ch.get("movePath"):
                affected.add(ch["movePath"])
        for path in affected:
            if os.path.exists(path):
                if os.path.isdir(path):
                    raise ExecutionError("invalid_patch", f"apply_patch verification failed: path is a directory: {path}")
                with open(path, "rb") as fh:
                    snapshots[path] = fh.read()
            else:
                snapshots[path] = None

        def atomic_write(path: str, data: bytes) -> None:
            directory = os.path.dirname(path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix=".chatcodex-patch-", dir=directory)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(temp_path, path)
            except OSError:
                try:
                    os.close(fd)
                except OSError:
                    pass
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise

        try:
            for ch in file_changes:
                typ=ch["type"]
                if typ in {"add", "update"}:
                    atomic_write(ch["filePath"], _join_bom(ch["newContent"], ch["bom"]).encode("utf-8"))
                elif typ=="move":
                    atomic_write(ch["movePath"], _join_bom(ch["newContent"], ch["bom"]).encode("utf-8"))
                    os.remove(ch["filePath"])
                elif typ=="delete":
                    os.remove(ch["filePath"])
        except Exception as commit_error:
            rollback_error: Exception | None = None
            for path, original in snapshots.items():
                try:
                    if original is None:
                        if os.path.exists(path) and not os.path.isdir(path):
                            os.remove(path)
                    else:
                        atomic_write(path, original)
                except Exception as exc:
                    rollback_error = rollback_error or exc
            detail = f"apply_patch commit failed: {commit_error}"
            if rollback_error is not None:
                detail += f"; rollback incomplete: {rollback_error}"
            raise ExecutionError("patch_commit_failed", detail) from commit_error
        summary=[f"{'A' if c['type']=='add' else 'D' if c['type']=='delete' else 'M'} {c['rel']}" for c in file_changes]
        output="Success. Updated the following files:\n"+"\n".join(summary)
        files=[{"filePath": c["filePath"], "relativePath": c["rel"], "type": c["type"], "patch": c["diff"], "additions": c["additions"], "deletions": c["deletions"], **({"movePath": c["movePath"]} if c.get("movePath") else {})} for c in file_changes]
        return {"title": output, "output": output, "metadata": {"diff": total_diff, "files": files}, "diff": total_diff, "files": files, "applied": True, "fileChanges": [c["rel"] for c in file_changes]}
