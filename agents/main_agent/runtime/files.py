"""智能体的文件树（设计文档 7.3）：工作区为默认后端，/skills/ 只读，/.agent/ 是智能体内部文件。

技能只有一处（D22）：/skills/ 对应 .workdata/skills/，停用的技能在里面看不见。
"""

from collections.abc import Awaitable, Callable, Set
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
)
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from agents.main_agent.context import AgentContext

if TYPE_CHECKING:
    from agents.main_agent.runtime.skills import SkillCatalog

# deepagents 把超长工具输出、压缩时移出的对话历史等放在这个根下。路由到"状态内存储"：
# 与对话存档一起按会话保存、随会话删除；放进工作区会被会话目录限制拒绝，也会混进用户的文件
AGENT_FILES = "/.agent"


SKILLS_ROOT = "/skills/"  # 技能目录在智能体文件树里的位置（D22：只有一处）


def build_file_tree(
    workspace: SandboxBackendProtocol, skills: "SkillCatalog | None"
) -> CompositeBackend:
    routes: dict[str, Any] = {f"{AGENT_FILES}/": StateBackend()}
    if skills is not None and skills.skills_dir is not None:
        routes[SKILLS_ROOT] = SkillsFilesystem(skills.skills_dir, skills.hidden)
    # 工作区必须是默认后端：deepagents 只把执行命令交给默认后端（设计文档 7.3）
    return CompositeBackend(default=workspace, routes=routes, artifacts_root=AGENT_FILES)


class ReadOnlyFilesystem(FilesystemBackend):
    """只读目录（技能文件只在技能页上增删，智能体不能改）。"""

    def __init__(self, root: Path) -> None:
        super().__init__(root_dir=root, virtual_mode=True)

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=f"{file_path} 是只读的")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return EditResult(error=f"{file_path} 是只读的")

    def delete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error=f"{file_path} 是只读的")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=path, error="permission_denied") for path, _ in files]


class SkillsFilesystem(ReadOnlyFilesystem):
    """技能目录：第一层文件夹在 hidden() 里的（停用的技能）智能体看不见、读不到。"""

    def __init__(self, root: Path, hidden: Callable[[], Set[str]]) -> None:
        super().__init__(root)
        self._hidden = hidden

    def _visible(self, path: str) -> bool:
        # 不分大小写：.workdata 在 Mac 上不分大小写，/EXCEL/ 读到的就是停用的 excel（积压小问题 F7）
        top = path.strip("/").split("/", 1)[0].casefold()
        return top not in {name.casefold() for name in self._hidden()}

    def ls(self, path: str) -> LsResult:
        result = super().ls(path)
        if result.entries is not None:
            result.entries = [e for e in result.entries if self._visible(e["path"])]
        return result

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        if not self._visible(file_path):
            return ReadResult(error=f"文件不存在：{file_path}")
        return super().read(file_path, offset, limit)

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        result = super().glob(pattern, path)
        result.matches = [m for m in result.matches or [] if self._visible(m["path"])]
        return result

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
        context_lines: int = 0,
    ) -> GrepResult:
        result = super().grep(pattern, path, glob, max_count=max_count, context_lines=context_lines)
        return self._filter_grep(result)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
        context_lines: int = 0,
    ) -> GrepResult:
        result = await super().agrep(
            pattern, path, glob, max_count=max_count, context_lines=context_lines
        )
        return self._filter_grep(result)

    def _filter_grep(self, result: GrepResult) -> GrepResult:
        result.matches = [m for m in result.matches or [] if self._visible(m["path"])]
        return result

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        visible = super().download_files([p for p in paths if self._visible(p)])
        found = {response.path: response for response in visible}
        return [
            found.get(path) or FileDownloadResponse(path=path, error="file_not_found")
            for path in paths
        ]


class WorkDirectoryMiddleware(AgentMiddleware):
    """每次调用模型前，在系统提示词末尾写明本会话的工作目录（各会话不同，不能写死在提示词里）。"""

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return handler(self._with_note(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._with_note(request))

    @staticmethod
    def _with_note(request: ModelRequest) -> ModelRequest:
        short_id = cast(AgentContext, request.runtime.context).thread_short_id
        note = (
            f"\n\n当前会话的工作目录是 /workspace/{short_id}/：要执行的代码和中间文件都放在这里，"
            f"交给用户的文件（图表、表格、报告等）放到 /workspace/{short_id}/outputs/。"
        )
        base = request.system_prompt or ""
        return request.override(system_message=SystemMessage(content=base + note))


# write_file 的说明（设计 2026-10-23 5.6）：deepagents 原文说"不用先读文件"，而工作区会拒绝没读过
# 最新版就覆盖已有文件，说明要跟着改，模型才知道先读
WRITE_FILE_DESCRIPTION = """Writes content to a file. Creates the file if it does not exist; replaces it entirely if it does.

Usage:
- Use this tool when you intend to create a new file or replace the whole file.
- Before overwriting an existing file, read its latest version with read_file first; otherwise the write is refused with "先用 read_file 读最新版再改".
- Prefer to edit existing files (with the edit_file tool) over creating new ones when possible.
"""  # noqa: E501 - 与 deepagents 原文同样的写法，一行一条
