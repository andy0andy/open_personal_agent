"""工作区实现：本地会话目录 + 在智能体所在环境里执行命令（设计文档 9.1；D20）。

读写文件由 backend 直接做（虚拟根 / 映射到 WORKDATA_DIR，/workspace/<会话短 ID>/ 落在
WORKDATA_DIR/workspace/<会话短 ID>/）；执行命令交给 Sandbox（LocalSandbox）。后端镜像里 /workspace
指向工作区目录，所以智能体看到的路径与命令里的真实路径一致。
"""

import asyncio
import itertools
import os
import re
import shutil
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import BinaryIO

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    GlobResult,
    GrepResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
)
from langgraph.config import get_config
from langgraph.runtime import get_runtime

from agents.main_agent.context import AgentContext
from agents.main_agent.workspace.base import COMMAND_RESULTS, OpenedFile, OutputFile, Sandbox
from common.errors import TooLargeError

_SHORT_ID = re.compile(r"c_[0-9a-f]{8}")
# 覆盖、修改已有文件前没读过最新版（设计 2026-10-23 5.6）
READ_FIRST = "先用 read_file 读最新版再改"
_CHUNK = 64 * 1024
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f]")
# 文件系统限制文件名不超过 255 字节；留出同名时加的序号（如" (12)"）的余地
_MAX_NAME_BYTES = 200


def current_session() -> str:
    """当前运行所属会话的短 ID（从 LangGraph 运行时上下文读取，子智能体同样可读）。"""
    return get_runtime(AgentContext).context.thread_short_id


def current_caller() -> str:
    """当前是哪个智能体在调用：主智能体为空串，子智能体为它所在的检查点命名空间
    （与 runtime/tracker.py 同样的取法：去掉最后一段）。不在 LangGraph 的运行里时当作主智能体。"""
    try:
        config = get_config()
    except RuntimeError:
        return ""
    namespace = str((config.get("metadata") or {}).get("langgraph_checkpoint_ns", ""))
    return "|".join(namespace.split("|")[:-1])


