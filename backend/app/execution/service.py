from __future__ import annotations
from typing import Any
from .errors import normalize_error
from .filesystem import FilesystemService
from .search import SearchService
from .shell import ShellService
from .patch import PatchService

class ExecutionService:
    """Capability composition root; independent from transport."""
    def __init__(self, settings: Any):
        self.settings=settings
        self.filesystem=FilesystemService(settings)
        self.search=SearchService(settings)
        self.shell=ShellService(settings)
        self.patch=PatchService(settings)
    async def _invoke(self, method: Any, *args: Any) -> Any:
        try: return await method(*args)
        except Exception as exc: raise normalize_error(exc) from exc
    async def read(self,file_path:str,offset:int|None=None,limit:int|None=None): return await self._invoke(self.filesystem.read,file_path,offset,limit)
    async def write(self,file_path:str,content:str): return await self._invoke(self.filesystem.write,file_path,content)
    async def edit(self,file_path:str,old_string:str,new_string:str,replace_all:bool=False): return await self._invoke(self.filesystem.edit,file_path,old_string,new_string,replace_all)
    async def delete(self,file_path:str): return await self._invoke(self.filesystem.delete,file_path)
    async def glob(self,pattern:str,path:str|None=None): return await self._invoke(self.search.glob,pattern,path)
    async def grep(self,pattern:str,path:str|None=None,include:str|None=None): return await self._invoke(self.search.grep,pattern,path,include)
    async def bash(self,command:str,timeout:int|None=None,workdir:str|None=None): return await self._invoke(self.shell.execute,command,timeout,workdir)
    async def apply_patch(self,patch_text:str): return await self._invoke(self.patch.apply,patch_text)
    async def view_image(self,path:str): return await self._invoke(self.filesystem.view_image,path)
    async def browse_dir(self,path:str=""): return await self._invoke(self.filesystem.browse_dir,path)
    async def update_plan(self,plan:list[dict],explanation:str=""):
        statuses=[str(item.get("status") or "pending") for item in plan]
        if any(s not in {"pending","in_progress","completed"} for s in statuses): raise ValueError("unsupported plan status")
        if statuses.count("in_progress")>1: raise ValueError("at most one plan item may be in_progress")
        return {"conversationId":"","updated":True,"plan":plan,"explanation":explanation}
    def mcp_tool_policies(self)->dict[str,str]: return {}
    def set_mcp_tool_policy(self,policies:dict[str,str])->dict[str,str]: return {}
    def capabilities(self)->list[str]: return ["read","write","edit","glob","grep","bash","apply_patch","view_image","browse_dir"]
