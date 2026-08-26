"""Full-access execution aligned to opencode tools (read/write/edit/glob/grep/bash/apply_patch)."""
from __future__ import annotations

import base64
import difflib
import fnmatch
import glob as globlib
import mimetypes
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

MAX_WIDGET_DIFF_CHARS = 200_000
MCP_TOOL_TIMEOUT_MS = 120_000

# opencode read constants
DEFAULT_READ_LIMIT = 2000
MAX_LINE_LENGTH = 2000
MAX_LINE_SUFFIX = f"... (line truncated to {MAX_LINE_LENGTH} chars)"
MAX_BYTES = 50 * 1024
MAX_BYTES_LABEL = f"{MAX_BYTES / 1024:.0f} KB"
SAMPLE_BYTES = 4096
SUPPORTED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_LINE_FALLBACK = 100  # for shell tail
MAX_BYTES_FALLBACK = 50 * 1024
DEFAULT_SHELL_TIMEOUT_MS = 2 * 60 * 1000

BINARY_EXTS = {
    ".zip", ".tar", ".gz", ".exe", ".dll", ".so", ".class", ".jar", ".war", ".7z",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".bin", ".dat", ".obj", ".o", ".a", ".lib", ".wasm", ".pyc", ".pyo",
}


class ExecutionError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.hint = hint


def _resolve_full_access(path: str) -> str:
    if not path:
        return os.path.abspath(os.getcwd())
    candidate = os.path.expanduser(path)
    if not os.path.isabs(candidate):
        candidate = os.path.join(os.getcwd(), candidate)
    return os.path.abspath(candidate)


def _resolve_absolute(p: str, cwd: Optional[str] = None) -> str:
    base = cwd or os.getcwd()
    if not p:
        return os.path.abspath(base)
    cand = os.path.expanduser(p)
    if not os.path.isabs(cand):
        cand = os.path.join(base, cand)
    return os.path.abspath(cand)


def _strip_bom(text: str) -> tuple[bool, str]:
    if text.startswith("\ufeff"):
        return True, text[1:]
    return False, text


def _rel_title(path: str) -> str:
    try:
        return os.path.relpath(path, os.getcwd()).replace("\\", "/")
    except ValueError:
        # 跨盘符（如 E:/1.txt 从 C: 盘的 cwd 相对）会抛 ValueError，回退为绝对路径
        return path.replace("\\", "/")


def _join_bom(text: str, bom: bool) -> str:
    _, stripped = _strip_bom(text)
    return ("\ufeff" + stripped) if bom else stripped


def trim_diff(diff: str) -> str:
    lines = diff.split("\n")
    content_lines = [l for l in lines if (l.startswith("+") or l.startswith("-") or l.startswith(" ")) and not l.startswith("---") and not l.startswith("+++")]
    if not content_lines:
        return diff
    mins = []
    for line in content_lines:
        content = line[1:]
        if content.strip():
            m = re.match(r"^(\s*)", content)
            if m:
                mins.append(len(m.group(1)))
    if not mins:
        return diff
    min_indent = min(mins)
    if min_indent == 0:
        return diff
    out = []
    for line in lines:
        if (line.startswith("+") or line.startswith("-") or line.startswith(" ")) and not line.startswith("---") and not line.startswith("+++"):
            out.append(line[0] + line[1:][min_indent:])
        else:
            out.append(line)
    return "\n".join(out)


def _write_file_diff(path: str, before: bytes, after: bytes, existed: bool) -> tuple[str, bool]:
    if existed and before == after:
        return "", False
    old_name = f"a/{path}"
    new_name = f"b/{path}"
    header = [f"diff --git {old_name} {new_name}"]
    if not existed:
        header.append("new file mode 100644")
    try:
        before_text = before.decode("utf-8")
        after_text = after.decode("utf-8")
    except UnicodeDecodeError:
        diff = "\n".join([*header, f"Binary files {old_name} and {new_name} differ", ""])
    else:
        body = difflib.unified_diff(before_text.splitlines(), after_text.splitlines(), fromfile=old_name if existed else "/dev/null", tofile=new_name, lineterm="")
        diff = "\n".join([*header, *body, ""])
    if len(diff) <= MAX_WIDGET_DIFF_CHARS:
        return diff, False
    suffix = "\n… Diff truncated for display …\n"
    return diff[: MAX_WIDGET_DIFF_CHARS - len(suffix)] + suffix, True


def _is_missing_file_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    message = str(exc).lower()
    return any(m in message for m in ("no such file", "cannot find the file", "cannot find the path", "os error 2", "找不到文件", "找不到指定的路径"))


def _is_binary_file(filepath: str, sample: bytes) -> bool:
    ext = Path(filepath).suffix.lower()
    if ext in BINARY_EXTS:
        return True
    if len(sample) == 0:
        return False
    non_printable = 0
    for b in sample:
        if b == 0:
            return True
        if b < 9 or (b > 13 and b < 32):
            non_printable += 1
    return (non_printable / len(sample)) > 0.3 if sample else False


# ---- edit replacers (port from edit.ts) ----