class LocalWorkspace:
    def __init__(
        self,
        root: Path,
        sandbox: Sandbox,
        *,
        session: Callable[[], str] = current_session,
        caller: Callable[[], str] = current_caller,
    ) -> None:
        self._root = root.resolve()
        self._backend = _SessionBackend(self._root, sandbox, session, caller)

    @property
    def agent_backend(self) -> SandboxBackendProtocol:
        return self._backend

    async def prepare(self, short_id: str) -> None:
        await asyncio.to_thread(self._prepare, short_id)

    def _prepare(self, short_id: str) -> None:
        # 原来要等沙箱第一次执行命令才建，模型先查看自己的目录会得到"路径不存在"
        session = self._session_dir(short_id)
        _make_shared_dirs(session, session / "outputs")

    async def list_outputs(self, short_id: str) -> list[OutputFile]:
        return await asyncio.to_thread(self._list_outputs, short_id)

    def _list_outputs(self, short_id: str) -> list[OutputFile]:
        session = self._session_dir(short_id)
        outputs = session / "outputs"
        if not outputs.is_dir():
            return []
        files = []
        for path in outputs.rglob("*"):
            if path.is_file() and not path.is_symlink():
                stat = path.stat()
                files.append(
                    OutputFile(path.relative_to(session).as_posix(), stat.st_size, stat.st_mtime)
                )
        return files

    async def read_file(self, short_id: str, path: str) -> bytes:
        target = await asyncio.to_thread(self._existing_file, short_id, path)
        return await asyncio.to_thread(target.read_bytes)

    async def open_file(self, short_id: str, path: str) -> OpenedFile:
        target = await asyncio.to_thread(self._existing_file, short_id, path)
        handle = await asyncio.to_thread(target.open, "rb")
        return OpenedFile(size=os.fstat(handle.fileno()).st_size, chunks=_read_chunks(handle))

    def _existing_file(self, short_id: str, path: str) -> Path:
        session = self._session_dir(short_id).resolve()
        target = (session / path).resolve()  # 解析链接后再比对：指向会话目录外的链接也算越界
        if session not in target.parents:
            raise PermissionError(f"只能读取会话目录里的文件：{path}")
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在：{path}")
        return target

    async def save_upload(
        self, short_id: str, name: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> OutputFile:
        session = self._session_dir(short_id)
        await asyncio.to_thread(_make_shared_dirs, session, session / "uploads")
        target, handle = await asyncio.to_thread(_reserve, session / "uploads", _safe_name(name))
        size = 0
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise TooLargeError(f"文件超过 {max_bytes // (1024 * 1024)}MB 上限")
                await asyncio.to_thread(handle.write, chunk)
        except BaseException:  # 超限、请求中断（取消）都不留下不完整的文件
            handle.close()
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
        handle.close()
        stat = await asyncio.to_thread(target.stat)
        return OutputFile(f"uploads/{target.name}", size, stat.st_mtime)

    async def remove(self, short_id: str) -> None:
        session = self._session_dir(short_id)
        self._backend.forget(session)
        await asyncio.to_thread(shutil.rmtree, session, ignore_errors=True)

    def _session_dir(self, short_id: str) -> Path:
        if not _SHORT_ID.fullmatch(short_id):
            raise PermissionError(f"会话短 ID 格式不正确：{short_id}")
        return self._root / "workspace" / short_id


class _SessionBackend(FilesystemBackend, SandboxBackendProtocol):
    """交给智能体的工作区后端（deepagents 协议）。

    所有文件操作都经过 _resolve_path：在 deepagents 的虚拟根检查之外，再限定在本会话目录。
    越界抛 PermissionError（OSError）：deepagents 只把 OSError 变成工具错误交回智能体，
    其他异常（包括它自己对 .. 抛的 ValueError）会让整次运行失败。

    覆盖、修改已有文件前要读过最新版（设计 2026-10-23 5.6）：记下读过的文件与读时的修改时间、
    大小；没读过、或读后被改过（如命令改的）就拒绝，让模型先读。新建文件不查；写、改成功后更新记录
    （连续修改不用重读）。记录在内存里，重启后要重新读一次（这个方向是安全的）。
    主智能体与子智能体共用这一个后端，读过记录按调用方分开（积压小问题 D16）：主智能体读过、
    子智能体改过之后，主智能体要先重读才能覆盖。调用来自 to_thread 的工作线程，用锁保护。
    """

    def __init__(
        self,
        root: Path,
        sandbox: Sandbox,
        session: Callable[[], str],
        caller: Callable[[], str],
    ) -> None:
        super().__init__(root_dir=root, virtual_mode=True)
        self._sandbox = sandbox
        self._session = session
        self._caller = caller
        # （调用方, 真实路径）→ 读时的（修改时间 ns，大小）
        self._seen: dict[tuple[str, Path], tuple[int, int]] = {}
        self._seen_lock = threading.Lock()

    @property
    def id(self) -> str:
        return "local-workspace"

    def _resolve_path(self, key: str) -> Path:
        try:
            full = super()._resolve_path(key)
        except ValueError as exc:
            raise PermissionError(str(exc)) from None
        allowed = (self.cwd / "workspace" / self._session()).resolve()
        if full != allowed and allowed not in full.parents:
            raise PermissionError(f"只能访问本会话的工作目录 /workspace/{self._session()}/")
        return full

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        stamp = self._stamp(file_path)  # 先记再读：读的途中被改了，记下的是旧的，写时会要求重读
        result = super().read(file_path, offset, limit)
        if result.error is None and stamp is not None:
            self._remember(file_path, stamp)
        return result

    def write(self, file_path: str, content: str) -> WriteResult:
        if self._unread(file_path):
            return WriteResult(error=READ_FIRST)
        result = super().write(file_path, content)
        if result.error is None and (stamp := self._stamp(file_path)) is not None:
            self._remember(file_path, stamp, wrote=True)
        return result

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        if self._unread(file_path):
            return EditResult(error=READ_FIRST)
        result = super().edit(file_path, old_string, new_string, replace_all)
        if result.error is None and (stamp := self._stamp(file_path)) is not None:
            self._remember(file_path, stamp, wrote=True)
        return result

    def forget(self, session_dir: Path) -> None:
        """删除会话时清掉它的读写记录。"""
        root = session_dir.resolve()
        with self._seen_lock:
            for key in [key for key in self._seen if root in key[1].parents]:
                del self._seen[key]

    def _stamp(self, file_path: str) -> tuple[int, int] | None:
        """文件现在的（修改时间 ns，大小）；不存在、越界或读不了时为 None。"""
        try:
            stat = self._resolve_path(file_path).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _remember(self, file_path: str, stamp: tuple[int, int], *, wrote: bool = False) -> None:
        """记下这个调用方读到（或写成）的版本；写、改成功时别的调用方的记录作废。"""
        path = self._resolve_path(file_path)
        caller = self._caller()
        with self._seen_lock:
            if wrote:
                for key in [key for key in self._seen if key[1] == path and key[0] != caller]:
                    del self._seen[key]
            self._seen[(caller, path)] = stamp

    def _unread(self, file_path: str) -> bool:
        """要改的是已有文件，而且没读过或读后被改过。"""
        stamp = self._stamp(file_path)
        if stamp is None:
            return False  # 新建文件（或越界：交给父类报越界的错误）
        key = (self._caller(), self._resolve_path(file_path))
        with self._seen_lock:
            return self._seen.get(key) != stamp

    def _scoped(self, path: str | None) -> str:
        """不指定路径（或指定根目录）的搜索默认限定在本会话目录。"""
        return f"/workspace/{self._session()}/" if path in (None, "", "/", ".") else path

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        return super().glob(pattern, self._scoped(path))

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
        context_lines: int = 0,
    ) -> GrepResult:
        return super().grep(
            pattern, self._scoped(path), glob, max_count=max_count, context_lines=context_lines
        )

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
        context_lines: int = 0,
    ) -> GrepResult:
        return await super().agrep(
            pattern, self._scoped(path), glob, max_count=max_count, context_lines=context_lines
        )

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        raise NotImplementedError("工作区只支持异步执行命令")

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109 - deepagents 协议的参数名，转交给沙箱
    ) -> ExecuteResponse:
        result = await self._sandbox.run(self._session(), command, time_limit=timeout)
        if (results := COMMAND_RESULTS.get()) is not None:  # 交给界面的退出码与错误输出
            results.append(result)
        return ExecuteResponse(
            output=result.output, exit_code=result.exit_code, truncated=result.truncated
        )


