"""工作区接口（设计文档 4.1：文件 + 执行）。

交给智能体的部分直接用 deepagents 的工作区后端协议（SandboxBackendProtocol，
设计文档 4"不过度包装"）：换成 E2B、Daytona 等云沙箱时，它们有官方适配。
backend 用到的产物列表、下载、删除另列在这里。
"""

from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol

from deepagents.backends.protocol import SandboxBackendProtocol


@dataclass(frozen=True)
class CommandResult:
    """执行一条命令的结果。"""

    output: str  # 标准输出与标准错误按到达先后拼在一起（给模型看）
    # 退出码：超时 124，没等到退出 -1（设计 2026-10-23 5.4，原来会被当成 0）
    exit_code: int
    truncated: bool = False  # 输出过长被截断（完整输出在会话目录的 logs/）
    timed_out: bool = False
    stderr: str = ""  # 另存的标准错误（最后一段），交给界面单独显示


# 这次工具调用里执行过的命令结果（设计 2026-10-23 5.4）：deepagents 的执行工具只把退出码写进
# 工具结果的附加信息，错误输出、是否超时传不出来；包着工具调用的中间件放好列表，工作区往里追加
COMMAND_RESULTS: ContextVar[list[CommandResult] | None] = ContextVar(
    "command_results", default=None
)


class Sandbox(Protocol):
    """执行命令的地方：在会话目录 /workspace/<会话短 ID>/ 下执行。请求被取消时须终止命令。"""

    async def run(self, session: str, command: str, *, time_limit: int | None) -> CommandResult: ...


@dataclass(frozen=True)
class OutputFile:
    """会话 outputs/ 下的一个文件（产物）。"""

    path: str  # 相对会话目录，如 outputs/chart.png
    size: int
    modified: float  # 修改时间（Unix 秒）


@dataclass(frozen=True)
class OpenedFile:
    """已打开、可分块读取的文件（下载时边读边传）。"""

    size: int
    chunks: AsyncIterator[bytes]


class Workspace(Protocol):
    @property
    def agent_backend(self) -> SandboxBackendProtocol:
        """交给智能体的工作区后端：只能读写本会话目录，执行命令交给 Sandbox。"""
        ...

    async def prepare(self, short_id: str) -> None:
        """建好会话目录与其中的 outputs/（每次运行开始时调用，已存在时什么也不做）。"""
        ...

    async def list_outputs(self, short_id: str) -> list[OutputFile]:
        """会话 outputs/ 下的全部文件（含子目录）。"""
        ...

    async def read_file(self, short_id: str, path: str) -> bytes:
        """读取会话目录里的文件（path 相对会话目录）。

        越界（含指向会话目录外的链接）抛 PermissionError；不存在或不是普通文件抛 FileNotFoundError。
        """
        ...

    async def open_file(self, short_id: str, path: str) -> OpenedFile:
        """打开会话目录里的文件供分块读取；检查与报错同 read_file，在打开时就完成。"""
        ...

    async def save_upload(
        self, short_id: str, name: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> OutputFile:
        """把上传的文件存到会话的 uploads/，返回实际保存的位置（相对会话目录）与大小。

        只取文件名本身（去掉目录部分与开头的点）；已有同名文件时加序号，不覆盖。
        超过 max_bytes 抛 common.errors.TooLargeError，不留下不完整的文件。
        """
        ...

    async def remove(self, short_id: str) -> None:
        """删除整个会话目录；不存在时什么也不做。"""
        ...