def _levenshtein(a: str, b: str) -> int:
    if a == "" or b == "":
        return max(len(a), len(b))
    m = len(a) + 1
    n = len(b) + 1
    dp = [[0]*n for _ in range(m)]
    for i in range(m):
        dp[i][0] = i
    for j in range(n):
        dp[0][j] = j
    for i in range(1, m):
        for j in range(1, n):
            cost = 0 if a[i-1] == b[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[m-1][n-1]

SINGLE_THRESHOLD = 0.65
MULTI_THRESHOLD = 0.65

def _simple_replacer(content: str, find: str):
    yield find

def _line_trimmed_replacer(content: str, find: str):
    original = content.split("\n")
    search = find.split("\n")
    if search and search[-1] == "":
        search = search[:-1]
    for i in range(len(original)-len(search)+1):
        ok=True
        for j in range(len(search)):
            if original[i+j].strip() != search[j].strip():
                ok=False
                break
        if ok:
            start=0
            for k in range(i):
                start+=len(original[k])+1
            end=start
            for k in range(len(search)):
                end+=len(original[i+k])
                if k < len(search)-1:
                    end+=1
            yield content[start:end]

def _block_anchor_replacer(content: str, find: str):
    original = content.split("\n")
    search = find.split("\n")
    if len(search)<3:
        return
    if search[-1]=="":
        search=search[:-1]
    first=search[0].strip()
    last=search[-1].strip()
    search_size=len(search)
    max_delta=max(1, search_size//4)
    cands=[]
    for i in range(len(original)):
        if original[i].strip()!=first:
            continue
        for j in range(i+2, len(original)):
            if original[j].strip()==last:
                if abs((j-i+1)-search_size)<=max_delta:
                    cands.append((i,j))
                break
    if not cands:
        return
    if len(cands)==1:
        s,e=cands[0]
        actual=e-s+1
        lines_to_check=min(search_size-2, actual-2)
        sim=0
        if lines_to_check>0:
            for j in range(1, search_size-1):
                if j>=actual-1:
                    break
                orig=original[s+j].strip()
                sea=search[j].strip()
                ml=max(len(orig), len(sea))
                if ml==0:
                    continue
                d=_levenshtein(orig, sea)
                sim+=(1-d/ml)/lines_to_check
                if sim>=SINGLE_THRESHOLD:
                    break
        else:
            sim=1.0
        if sim>=SINGLE_THRESHOLD:
            start=0
            for k in range(s):
                start+=len(original[k])+1
            end=start
            for k in range(s, e+1):
                end+=len(original[k])
                if k<e:
                    end+=1
            yield content[start:end]
        return
    best=None
    best_sim=-1
    for s,e in cands:
        actual=e-s+1
        lines_to_check=min(search_size-2, actual-2)
        sim=0
        if lines_to_check>0:
            for j in range(1, search_size-1):
                if j>=actual-1:
                    break
                orig=original[s+j].strip()
                sea=search[j].strip()
                ml=max(len(orig), len(sea))
                if ml==0:
                    continue
                d=_levenshtein(orig, sea)
                sim+=1-d/ml
            sim/=lines_to_check
        else:
            sim=1.0
        if sim>best_sim:
            best_sim=sim
            best=(s,e)
    if best and best_sim>=MULTI_THRESHOLD:
        s,e=best
        start=0
        for k in range(s):
            start+=len(original[k])+1
        end=start
        for k in range(s, e+1):
            end+=len(original[k])
            if k<e:
                end+=1
        yield content[start:end]

def _whitespace_normalized_replacer(content: str, find: str):
    norm = lambda t: re.sub(r"\s+", " ", t).strip()
    nfind = norm(find)
    lines=content.split("\n")
    for i,line in enumerate(lines):
        if norm(line)==nfind:
            yield line
        else:
            if norm(line).find(nfind)!=-1:
                words=find.strip().split()
                if words:
                    pat=r"\s+".join(re.escape(w) for w in words)
                    try:
                        m=re.search(pat, line)
                        if m:
                            yield m.group(0)
                    except: pass
    fl=find.split("\n")
    if len(fl)>1:
        for i in range(len(lines)-len(fl)+1):
            block="\n".join(lines[i:i+len(fl)])
            if norm(block)==nfind:
                yield block

def _indentation_flexible_replacer(content: str, find: str):
    def remove_indent(t: str):
        ls=t.split("\n")
        non=[l for l in ls if l.strip()]
        if not non:
            return t
        m=min(len(re.match(r"^(\s*)", l).group(1)) for l in non)
        return "\n".join(l[m:] if l.strip() else l for l in ls)
    nfind=remove_indent(find)
    cl=content.split("\n")
    fl=find.split("\n")
    for i in range(len(cl)-len(fl)+1):
        block="\n".join(cl[i:i+len(fl)])
        if remove_indent(block)==nfind:
            yield block

def _escape_normalized_replacer(content: str, find: str):
    def unesc(s: str):
        return re.sub(r"\\(n|t|r|'|\"|`|\\|\n|\$)", lambda m: {"n":"\n","t":"\t","r":"\r","'":"'","\"":"\"","`":"`","\\":"\\","\n":"\n","$":"$"}[m.group(1)], s)
    uf=unesc(find)
    if uf in content:
        yield uf
    lines=content.split("\n")
    fl=uf.split("\n")
    for i in range(len(lines)-len(fl)+1):
        block="\n".join(lines[i:i+len(fl)])
        if unesc(block)==uf:
            yield block

def _trimmed_boundary_replacer(content: str, find: str):
    tf=find.strip()
    if tf==find:
        return
    if tf in content:
        yield tf
    lines=content.split("\n")
    fl=find.split("\n")
    for i in range(len(lines)-len(fl)+1):
        block="\n".join(lines[i:i+len(fl)])
        if block.strip()==tf:
            yield block

def _context_aware_replacer(content: str, find: str):
    fl=find.split("\n")
    if len(fl)<3:
        return
    if fl[-1]=="":
        fl=fl[:-1]
    cl=content.split("\n")
    first=fl[0].strip()
    last=fl[-1].strip()
    for i in range(len(cl)):
        if cl[i].strip()!=first:
            continue
        for j in range(i+2, len(cl)):
            if cl[j].strip()==last:
                block=cl[i:j+1]
                if len(block)==len(fl):
                    matching=0
                    total=0
                    for k in range(1, len(block)-1):
                        bl=block[k].strip()
                        flk=fl[k].strip()
                        if bl or flk:
                            total+=1
                            if bl==flk:
                                matching+=1
                    if total==0 or matching/total>=0.5:
                        yield "\n".join(block)
                        break
                break

def _multi_occurrence_replacer(content: str, find: str):
    start=0
    while True:
        idx=content.find(find, start)
        if idx==-1:
            break
        yield find
        start=idx+len(find)

def _replace_content(content: str, old: str, new: str, replace_all: bool = False) -> str:
    if old == new:
        raise ExecutionError("invalid_edit", "No changes to apply: oldString and newString are identical.")
    if old == "":
        raise ExecutionError("invalid_edit", "oldString cannot be empty when editing an existing file. Provide the exact text to replace, or use write for an intentional full-file replacement.")
    not_found=True
    replacers=[_simple_replacer,_line_trimmed_replacer,_block_anchor_replacer,_whitespace_normalized_replacer,_indentation_flexible_replacer,_escape_normalized_replacer,_trimmed_boundary_replacer,_context_aware_replacer,_multi_occurrence_replacer]
    for rep in replacers:
        for search in rep(content, old):
            idx=content.find(search)
            if idx==-1:
                continue
            not_found=False
            # disproportionate check
            old_lines=old.split("\n")
            search_lines=search.split("\n")
            if len(search_lines) >= max(len(old_lines)+3, len(old_lines)*2):
                if len(old_lines)!=1 or search.strip()!=old.strip():
                    raise ExecutionError("invalid_edit", "Refusing replacement because the matched span is much larger than oldString. Re-read the file and provide the full exact oldString for the intended replacement.")
            if search.strip().__len__() > max(len(old.strip())+500, len(old.strip())*4) and len(old_lines)!=1:
                raise ExecutionError("invalid_edit", "Refusing replacement because the matched span is much larger than oldString. Re-read the file and provide the full exact oldString for the intended replacement.")
            if replace_all:
                return content.replace(search, new)
            last=content.rfind(search)
            if idx!=last:
                continue
            return content[:idx]+new+content[idx+len(search):]
    if not_found:
        raise ExecutionError("not_found", "Could not find oldString in the file. It must match exactly, including whitespace, indentation, and line endings.")
    raise ExecutionError("multiple_matches", "Found multiple matches for oldString. Provide more surrounding context to make the match unique.")


# ---- patch parsing (port from patch/index.ts) ----
def _strip_heredoc(text: str) -> str:
    m=re.match(r"^(?:cat\s+)?<<['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$", text)
    if m:
        return m.group(2)
    return text

def _parse_patch(patch_text: str):
    cleaned=_strip_heredoc(patch_text.strip())
    lines=cleaned.split("\n")
    hunks=[]
    begin="*** Begin Patch"
    end="*** End Patch"
    try:
        bi=next(i for i,l in enumerate(lines) if l.strip()==begin)
        ei=next(i for i,l in enumerate(lines) if l.strip()==end)
    except StopIteration:
        raise ValueError("Invalid patch format: missing Begin/End markers")
    if bi>=ei:
        raise ValueError("Invalid patch format: missing Begin/End markers")
    i=bi+1
    while i<ei:
        line=lines[i]
        if line.startswith("*** Add File:"):
            path=line[len("*** Add File:"):].strip()
            if not path:
                i+=1
                continue
            content=""
            j=i+1
            while j<ei and not lines[j].startswith("***"):
                if lines[j].startswith("+"):
                    content+=lines[j][1:]+"\n"
                j+=1
            if content.endswith("\n"):
                content=content[:-1]
            hunks.append({"type":"add","path":path,"contents":content})
            i=j
        elif line.startswith("*** Delete File:"):
            path=line[len("*** Delete File:"):].strip()
            if path:
                hunks.append({"type":"delete","path":path})
            i+=1
        elif line.startswith("*** Update File:"):
            path=line[len("*** Update File:"):].strip()
            if not path:
                i+=1
                continue
            move=None
            j=i+1
            if j<ei and lines[j].startswith("*** Move to:"):
                move=lines[j][len("*** Move to:"):].strip()
                j+=1
            chunks=[]
            while j<ei and not lines[j].startswith("***"):
                if lines[j].startswith("@@"):
                    ctx=lines[j][2:].strip()
                    j+=1
                    old=[]
                    new=[]
                    is_eof=False
                    while j<ei and not lines[j].startswith("@@") and not lines[j].startswith("***"):
                        cl=lines[j]
                        if cl=="*** End of File":
                            is_eof=True
                            j+=1
                            break
                        if cl.startswith(" "):
                            c=cl[1:]
                            old.append(c)
                            new.append(c)
                        elif cl.startswith("-"):
                            old.append(cl[1:])
                        elif cl.startswith("+"):
                            new.append(cl[1:])
                        j+=1
                    chunks.append({"old_lines":old,"new_lines":new,"change_context": ctx or None,"is_end_of_file": is_eof or None})
                else:
                    j+=1
            hunks.append({"type":"update","path":path,"move_path":move,"chunks":chunks})
            i=j
        else:
            i+=1
    return hunks

def _normalize_unicode(s: str) -> str:
    return s.replace("‘","'").replace("’","'").replace("‚","'").replace("‛","'").replace("“","\"").replace("”","\"").replace("„","\"").replace("‟","\"").replace("‐","-").replace("‑","-").replace("‒","-").replace("–","-").replace("—","-").replace("―","-").replace("…","...").replace(" "," ")

def _try_match(lines, pattern, start, compare, eof):
    if eof:
        fe=len(lines)-len(pattern)
        if fe>=start:
            ok=True
            for j in range(len(pattern)):
                if not compare(lines[fe+j], pattern[j]):
                    ok=False
                    break
            if ok:
                return fe
    for i in range(start, len(lines)-len(pattern)+1):
        ok=True
        for j in range(len(pattern)):
            if not compare(lines[i+j], pattern[j]):
                ok=False
                break
        if ok:
            return i
    return -1

def _seek_sequence(lines, pattern, start, eof=False):
    if not pattern:
        return -1
    r=_try_match(lines, pattern, start, lambda a,b: a==b, eof)
    if r!=-1:
        return r
    r=_try_match(lines, pattern, start, lambda a,b: a.rstrip()==b.rstrip(), eof)
    if r!=-1:
        return r
    r=_try_match(lines, pattern, start, lambda a,b: a.strip()==b.strip(), eof)
    if r!=-1:
        return r
    return _try_match(lines, pattern, start, lambda a,b: _normalize_unicode(a.strip())==_normalize_unicode(b.strip()), eof)

def _derive_new_contents(file_path: str, chunks, original_text: str):
    has_bom, text = _strip_bom(original_text)
    orig_lines=text.split("\n")
    if orig_lines and orig_lines[-1]=="":
        orig_lines.pop()
    reps=[]
    idx=0
    for ch in chunks:
        ctx=ch.get("change_context")
        if ctx:
            found=_seek_sequence(orig_lines, [ctx], idx)
            if found==-1:
                raise ValueError(f"Failed to find context '{ctx}' in {file_path}")
            idx=found+1
        old=ch.get("old_lines",[])
        new=ch.get("new_lines",[])
        is_eof=ch.get("is_end_of_file")
        if len(old)==0:
            ins=len(orig_lines)-1 if orig_lines and orig_lines[-1]=="" else len(orig_lines)
            reps.append((ins,0,new))
            continue
        pat=old[:]
        ns=new[:]
        found=_seek_sequence(orig_lines, pat, idx, bool(is_eof))
        if found==-1 and pat and pat[-1]=="":
            pat=pat[:-1]
            if ns and ns[-1]=="":
                ns=ns[:-1]
            found=_seek_sequence(orig_lines, pat, idx, bool(is_eof))
        if found!=-1:
            reps.append((found, len(pat), ns))
            idx=found+len(pat)
        else:
            raise ValueError(f"Failed to find expected lines in {file_path}:\n"+"\n".join(old))
    reps.sort(key=lambda x: x[0])
    res=orig_lines[:]
    for s,ol,ns in reversed(reps):
        res[s:s+ol]=ns
    if not res or res[-1]!="":
        res.append("")
    new_text="\n".join(res)
    _, stripped = _strip_bom(new_text)
    # preserve BOM
    final = ("\ufeff" + stripped) if has_bom else stripped
    # diff
    old_text=text
    # generate diff body via difflib for metadata but simple
    return final, has_bom



class ExecutionOrchestrator:
    """Stateless orchestrator aligned to opencode tool behaviors, full-access filesystem."""

    def __init__(self, settings: Any, appserver: Any, *ignored: Any):
        self.settings = settings
        self.appserver = appserver
        self.store = None
        self.registry = None
        from .operations import OperationRouter
        self.router = OperationRouter(appserver, settings)
        self._carrier = None
        try:
            from .appserver.mcp_carrier import McpCarrier
            self._carrier = McpCarrier(appserver)
        except Exception:
            pass

    # ---- opencode-aligned core tools ----

    async def read(self, filePath: str, offset: Optional[int] = None, limit: Optional[int] = None) -> dict[str, Any]:
        # opencode: filePath absolute, offset 1-indexed, limit default 2000
        resolved = _resolve_absolute(filePath)
        if not os.path.exists(resolved):
            # suggest similar
            dirp=os.path.dirname(resolved)
            base=os.path.basename(resolved)
            sugg=[]
            try:
                for e in os.listdir(dirp):
                    if base.lower() in e.lower() or e.lower() in base.lower():
                        sugg.append(os.path.join(dirp, e))
                        if len(sugg)>=3:
                            break
            except Exception:
                pass
            if sugg:
                raise ExecutionError("not_found", f"File not found: {resolved}\n\nDid you mean one of these?\n"+"\n".join(sugg))
            raise ExecutionError("not_found", f"File not found: {resolved}")
        stat=os.stat(resolved)
        is_dir=os.path.isdir(resolved)
        if is_dir:
            entries=[]
            try:
                with os.scandir(resolved) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                target=os.stat(entry.path) if os.path.exists(entry.path) else None
                                if target and os.path.isdir(entry.path):
                                    entries.append(entry.name+"/")
                                else:
                                    entries.append(entry.name)
                            elif entry.is_dir(follow_symlinks=False):
                                entries.append(entry.name+"/")
                            else:
                                entries.append(entry.name)
                        except Exception:
                            entries.append(entry.name)
            except Exception as e:
                raise ExecutionError("read_error", str(e))
            entries.sort(key=lambda x: x.lower())
            lim = int(limit) if limit is not None else DEFAULT_READ_LIMIT
            off = int(offset) if offset else 1
            start=off-1
            sliced=entries[start:start+lim]
            truncated = start+len(sliced) < len(entries)
            title=_rel_title(resolved).replace("\\","/")
            out_lines=[f"<path>{resolved}</path>","<type>directory</type>","<entries>", "\n".join(sliced)]
            if truncated:
                out_lines.append(f"\n(Showing {len(sliced)} of {len(entries)} entries. Use 'offset' parameter to read beyond entry {off+len(sliced)})")
            else:
                out_lines.append(f"\n({len(entries)} entries)")
            out_lines.append("</entries>")
            return {"title": title, "output": "\n".join(out_lines), "metadata": {"preview": "\n".join(sliced[:20]), "truncated": truncated}, "entries": sliced, "truncated": truncated, "totalEntries": len(entries)}

        # file
        # sample for binary / mime
        try:
            with open(resolved, "rb") as f:
                sample=f.read(SAMPLE_BYTES)
                f.seek(0, os.SEEK_END)
                size=f.tell()
        except Exception as e:
            raise ExecutionError("read_error", str(e))
        mime=mimetypes.guess_type(resolved)[0] or ""
        is_image = mime in SUPPORTED_IMAGE_MIMES
        is_pdf = mime=="application/pdf"
        if is_image or is_pdf:
            try:
                with open(resolved, "rb") as f:
                    data=f.read()
                b64=base64.b64encode(data).decode()
                msg="PDF read successfully" if is_pdf else "Image read successfully"
                return {"title": _rel_title(resolved), "output": msg, "metadata": {"preview": msg, "truncated": False}, "mime": mime, "dataBase64": b64}
            except Exception as e:
                raise ExecutionError("read_error", str(e))
        if _is_binary_file(resolved, sample):
            raise ExecutionError("binary", f"Cannot read binary file: {resolved}")
        # text file read with limits
        lim = int(limit) if limit is not None else DEFAULT_READ_LIMIT
        off = int(offset) if offset else 1
        raw=[]
        count=0
        cut=False
        more=False
        done=False
        bytes_used=0
        try:
            with open(resolved, "r", encoding="utf-8", errors="strict") as f:
                for line in f:
                    count+=1
                    if count < off:
                        continue
                    if len(raw) >= lim:
                        more=True
                        continue
                    text=line.rstrip("\r\n")
                    if len(text) > MAX_LINE_LENGTH:
                        text=text[:MAX_LINE_LENGTH]+MAX_LINE_SUFFIX
                    sz=len(text.encode("utf-8")) + (1 if raw else 0)
                    if bytes_used + sz <= MAX_BYTES:
                        raw.append(text)
                        bytes_used+=sz
                    else:
                        cut=True
                        more=True
                        done=True
                        break
                # count remaining lines if not truncated due to limit
                if not done:
                    # we already counted lines read; need total lines
                    # if we broke early due to more, count is already at limit start, but need total
                    # continue counting without storing
                    if more and len(raw)>=lim:
                        # need to count total
                        # we already have count = off+len(raw)-1 plus remaining
                        # continue reading
                        for _ in f:
                            count+=1
        except UnicodeDecodeError:
            raise ExecutionError("binary", f"Cannot read binary file: {resolved}")
        except Exception as e:
            raise ExecutionError("read_error", str(e))
        if count < off and not (count==0 and off==1):
            raise ExecutionError("out_of_range", f"Offset {off} is out of range for this file ({count} lines)")
        last = off+len(raw)-1 if raw else off-1
        nxt = last+1
        truncated = more or cut
        out=[f"<path>{resolved}</path>","<type>file</type>","<content>\n"]
        out.append("\n".join(f"{i+off}: {l}" for i,l in enumerate(raw)))
        if cut:
            out.append(f"\n\n(Output capped at {MAX_BYTES_LABEL}. Showing lines {off}-{last}. Use offset={nxt} to continue.)")
        elif more:
            out.append(f"\n\n(Showing lines {off}-{last} of {count}. Use offset={nxt} to continue.)")
        else:
            out.append(f"\n\n(End of file - total {count} lines)")
        out.append("\n</content>")
        output="\n".join(out)
        return {"title": _rel_title(resolved), "output": output, "metadata": {"preview": "\n".join(raw[:20]), "truncated": truncated}, "content": "\n".join(raw), "truncated": truncated, "totalLines": count, "lineStart": off, "lineEnd": last}

    async def write(self, filePath: str, content: str) -> dict[str, Any]:
        resolved=_resolve_absolute(filePath)
        existed=os.path.exists(resolved)
        old_text=""
        old_bytes=b""
        bom=False
        if existed:
            try:
                with open(resolved, "rb") as f:
                    old_bytes=f.read()
                # decode with BOM handling
                text=old_bytes.decode("utf-8")
                bom, old_text = _strip_bom(text)
            except UnicodeDecodeError:
                # binary previous - treat as empty for diff
                old_text=""
                bom=False
                old_bytes=b""
            except Exception as e:
                raise ExecutionError("read_error", str(e))
        # desired BOM
        has_new_bom, new_stripped = _strip_bom(content)
        desired_bom = bom or has_new_bom
        new_text=new_stripped
        new_bytes=_join_bom(new_text, desired_bom).encode("utf-8")
        diff=trim_diff(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=resolved, tofile=resolved, lineterm="") and "\n".join([f"diff --git a/{resolved} b/{resolved}"]+ (["new file mode 100644"] if not existed else []) + list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=resolved if existed else "/dev/null", tofile=resolved, lineterm="")) + [""]) or "")
        # actually generate diff correctly
        try:
            old_lines=old_text.splitlines()
            new_lines=new_text.splitlines()
            body=list(difflib.unified_diff(old_lines, new_lines, fromfile=resolved if existed else "/dev/null", tofile=resolved, lineterm=""))
            if body:
                header=[f"diff --git a/{resolved} b/{resolved}"]
                if not existed:
                    header.append("new file mode 100644")
                diff="\n".join(header+body+[""])
            else:
                diff=""
            diff=trim_diff(diff) if diff else ""
        except Exception:
            diff=""
        # write
        try:
            os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
            with open(resolved, "wb") as f:
                f.write(new_bytes)
        except Exception as e:
            raise ExecutionError("write_error", str(e))
        return {"title": _rel_title(resolved), "output": "Wrote file successfully.", "metadata": {"filepath": resolved, "exists": existed}, "path": resolved, "bytesWritten": len(new_bytes), "written": True, "changed": old_bytes!=new_bytes, "diff": diff, "diffTruncated": len(diff)>MAX_WIDGET_DIFF_CHARS}

    async def edit(self, filePath: str, oldString: str, newString: str, replaceAll: bool = False) -> dict[str, Any]:
        if oldString==newString:
            raise ExecutionError("invalid_edit", "No changes to apply: oldString and newString are identical.")
        resolved=_resolve_absolute(filePath)
        if oldString=="":
            existed=os.path.exists(resolved)
            if existed:
                raise ExecutionError("invalid_edit", "oldString cannot be empty when editing an existing file. Provide the exact text to replace, or use write for an intentional full-file replacement.")
            # create new file
            has_bom, new_text = _strip_bom(newString)
            diff=trim_diff("\n".join([f"diff --git a/{resolved} b/{resolved}","new file mode 100644"]+list(difflib.unified_diff([],[new_text], fromfile="/dev/null", tofile=resolved, lineterm=""))+[""]))
            try:
                os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
                with open(resolved, "wb") as f:
                    f.write(_join_bom(new_text, has_bom).encode("utf-8"))
            except Exception as e:
                raise ExecutionError("write_error", str(e))
            return {"title": _rel_title(resolved), "output": "Edit applied successfully.", "metadata": {"diff": diff}, "diff": diff}
        # existing file
        if not os.path.exists(resolved):
            raise ExecutionError("not_found", f"File {resolved} not found")
        if os.path.isdir(resolved):
            raise ExecutionError("is_directory", f"Path is a directory, not a file: {resolved}")
        try:
            with open(resolved, "rb") as f:
                raw=f.read()
            text=raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ExecutionError("binary", f"Cannot edit binary file: {resolved}")
        except Exception as e:
            raise ExecutionError("read_error", str(e))
        has_bom, old_text = _strip_bom(text)
        # line ending detection
        ending="\r\n" if "\r\n" in old_text else "\n"
        def norm(t): return t.replace("\r\n","\n")
        def to_ending(t, e): return t.replace("\n", e) if e=="\r\n" else t
        old_norm= to_ending(norm(oldString), ending)
        new_norm= to_ending(norm(newString), ending)
        # perform replace
        new_content_norm = _replace_content(norm(old_text), norm(old_norm), norm(new_norm), bool(replaceAll))
        # convert back? keep \n normalized then re-apply ending
        if ending=="\r\n":
            new_content = new_content_norm.replace("\n", "\r\n")
            old_for_diff = norm(old_text)
            new_for_diff = new_content_norm
        else:
            new_content = new_content_norm
            old_for_diff = old_text
            new_for_diff = new_content
        # BOM handling
        _, new_stripped = _strip_bom(new_content)
        desired_bom = has_bom or newString.startswith("\ufeff")
        final_bytes=_join_bom(new_stripped, desired_bom).encode("utf-8")
        # diff
        try:
            body=list(difflib.unified_diff(norm(old_text).splitlines(), norm(new_content).splitlines(), fromfile=resolved, tofile=resolved, lineterm=""))
            diff="\n".join([f"diff --git a/{resolved} b/{resolved}"]+body+[""]) if body else ""
            diff=trim_diff(diff)
        except Exception:
            diff=""
        try:
            os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
            with open(resolved, "wb") as f:
                f.write(final_bytes)
        except Exception as e:
            raise ExecutionError("write_error", str(e))
        # diff stats
        adds=dels=0
        for ch in difflib.unified_diff(old_for_diff.splitlines(), new_for_diff.splitlines(), lineterm=""):
            # use diffLines count
            pass
        # use simple
        import difflib as _d
        for line in _d.unified_diff(old_text.splitlines(), new_content.splitlines()):
            if line.startswith("+") and not line.startswith("+++"):
                adds+=1
            if line.startswith("-") and not line.startswith("---"):
                dels+=1
        return {"title": _rel_title(resolved), "output": "Edit applied successfully.", "metadata": {"diff": diff}, "diff": diff, "additions": adds, "deletions": dels}

    async def glob(self, pattern: str, path: Optional[str] = None) -> dict[str, Any]:
        search=_resolve_absolute(path) if path else os.getcwd()
        if os.path.isfile(search):
            raise ExecutionError("invalid_path", f"glob path must be a directory: {search}")
        if not os.path.isdir(search):
            raise ExecutionError("not_found", f"Directory not found: {search}")
        limit=100
        # use globlib with recursive
        # ripgrep glob respects pattern relative to cwd
        # we emulate via pathlib
        base=Path(search)
        # handle pattern like **/*.js
        try:
            # use globlib.glob with recursive
            full_pattern=os.path.join(search, pattern)
            files=globlib.glob(full_pattern, recursive=True)
            # filter to files only, relative
            rel_files=[]
            for f in files:
                # glob may return dirs; include all matching
                p=Path(f)
                # ensure inside search
                try:
                    rel=p.relative_to(base)
                except Exception:
                    rel=Path(os.path.relpath(f, search))
                # ripgrep only returns files? but we include both
                rel_files.append((str(rel).replace("\\","/"), f))
            # sort
            rel_files.sort(key=lambda x: x[0])
            # deduplicate and limit
            seen=set()
            out=[]
            for rel, abs_p in rel_files:
                if abs_p not in seen:
                    seen.add(abs_p)
                    out.append(os.path.abspath(abs_p))
                if len(out)>=limit:
                    break
            truncated=len(rel_files)>=limit or len(out)==limit and len(rel_files)>limit
            # if we limited, need to check if more
            if len(rel_files)>limit:
                truncated=True
            output=[]
            if not out:
                output.append("No files found")
            else:
                output.extend(out)
                if truncated:
                    output.append("")
                    output.append(f"(Results are truncated: showing first {limit} results. Consider using a more specific path or pattern.)")
            return {"title": _rel_title(search), "output": "\n".join(output), "metadata": {"count": len(out), "truncated": truncated}, "files": [{"path": p} for p in out], "truncated": truncated}
        except Exception as e:
            raise ExecutionError("glob_error", str(e))

    async def grep(self, pattern: str, path: Optional[str] = None, include: Optional[str] = None) -> dict[str, Any]:
        if not pattern:
            raise ExecutionError("invalid_pattern", "pattern is required")
        try:
            regex=re.compile(pattern)
        except re.error as e:
            raise ExecutionError("invalid_regex", f"Invalid regex: {e}")
        search=_resolve_absolute(path) if path else os.getcwd()
        # if file, use its dir
        cwd=search
        if os.path.isfile(search):
            cwd=os.path.dirname(search)
        elif not os.path.isdir(search):
            raise ExecutionError("not_found", f"Path not found: {search}")
        limit=100
        rows=[]
        # walk
        for root, dirs, files in os.walk(cwd):
            # skip .git, node_modules for performance? keep simple
            # need to respect include filter
            for fname in files:
                fpath=os.path.join(root, fname)
                # include filter
                if include:
                    # include is glob like "*.js" or "*.{ts,tsx}"
                    # expand brace
                    incs=[]
                    if "{" in include and "}" in include:
                        # simple brace expand: *.{ts,tsx} -> [*.ts, *.tsx]
                        m=re.match(r"^(.*)\{([^}]+)\}(.*)$", include)
                        if m:
                            pre, body, post=m.groups()
                            for part in body.split(","):
                                incs.append(pre+part.strip()+post)
                        else:
                            incs=[include]
                    else:
                        incs=[include]
                    matched=False
                    for inc in incs:
                        if fnmatch.fnmatch(fname, inc) or fnmatch.fnmatch(os.path.relpath(fpath, cwd).replace("\\","/"), inc) or fnmatch.fnmatch(fpath, inc):
                            matched=True
                            break
                    if not matched:
                        continue
                # try read as text
                try:
                    with open(fpath, "r", encoding="utf-8", errors="strict") as fh:
                        for lineno, line in enumerate(fh, 1):
                            if regex.search(line):
                                rows.append((os.path.abspath(fpath), lineno, line.rstrip("\n")[:500]))
                                if len(rows)>=limit:
                                    break
                except Exception:
                    continue
                if len(rows)>=limit:
                    break
            if len(rows)>=limit:
                break
        if not rows:
            return {"title": pattern, "output": "No files found", "metadata": {"matches": 0, "truncated": False}, "matches": 0, "truncated": False}
        truncated=len(rows)==limit
        total=len(rows)
        out=[f"Found {total} matches{' (more matches available)' if truncated else ''}"]
        cur=""
        for p, lno, txt in rows:
            if cur!=p:
                if cur!="":
                    out.append("")
                cur=p
                out.append(f"{p}:")
            out.append(f"  Line {lno}: {txt}")
        if truncated:
            out.append("")
            out.append("(Results truncated. Consider using a more specific path or pattern.)")
        return {"title": pattern, "output": "\n".join(out), "metadata": {"matches": total, "truncated": truncated}, "matches": total, "truncated": truncated, "rows": [{"path": p, "line": l, "text": t} for p,l,t in rows]}

    async def bash(self, command: str, timeout: Optional[int] = None, workdir: Optional[str] = None) -> dict[str, Any]:
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
            if is_pwsh:
                proc=subprocess.Popen([shell, "-NoLogo","-NoProfile","-NonInteractive","-Command", command], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            else:
                proc=subprocess.Popen(command, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", executable=shell if shell else None)
            try:
                out, _ = proc.communicate(timeout=(eff_timeout+100)/1000.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    out, _ = proc.communicate(timeout=3)
                except Exception:
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

    async def apply_patch(self, patchText: str) -> dict[str, Any]:
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
        # apply
        for ch in file_changes:
            typ=ch["type"]
            if typ=="add":
                os.makedirs(os.path.dirname(ch["filePath"]) or ".", exist_ok=True)
                with open(ch["filePath"], "wb") as fh:
                    fh.write(_join_bom(ch["newContent"], ch["bom"]).encode("utf-8"))
            elif typ=="update":
                os.makedirs(os.path.dirname(ch["filePath"]) or ".", exist_ok=True)
                with open(ch["filePath"], "wb") as fh:
                    fh.write(_join_bom(ch["newContent"], ch["bom"]).encode("utf-8"))
            elif typ=="move":
                dest=ch["movePath"]
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(_join_bom(ch["newContent"], ch["bom"]).encode("utf-8"))
                try:
                    os.remove(ch["filePath"])
                except FileNotFoundError:
                    pass
            elif typ=="delete":
                try:
                    os.remove(ch["filePath"])
                except FileNotFoundError:
                    pass
        summary=[f"{'A' if c['type']=='add' else 'D' if c['type']=='delete' else 'M'} {c['rel']}" for c in file_changes]
        output="Success. Updated the following files:\n"+"\n".join(summary)
        files=[{"filePath": c["filePath"], "relativePath": c["rel"], "type": c["type"], "patch": c["diff"], "additions": c["additions"], "deletions": c["deletions"], **({"movePath": c["movePath"]} if c.get("movePath") else {})} for c in file_changes]
        return {"title": output, "output": output, "metadata": {"diff": total_diff, "files": files}, "diff": total_diff, "files": files, "applied": True, "fileChanges": [c["rel"] for c in file_changes]}

    async def view_image(self, path: str) -> dict[str, Any]:
        resolved=_resolve_absolute(path)
        if not os.path.exists(resolved):
            raise ExecutionError("not_found", f"File not found: {resolved}")
        mime=mimetypes.guess_type(resolved)[0] or "application/octet-stream"
        if not mime.startswith("image/"):
            raise ExecutionError("not_an_image", f"unsupported image type: {mime}")
        with open(resolved, "rb") as f:
            raw=f.read()
        return {"path": resolved, "mimeType": mime, "sizeBytes": len(raw), "dataBase64": base64.b64encode(raw).decode()}

    async def browse_dir(self, path: str = "") -> dict[str, Any]:
        target=os.path.realpath(os.path.abspath(os.path.expanduser(path or os.getcwd())))
        if not os.path.isdir(target):
            return {"path": target, "parent": None, "entries": [], "error": "directory does not exist"}
        entries=[]
        try:
            with os.scandir(target) as it:
                for entry in sorted(it, key=lambda x: (not x.is_dir(follow_symlinks=False), x.name.lower()))[:200]:
                    entries.append({"name": entry.name, "path": entry.path, "isDirectory": entry.is_dir(follow_symlinks=False)})
        except OSError as exc:
            return {"path": target, "parent": None, "entries": [], "error": str(exc)}
        parent=os.path.dirname(target)
        return {"path": target, "parent": parent if parent!=target else None, "entries": entries}

    async def list_mcp_tools(self) -> dict[str, Any]:
        response: dict[str, Any] = {}
        try:
            response = await self.appserver.mcp_server_status_list()
        except Exception:
            if self._carrier is not None:
                try:
                    carrier = await self._carrier.thread_id("__full_access__")
                    response = await self.appserver.mcp_server_status_list(carrier)
                except Exception:
                    response = {}
        servers = (response or {}).get("data") or []
        out: list[dict[str, Any]] = []
        for server in servers:
            name = str(server.get("name") or "")
            raw_tools = server.get("tools") or {}
            tool_items = list(raw_tools.values()) if isinstance(raw_tools, dict) else list(raw_tools or [])
            tools: list[dict[str, Any]] = []
            for tool in tool_items:
                tool_name = str(tool.get("name") or "")
                ann = tool.get("annotations") or {}
                tools.append({"name": tool_name, "description": str(tool.get("description") or ""), "inputSchema": tool.get("inputSchema") or tool.get("input_schema") or {}, "readOnly": bool(ann.get("readOnlyHint")), "policy": "allow"})
            tools.sort(key=lambda x: x["name"])
            out.append({"name": name, "authStatus": str(server.get("authStatus") or ""), "tools": tools})
        out.sort(key=lambda x: x["name"])
        return {"conversationId": "", "servers": out}

    async def mcp_tool_call(self, server: str, tool: str, arguments: Optional[dict], timeout_ms: Optional[int] = None) -> dict[str, Any]:
        effective_timeout = timeout_ms if isinstance(timeout_ms, int) and timeout_ms > 0 else MCP_TOOL_TIMEOUT_MS
        carrier = None
        if self._carrier is not None:
            try:
                carrier = await self._carrier.thread_id("__full_access__")
            except Exception:
                carrier = None
        result = None
        if carrier:
            try:
                result = await self.appserver.mcp_tool_call(carrier, server, tool, arguments or {}, timeout=max(1.0, effective_timeout / 1000.0))
            except Exception:
                result = None
        if result is None:
            try:
                result = await self.appserver.mcp_tool_call("__full_access__", server, tool, arguments or {}, timeout=max(1.0, effective_timeout / 1000.0))
            except Exception as exc:
                raise ExecutionError("mcp_tool_failed", str(exc)) from exc
        return {"conversationId": "", "server": server, "tool": tool, "content": (result or {}).get("content") or [], "structuredContent": (result or {}).get("structuredContent"), "isError": bool((result or {}).get("isError"))}

    async def update_plan(self, plan: list[dict], explanation: str = "") -> dict[str, Any]:
        statuses = [str(item.get("status") or "pending") for item in plan]
        if any(s not in {"pending", "in_progress", "completed"} for s in statuses):
            raise ExecutionError("invalid_plan", "unsupported plan status")
        if statuses.count("in_progress") > 1:
            raise ExecutionError("invalid_plan", "at most one plan item may be in_progress")
        return {"conversationId": "", "updated": True, "plan": plan, "explanation": explanation}

    def mcp_tool_policies(self) -> dict[str, str]:
        return {}

    def set_mcp_tool_policy(self, policies: dict[str, str]) -> dict[str, str]:
        return {}

def _tail_output(text: str, max_lines: int, max_bytes: int):
    lines=text.split("\n")
    if len(lines)<=max_lines and len(text.encode("utf-8"))<=max_bytes:
        return text
    out=[]
    used=0
    for i in range(len(lines)-1, -1, -1):
        if len(out)>=max_lines:
            break
        sz=len(lines[i].encode("utf-8"))+(1 if out else 0)
        if used+sz>max_bytes:
            if not out:
                buf=lines[i].encode("utf-8")
                start=len(buf)-max_bytes
                if start<0:
                    start=0
                while start<len(buf) and (buf[start] & 0xC0)==0x80:
                    start+=1
                out.insert(0, buf[start:].decode("utf-8", errors="replace"))
            break
        out.insert(0, lines[i])
        used+=sz
    return "\n".join(out)