async def _read_chunks(handle: BinaryIO) -> AsyncIterator[bytes]:
    try:
        while chunk := await asyncio.to_thread(handle.read, _CHUNK):
            yield chunk
    finally:
        handle.close()


def _safe_name(name: str) -> str:
    """只留文件名本身：去掉目录部分（/ 与 \\ 都算）、控制字符和开头的点（不生成隐藏文件）；
    过长的保留开头与后缀。"""
    base = _UNSAFE_NAME.sub("", name.replace("\\", "/").rsplit("/", 1)[-1]).strip().lstrip(".")
    base = base or "未命名文件"
    if len(base.encode()) <= _MAX_NAME_BYTES:
        return base
    suffix = Path(base).suffix if len(Path(base).suffix.encode()) <= 20 else ""
    stem = base.removesuffix(suffix).encode()[: _MAX_NAME_BYTES - len(suffix.encode())]
    return stem.decode(errors="ignore") + suffix  # 截断处不完整的汉字丢掉


def _make_shared_dirs(*directories: Path) -> None:
    """依次建好目录，已存在的跳过（不先判断是否存在：同时上传的几个文件会同时来建）。

    新建的目录放开权限：backend 在容器里是 root、执行命令用 uid 1000，在区分 uid 的文件系统上
    命令也要能在里面写文件（mkdir 的权限受 umask 影响，所以单独设置）。
    """
    for directory in directories:
        try:
            directory.mkdir(parents=True)
        except FileExistsError:
            continue
        directory.chmod(0o777)


def _reserve(directory: Path, name: str) -> tuple[Path, BinaryIO]:
    """以独占方式新建文件（同名已存在时加序号），返回位置与打开的文件。"""
    stem, suffix = Path(name).stem, Path(name).suffix
    for number in itertools.count(1):
        candidate = directory / (name if number == 1 else f"{stem} ({number}){suffix}")
        try:
            return candidate, candidate.open("xb")
        except FileExistsError:
            continue
    raise AssertionError("unreachable")
