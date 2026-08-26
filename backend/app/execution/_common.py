from __future__ import annotations

import base64
import difflib
import fnmatch
import glob as globlib
import mimetypes
import os
import re
import signal
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional
from .errors import ExecutionError
logger = logging.getLogger(__name__)
MAX_WIDGET_DIFF_CHARS=200_000
DEFAULT_READ_LIMIT=2000
MAX_LINE_LENGTH=2000
MAX_LINE_SUFFIX=f"... (line truncated to {MAX_LINE_LENGTH} chars)"
MAX_BYTES=50*1024
MAX_BYTES_LABEL=f"{MAX_BYTES/1024:.0f} KB"
SAMPLE_BYTES=4096
SUPPORTED_IMAGE_MIMES={"image/jpeg","image/png","image/gif","image/webp"}
MAX_LINE_FALLBACK=100
MAX_BYTES_FALLBACK=50*1024
DEFAULT_SHELL_TIMEOUT_MS=2*60*1000
SEARCH_RESULT_LIMIT=100
SEARCH_FILE_LIMIT=5000
SEARCH_FILE_SIZE_LIMIT=2*1024*1024
SEARCH_EXCLUDED_DIRS={".git",".hg",".svn","node_modules",".venv","venv","dist","build",".cache","coverage","target"}
BINARY_EXTS={".zip",".tar",".gz",".exe",".dll",".so",".class",".jar",".war",".7z",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".odt",".ods",".odp",".bin",".dat",".obj",".o",".a",".lib",".wasm",".pyc",".pyo"}


def _expand_include(include: str) -> list[str]:
    if "{" not in include or "}" not in include:
        return [include]
    match=re.match(r"^(.*)\{([^}]+)\}(.*)$", include)
    if not match:
        return [include]
    prefix, body, suffix=match.groups()
    return [prefix+part.strip()+suffix for part in body.split(",")]

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

def _atomic_write_bytes(path: str, data: bytes) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".chatcodex-write-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    except Exception as exc:
        try:
            os.remove(temp_path)
        except OSError as cleanup_exc:
            logger.debug("temporary write cleanup failed for %s: %s", temp_path, cleanup_exc)
        raise ExecutionError("write_error", str(exc)) from exc

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

def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """Terminate the shell and all children spawned by it."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        proc.terminate()

def _tail_output(text: str, max_lines: int, max_bytes: int):
    lines=text.split("\n")
    if len(lines)<=max_lines and len(text.encode("utf-8"))<=max_bytes: return text
    out=[]; used=0
    for i in range(len(lines)-1,-1,-1):
        if len(out)>=max_lines: break
        sz=len(lines[i].encode("utf-8"))+(1 if out else 0)
        if used+sz>max_bytes:
            if not out:
                buf=lines[i].encode("utf-8"); start=max(0,len(buf)-max_bytes)
                while start<len(buf) and (buf[start]&0xC0)==0x80: start+=1
                out.insert(0,buf[start:].decode("utf-8",errors="replace"))
            break
        out.insert(0,lines[i]); used+=sz
    return "\n".join(out)

def _terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None: return
    if os.name=="nt":
        subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False); return
    try: os.killpg(proc.pid,signal.SIGTERM)
    except ProcessLookupError: return
    except OSError: proc.terminate()

__all__ = [name for name in globals() if not name.startswith('__')]
