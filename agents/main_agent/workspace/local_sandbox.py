"""执行命令的实现：在智能体所在的环境里执行（D20，取代沙箱容器）。

- 在会话目录 <工作区>/<会话短 ID>/ 下用 bash 执行，单独成一个进程组；超时、或这次执行被取消
  （运行被停止）时杀掉整个进程组，命令派生的子进程一并结束；脱离了进程组的按记下的后代与
  环境里的随机标记补杀（reaper.py，设计 2026-10-23 5.5）；
- 标准输出、标准错误分开读，按到达先后拼成给智能体的输出，标准错误另存一份给界面；
  输出超过上限时留开头 40% 与结尾 60%，完整内容写进会话目录的 logs/，并告诉智能体去哪里读；
- 只传白名单里的环境变量（不传网关密钥、数据库地址等），HOME 指向单独的目录；
- 智能体以 root 运行时（后端容器里就是）改用 uid 1000 执行，并加上进程数限制；
  同时用 Landlock 只放行写本会话目录、命令自己的缓存目录、/tmp、/dev（设计 2026-10-23 5.1）：
  .workdata 里的配置、技能、别的会话都写不了（读不受限）；内核或容器不支持时不加，只提示一次；
- 与智能体共用同一个 Python 环境（用户选定）：PATH 最前面是智能体自己的 Python 所在目录；
- 智能体看到的路径是 /workspace/<会话短 ID>/…，输出里的真实路径换回这个写法。
"""

import asyncio
import codecs
import contextlib
import logging
import os
import re
import signal
import sys
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from agents.main_agent.workspace.base import CommandResult
from agents.main_agent.workspace.reaper import (
    BARE_ENV,
    MARK_VARIABLE,
    PROC,
    descendants,
    marked_pids,
    still_alive,
)

logger = logging.getLogger(__name__)

_SESSION = re.compile(r"c_[0-9a-f]{8}")
_VIRTUAL_ROOT = "/workspace"
_LOG_LIMIT = 20 * 1024 * 1024  # 日志文件最多记录 20MB，防止失控的输出写满磁盘
# 命令结束后最多再等几秒把输出读完：脱离了进程组的后台进程（杀不到）可能一直占着输出
_DRAIN_SECONDS = 2
_REAP_GRACE_SECONDS = 0.5  # 补杀后再等多久看输出放开没有
_POLL_SECONDS = 0.1
_RECORD_EVERY = 5  # 每轮询这么多次记一次后代进程（约 0.5 秒）
_EXEC_UID = 1000  # 智能体以 root 运行时，命令改用这个普通用户执行
_STDERR_LIMIT = 8000  # 另存的标准错误最多留最后这么多字
_TIMED_OUT = 124  # 超时的退出码（同 GNU timeout）
_UNKNOWN_EXIT = -1  # 杀掉后没等到退出
# 只在改用普通用户时生效。进程数按用户计、线程也算，所有会话的命令一起算（按会话限要用 cgroup）：
# 256 起几百个线程的 Python 就不够（积压小问题 D13，2026-10-26 提到 1024）
_MAX_PROCESSES = 1024
# 传给命令的环境变量：其余（密钥、数据库地址等）一律不传
_PASSED_ENV = ("LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "MATPLOTLIBRC")


# Landlock 里写类的权限（setpriv 的写法）：只限制这些，读与执行不受限。refer（跨目录改名、
# 硬链接）Landlock 默认一律拒绝，要显式放行，否则放行目录之间 os.rename 也会失败
WRITE_RIGHTS = (
    "write-file,remove-dir,remove-file,make-char,make-dir,make-reg,"
    "make-sock,make-fifo,make-block,make-sym,refer,truncate"
)


def landlock_args(writable: Sequence[Path]) -> list[str]:
    """setpriv 的 Landlock 参数：限制写类权限，只在 writable 这些目录下放行。"""
    args = ["--landlock-access", f"fs:{WRITE_RIGHTS}"]
    for path in writable:
        args += ["--landlock-rule", f"path-beneath:{WRITE_RIGHTS}:{path}"]
    return args


def _as_user(identity: tuple[int, int] | None, writable: Sequence[Path] = ()) -> list[str]:
    """换用户执行的命令前缀：用 setpriv（util-linux）切换并清掉 root 的附加用户组；
    给了 writable 时再加上 Landlock 写入限制。

    不用 create_subprocess_exec 的 user / group / extra_groups 参数：后端跑在 uvicorn 默认的
    uvloop 事件循环上，它不认这几个参数，每条命令都会失败（实际出过错）。
    """
    if identity is None:
        return []
    uid, gid = identity
    prefix = ["setpriv", f"--reuid={uid}", f"--regid={gid}", "--clear-groups"]
    return prefix + landlock_args(writable) if writable else prefix


def exec_identity(*, euid: int) -> tuple[int, int] | None:
    """执行命令用的用户与组：智能体是 root 时换成普通用户，否则沿用当前用户（None）。"""
    return (_EXEC_UID, _EXEC_UID) if euid == 0 else None


class LocalSandbox:
    def __init__(
        self,
        workspace_dir: Path,
        *,
        default_timeout: int = 120,
        max_timeout: int = 600,
        max_output: int = 30000,
        max_file_mb: int = 1024,
        landlock: bool | None = None,
    ) -> None:
        """landlock：None 时第一次以普通用户执行前探测一次内核与容器是否支持。"""
        self._workspace = workspace_dir.resolve()
        # 输出里的真实路径换回 /workspace：只换工作区本身，同前缀的 workspace-old、workspace2
        # 不动（积压小问题 D10）
        self._real_root = re.compile(re.escape(str(self._workspace)) + r"(?![\w.-])")
        self._real_root_bytes = re.compile(
            re.escape(str(self._workspace).encode()) + rb"(?![\w.-])"
        )
        self._home = self._workspace.parent / "cache" / "exec-home"
        self._landlock = landlock
        self._default_timeout = default_timeout
        self._max_timeout = max_timeout
        self._max_output = max_output
        self._max_file_kb = max_file_mb * 1024

    async def run(self, session: str, command: str, *, time_limit: int | None) -> CommandResult:
        if not _SESSION.fullmatch(session):
            raise PermissionError(f"会话短 ID 格式不正确：{session}")
        limit = time_limit or self._default_timeout
        if not 0 < limit <= self._max_timeout:
            return CommandResult(
                output=f"执行被拒绝：超时时间须在 1～{self._max_timeout} 秒之间", exit_code=2
            )
        cwd = self._workspace / session
        await asyncio.to_thread(_make_open_dirs, cwd, self._home)
        identity = exec_identity(euid=os.geteuid())
        writable: list[Path] = []
        if identity is not None:
            if self._landlock is None:
                self._landlock = await self._probe_landlock(identity)
            if self._landlock:
                writable = [cwd, self._home, Path("/tmp"), Path("/dev")]
        mark = uuid.uuid4().hex  # 认出脱离了进程组的后代（reaper.py）
        process = await asyncio.create_subprocess_exec(
            *_as_user(identity, writable),
            "bash",
            "-c",
            self._limits(identity) + command,
            cwd=cwd,
            env={**self._environment(), MARK_VARIABLE: mark},
            # 标准输入给空的：不继承后端的，读标准输入的命令不会卡到超时（积压小问题 D11）
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # 单独成一个进程组，结束时连同子进程一起杀掉
        )
        collector = _Collector(cwd, self._max_output, virtual=self._to_virtual_bytes)
        assert process.stdout is not None
        assert process.stderr is not None
        reading = asyncio.gather(
            collector.drain(process.stdout), collector.drain(process.stderr, errors=True)
        )
        timed_out = held = stopped = ended = False
        recorded: dict[int, int] = {}  # 记下的后代进程：进程号 → 启动时间
        # 看 bash 本身有没有退出，而不是 process.wait()：后者要等输出管道也关上才返回，
        # 脱离了进程组的后台进程一直占着管道时会一直等下去
        deadline = time.monotonic() + limit
        try:
            polls = 0
            while process.returncode is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                if polls % _RECORD_EVERY == 0 and PROC.exists():
                    recorded.update(await asyncio.to_thread(descendants, process.pid))
                polls += 1
                await asyncio.sleep(_POLL_SECONDS)
        except asyncio.CancelledError:
            stopped = True
            raise
        finally:  # 正常结束、超时、被取消（运行停止）都走这里：同组留在后台的进程一并结束
            held, ended = await _clean_up(
                process, reading, recorded, mark, identity, ended_early=stopped or timed_out
            )
        output = self._to_virtual(collector.text())
        if timed_out:
            output += f"\n[命令超过 {limit} 秒，已终止]"
        if ended:
            output += "\n[仍有后台进程脱离了进程组、占着输出，已结束]"
        elif held:  # 补杀找不到它们（没有 /proc、清空了环境变量的）
            output += "\n[仍有后台进程脱离了进程组、占着输出，已不再等它（这类进程不会被自动结束）]"
        return CommandResult(
            output=output,
            exit_code=exit_code_of(process.returncode, timed_out=timed_out),
            truncated=collector.truncated,
            timed_out=timed_out,
            stderr=self._to_virtual(collector.stderr()),
        )

    async def _probe_landlock(self, identity: tuple[int, int]) -> bool:
        """内核与容器支不支持 Landlock：不支持时 setpriv 带上这些参数会直接失败，
        每条命令都跑不了。"""
        try:
            probe = await asyncio.create_subprocess_exec(
                *_as_user(identity, [Path("/tmp")]),
                "true",
                env=BARE_ENV,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            supported = await probe.wait() == 0
        except OSError:
            supported = False
        if not supported:
            logger.warning("Landlock 用不了：命令照常执行，但能写 .workdata 里的配置（见 D25）")
        return supported

    def _limits(self, identity: tuple[int, int] | None) -> str:
        """单个文件大小（KB）与进程数的上限；改不了时（如 macOS 不支持某项）忽略。"""
        limits = f"ulimit -f {self._max_file_kb} 2>/dev/null; "
        if identity is not None:
            limits += f"ulimit -u {_MAX_PROCESSES} 2>/dev/null; "
        return limits

    def _environment(self) -> dict[str, str]:
        env = {name: os.environ[name] for name in _PASSED_ENV if name in os.environ}
        python_dir = str(Path(sys.executable).parent)
        env["PATH"] = f"{python_dir}:/usr/local/bin:/usr/bin:/bin"
        env["HOME"] = str(self._home)
        env["MPLBACKEND"] = "Agg"  # 只画到文件，不开窗口
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _to_virtual(self, text: str) -> str:
        return self._real_root.sub(_VIRTUAL_ROOT, text)

    def _to_virtual_bytes(self, data: bytes) -> bytes:
        """写进 logs/ 的原始字节同样换路径（正好被切在两块之间的路径偶尔漏换，可以接受）。"""
        return self._real_root_bytes.sub(_VIRTUAL_ROOT.encode(), data)


def _make_open_dirs(*directories: Path) -> None:
    """建好目录并放开权限：命令可能以 uid 1000 执行，而目录由 root 建（同 local.py）。"""
    for directory in directories:
        try:
            directory.mkdir(parents=True)
        except FileExistsError:
            continue
        directory.chmod(0o777)


async def _wait_exit(process: asyncio.subprocess.Process) -> None:
    """杀掉进程组后等 bash 退出（最多 _DRAIN_SECONDS 秒）。"""
    deadline = time.monotonic() + _DRAIN_SECONDS
    # 只能轮询 returncode：能等事件的 process.wait() 要等输出管道关上
    while process.returncode is None and time.monotonic() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(_POLL_SECONDS)


def exit_code_of(returncode: int | None, *, timed_out: bool) -> int:
    """交给智能体与界面的退出码：超时 124；杀掉后没等到退出 -1；其余原样（设计 2026-10-23 5.4）。"""
    if timed_out:
        return _TIMED_OUT
    return _UNKNOWN_EXIT if returncode is None else returncode


async def _drained(reading: asyncio.Future[Any], seconds: float) -> bool:
    """最多等 seconds 秒让输出读完，返回读完了没有。"""
    await asyncio.wait({reading}, timeout=seconds)
    return reading.done()


def _give_up(reading: asyncio.Future[Any]) -> None:
    """不再等输出：取消读取。取消后的结果没人取，不取的话回收时打一条
    "exception was never retrieved"（积压小问题 D14）。"""
    reading.cancel()
    reading.add_done_callback(lambda done: done.cancelled() or done.exception())


async def _reap(recorded: dict[int, int], mark: str, identity: tuple[int, int] | None) -> None:
    """补杀脱离了进程组的后代：记下的还活着的，加上环境里带着标记的；只杀执行命令那个用户的。"""
    uid = identity[0] if identity is not None else os.getuid()
    pids = set(await asyncio.to_thread(still_alive, recorded, uid=uid))
    with contextlib.suppress(OSError):  # 扫描失败只是少补杀一些
        pids |= set(await marked_pids(mark, _as_user(identity)))
    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)


async def _clean_up(
    process: asyncio.subprocess.Process,
    reading: asyncio.Future[Any],
    recorded: dict[int, int],
    mark: str,
    identity: tuple[int, int] | None,
    *,
    ended_early: bool,
) -> tuple[bool, bool]:
    """结束同组留在后台的进程，等 bash 退出、输出读完；返回（还有进程占着输出，占着输出的已被
    补杀）。超时、被停（ended_early）时一律补杀；正常结束时只在它们还占着输出时才补杀
    （积压小问题 D14，用户 2026-10-26 决定；脱离进程组、输出又重定向走的不占着输出，照旧留着）。"""
    _kill_group(process.pid)
    if ended_early and PROC.exists():
        await _reap(recorded, mark, identity)
    await _wait_exit(process)
    try:
        if await _drained(reading, _DRAIN_SECONDS):
            return False, False
        if ended_early or not PROC.exists():
            return True, False
        await _reap(recorded, mark, identity)
        # 补杀后输出放开了才算"已结束"：补杀找不到的（如清空了环境变量的）照旧说不会被结束
        if await _drained(reading, _REAP_GRACE_SECONDS):
            return True, True
        return True, False
    finally:
        if not reading.done():
            _give_up(reading)


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):  # 进程组可能已全部结束
        os.killpg(pid, signal.SIGKILL)


class _Collector:
    """收集一条命令的输出：标准输出、标准错误按到达先后拼在一起；超过上限后完整内容写进 logs/，
    给智能体的只留开头 40% 与结尾 60%。字数按增量算（不再每来一块就把全部重新拼一遍，R26）。"""

    def __init__(self, cwd: Path, limit: int, *, virtual: Callable[[bytes], bytes]) -> None:
        self._cwd = cwd
        self._limit = limit
        self._virtual = virtual  # 写进日志前把真实路径换回 /workspace（积压小问题 D12）
        self._head_limit = limit * 2 // 5
        self._tail_limit = limit - self._head_limit
        self._parts: list[str] = []  # 还没超限时的全部内容
        self._raw: list[bytes] = []  # 同上的原始字节（超限时写进日志）
        self._size = 0  # 收到的总字数
        self._head = ""  # 超限后：开头
        self._tail: deque[str] = deque()  # 超限后：结尾（字数略多于 _tail_limit）
        self._tail_size = 0
        self._stderr: deque[str] = deque()
        self._log: Path | None = None
        self._logged = 0
        self._log_full = False  # 日志写满上限、后面没再记
        # 两路输出各有一个读取任务；建日志、追加日志要切到线程里等，期间另一路不能插进来（审查 I4）
        self._lock = asyncio.Lock()

    @property
    def truncated(self) -> bool:
        return self._log is not None

    async def drain(self, stream: asyncio.StreamReader, *, errors: bool = False) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := await stream.read(65536):
            await self._add(chunk, decoder.decode(chunk), errors=errors)
        if rest := decoder.decode(b"", final=True):
            await self._add(b"", rest, errors=errors)

    async def _add(self, raw: bytes, text: str, *, errors: bool) -> None:
        async with self._lock:
            if errors:
                _keep_last(self._stderr, text, _STDERR_LIMIT)
            self._size += len(text)
            if self._log is None:
                self._parts.append(text)
                self._raw.append(raw)
                if self._size > self._limit:
                    await asyncio.to_thread(self._start_log)
                return
            _keep_last(self._tail, text, self._tail_limit)
            if self._logged < _LOG_LIMIT:
                await asyncio.to_thread(self._append, raw)
            elif raw:
                self._log_full = True

    def _start_log(self) -> None:
        logs = self._cwd / "logs"
        _make_open_dirs(logs)
        self._log = logs / f"exec-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{id(self)}.log"
        data = self._virtual(b"".join(self._raw))
        self._log.write_bytes(data)
        self._logged = len(data)
        text = "".join(self._parts)
        self._head = text[: self._head_limit]
        self._tail = deque([text[self._head_limit :]])
        _keep_last(self._tail, "", self._tail_limit)
        self._parts, self._raw = [], []

    def _append(self, chunk: bytes) -> None:
        assert self._log is not None
        data = self._virtual(chunk)
        with self._log.open("ab") as file:
            file.write(data)
        self._logged += len(data)

    def text(self) -> str:
        if self._log is None:
            return "".join(self._parts)
        tail = "".join(self._tail)[-self._tail_limit :]
        omitted = self._size - len(self._head) - len(tail)
        if self._log_full:  # 日志也没记全：不能再说"完整输出"（积压小问题 D12）
            where = f"logs/{self._log.name} 只记了前 {_LOG_LIMIT // 1024 // 1024}MB"
        else:
            where = f"完整输出在 logs/{self._log.name}"
        note = f"（中间省略了 {omitted} 字，{where}）"
        return f"{self._head}\n{note}\n{tail}"

    def stderr(self) -> str:
        return "".join(self._stderr)[-_STDERR_LIMIT:]


def _keep_last(parts: deque[str], text: str, limit: int) -> None:
    """往结尾追加一段，再从开头丢掉整段，直到去掉第一段后仍不少于 limit 字为止。"""
    if text:
        parts.append(text)
    total = sum(len(part) for part in parts)
    while parts and total - len(parts[0]) >= limit:
        total -= len(parts.popleft())
