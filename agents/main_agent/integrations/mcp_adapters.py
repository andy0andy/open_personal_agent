"""McpClient 的 langchain-mcp-adapters 实现。

这个库默认每调用一次工具就新起一个服务进程（又慢，又会丢掉服务的状态），所以每个服务
放一个专属任务长期保持一个会话：会话必须在同一个任务里进入和退出（anyio 的限制），
其他任务里的工具调用经这个会话发出（先行探测：并发调用、取消一次调用都不影响会话）。

断线重连（设计 2026-10-23 5.8）：
- 连着时每 30 秒 ping 一次；ping 不通、会话出错、调用时发现断开都算断开：状态改成"重连中"，
  按 1、2、4、8、16 秒的间隔重试 5 次，还不行就是"没有连上"，之后每 5 分钟再试一次
  （一开始就没连上的也一样每 5 分钟再试）。
- 交给智能体的是稳定的工具：名字、说明、参数取自最近一次连上时，调用经拦截器转给当前的会话；
  断开时直接返回一句中文提示（作为出错的结果，运行不失败）。重连后工具不同了、或没连上而不再
  交出工具时，通知使用方（MainAgent 清掉组装好的智能体）。
"""

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest, MCPToolCallResult
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, CallToolResult, TextContent

from agents.main_agent.integrations.mcp import (
    MCP_DISCONNECTED,
    McpProbeResult,
    McpServerState,
    McpServerStatus,
    McpTool,
)
from common.redact import redact
from config import McpServerConfig, blanked_hint

logger = logging.getLogger(__name__)

_STOP_TIMEOUT = 5.0  # 关闭一个服务最多等几秒，之后直接取消它的任务
_REASON_LIMIT = 200


@dataclass(frozen=True)
class ReconnectTiming:
    """断线重连的时间（秒）；测试里调小。"""

    ping_interval: float = 30.0
    ping_timeout: float = 10.0
    retry_delays: tuple[float, ...] = (1, 2, 4, 8, 16)  # 断开后的快速重试
    retry_later: float = 300.0  # 没连上以后隔多久再试
    # 连上后至少稳定这么久，断开时才重新给一组快速重试（积压小问题 E3：刚连上就断的服务
    # 原来会一直被重启）
    stable_after: float = 60.0


# mcp 库等不到回应时报的错误码（它用的是 HTTP 的 408，见 mcp/shared/session.py）
_REQUEST_TIMEOUT = 408


class McpAdaptersClient:
    def __init__(self, timing: ReconnectTiming | None = None) -> None:
        self._timing = timing or ReconnectTiming()
        self._connections: list[_Connection] = []
        self._on_tools_changed: Callable[[], None] | None = None
        self._signature: list[tuple[str, str, bool | None, str]] = []  # 上次交出的工具

    async def connect(self, servers: Sequence[McpServerConfig]) -> None:
        await self.close()
        self._connections = [
            _Connection(server, self._timing, self._tools_maybe_changed) for server in servers
        ]
        await asyncio.gather(*(connection.start() for connection in self._connections))
        self._signature = _signature(self.tools())

    def tools(self) -> list[McpTool]:
        return [tool for connection in self._connections for tool in connection.tools]

    def on_tools_changed(self, callback: Callable[[], None]) -> None:
        self._on_tools_changed = callback

    def statuses(self) -> list[McpServerStatus]:
        return [connection.status() for connection in self._connections]

    async def probe(self, server: McpServerConfig) -> McpProbeResult:
        connection = _Connection(server, self._timing, lambda: None)
        await connection.start()
        try:
            return McpProbeResult(
                ok=connection.state == "connected",
                tools=[tool.name for tool in connection.tools],
                error=connection.error,
            )
        finally:
            await connection.stop()

    async def close(self) -> None:
        connections, self._connections = self._connections, []
        await asyncio.gather(*(connection.stop() for connection in connections))
        self._signature = []

    def _tools_maybe_changed(self) -> None:
        signature = _signature(self.tools())
        if signature != self._signature:
            self._signature = signature
            if self._on_tools_changed is not None:
                self._on_tools_changed()


class _Connection:
    """一个服务的长期会话，断开后自己重连。"""

    def __init__(
        self, config: McpServerConfig, timing: ReconnectTiming, changed: Callable[[], None]
    ) -> None:
        self.config = config
        self.state: McpServerState = "connecting"
        self.error: str | None = None
        self._timing = timing
        self._changed = changed  # 交出的工具可能变了（状态变了、重连后工具不同了）
        self._tools: list[McpTool] = []  # 最近一次连上时的工具：调用转给当前的会话
        self._session: ClientSession | None = None
        self._calls: set[asyncio.Task[CallToolResult]] = set()  # 正在经当前会话进行的调用
        self._settled = asyncio.Event()  # 第一次连上或失败
        self._stopping = asyncio.Event()
        self._wake = asyncio.Event()  # 要停了，或调用时发现断开：叫醒守着会话的任务
        self._task: asyncio.Task[None] | None = None
        self._connected_at = 0.0  # 最近一次连上的时间（time.monotonic）

    @property
    def tools(self) -> list[McpTool]:
        """连着或正在重连时交出的工具；没连上时不交（智能体不会再去调用）。"""
        return self._tools if self.state in ("connected", "reconnecting") else []

    def status(self) -> McpServerStatus:
        return McpServerStatus(
            name=self.config.name,
            description=self.config.description,
            transport=self.config.transport,
            state=self.state,
            error=self.error,
            tools=[tool.name for tool in self.tools],
        )

    async def start(self) -> None:
        config = self.config
        if not config.enabled:
            self.state = "disabled"
            return
        if config.missing_env:
            names = "、".join(config.missing_env)
            hint = blanked_hint(config.missing_env, os.environ)
            self._fail(f"缺少环境变量 {names}：在 .env 里设置后执行 make restart{hint}")
            return
        self._task = asyncio.create_task(self._hold(), name=f"mcp:{config.name}")
        try:
            # 每次连接自己有超时（_attempt）；这里多等一会儿只是兜底
            async with asyncio.timeout(config.connect_timeout + _STOP_TIMEOUT):
                await self._settled.wait()
        except TimeoutError:
            # 先记成没连上；守着它的任务不停，之后照常隔一段时间再试（积压小问题：原来直接
            # stop，这个服务再也不试）
            logger.warning("MCP 服务 %s 连接超时", config.name)
            self._fail(f"连接超时（{config.connect_timeout:g} 秒）")

    async def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        task, self._task = self._task, None
        if task is None or task.done():
            return
        try:
            async with asyncio.timeout(_STOP_TIMEOUT):
                await asyncio.shield(task)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _hold(self) -> None:
        name = self.config.name
        retries: Iterator[float] = iter(())  # 断开后还剩的快速重试间隔
        fresh = True  # 启动或上次稳定连上以来还没用过一组快速重试
        while True:
            connected, reason = await self._attempt()
            if self._stopping.is_set():
                return
            if connected:
                logger.warning("MCP 服务 %s 断开（%s），开始重连", name, reason)
                self._set_state("reconnecting")
                if time.monotonic() - self._connected_at >= self._timing.stable_after:
                    fresh = True
                if fresh:  # 刚连上就断的不重设：接着用剩下的，用完就记成没连上（E3）
                    retries = iter(self._timing.retry_delays)
                    fresh = False
            delay = next(retries, None)
            if delay is None:
                if self.state != "failed":
                    logger.warning("MCP 服务 %s 没有连上：%s", name, reason)
                self._fail(reason)
                delay = self._timing.retry_later
            if await self._stopped_within(delay):
                return

    async def _attempt(self) -> tuple[bool, str]:
        """连一次；连上后守着会话，直到要停或断开。返回（这次连上过没有，断开或没连上的原因）。"""
        name = self.config.name
        client = MultiServerMCPClient({name: _connection(self.config)})  # type: ignore[dict-item]
        connected = False
        try:
            async with contextlib.AsyncExitStack() as stack:
                async with asyncio.timeout(self.config.connect_timeout):
                    session = await stack.enter_async_context(client.session(name))
                    tools = await load_mcp_tools(
                        session,
                        server_name=name,
                        tool_name_prefix=True,
                        tool_interceptors=[self._forward],
                    )
                connected = True
                self._adopt(tools, session)
                return True, await self._watch(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 后台任务边界：任何连接失败都记成原因（anyio 会把错误包成异常组）
            logger.info("MCP 服务 %s 的会话出错", name, exc_info=True)
            # 先拆开异常组再看：取工具清单时超时，anyio 的任务组会把它包一层（积压小问题 E6）
            if isinstance(_first_error(exc), TimeoutError) and not connected:
                return False, f"连接超时（{self.config.connect_timeout:g} 秒）"
            return connected, _reason(exc, self.config)
        finally:
            self._session = None
            for call in self._calls:  # 还在等这个会话回应的调用：会话没了，直接告诉它断开了
                call.cancel()

    def _adopt(self, loaded: list[BaseTool], session: ClientSession) -> None:
        tools = [
            McpTool(
                server=self.config.name,
                name=tool.name,
                description=tool.description,
                read_only=_read_only(tool.metadata),
                tool=tool,
            )
            for tool in loaded
        ]
        if _signature(tools) != _signature(self._tools):
            self._tools = tools  # 工具没变时留着原来那份：组装好的智能体手里的照常能用
        self._session = session
        self.error = None
        self._connected_at = time.monotonic()
        self._set_state("connected")
        self._settled.set()

    async def _watch(self, session: ClientSession) -> str:
        """守着连上的会话，隔一段时间 ping 一次。要停时返回空串；断开时返回原因。"""
        while True:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self._timing.ping_interval):
                    await self._wake.wait()
            if self._stopping.is_set():
                return ""
            if self._wake.is_set():
                self._wake.clear()
                return "调用时发现连接断开"
            if self._calls:  # 有调用在进行：一次只处理一个请求的服务这时答不上 ping，不算断开
                continue
            if not await self._alive(session):
                return "ping 不通"

    async def _alive(self, session: ClientSession) -> bool:
        try:
            async with asyncio.timeout(self._timing.ping_timeout):
                await session.send_ping()
        except asyncio.CancelledError:
            raise
        except Exception:  # ping 失败的原因各式各样（流已关闭、超时……），都说明会话不能用了
            logger.info("MCP 服务 %s ping 不通", self.config.name, exc_info=True)
            return False
        return True

    async def _forward(
        self,
        request: MCPToolCallRequest,
        handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
    ) -> MCPToolCallResult:
        """工具调用转给当前的会话（不用 handler：它绑着连上那时的会话）；断开时返回一句提示。"""
        session = self._session
        if session is None or self.state != "connected":
            return self._disconnected()
        call = asyncio.create_task(session.call_tool(request.name, request.args))
        self._calls.add(call)
        try:
            await asyncio.wait({call})
        finally:
            self._calls.discard(call)
            call.cancel()  # 外面取消了这次调用（如停止运行）：会话里的这次请求也不再等
        if call.cancelled():  # 会话断开时被取消
            return self._disconnected()
        exc = call.exception()
        if exc is None:
            return call.result()
        # 连接已关闭；或别的意外错误、且 ping 也不通：都算断开。工具自己报的错、超时照常抛出
        closed = isinstance(exc, McpError) and exc.error.code == CONNECTION_CLOSED
        if closed or (not isinstance(exc, McpError) and not await self._alive(session)):
            self._broken(session)
            return self._disconnected()
        if isinstance(exc, McpError) and exc.error.code == _REQUEST_TIMEOUT:
            # mcp 库的超时是英文的一句：换成我们自己的中文说法（积压小问题 E8）；
            # 服务自己报的错属于外部资料，原样交出去
            raise TimeoutError(f"调用超时（{self.config.call_timeout:g} 秒）") from exc
        raise exc

    def _broken(self, session: ClientSession) -> None:
        """调用时发现断开：马上标成重连中（后面的调用直接拿到提示），叫醒守着会话的任务去重连。"""
        if self._session is session and self.state == "connected":
            self._set_state("reconnecting")
            self._wake.set()

    def _disconnected(self) -> CallToolResult:
        text = MCP_DISCONNECTED.format(server=self.config.name)
        return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)

    async def _stopped_within(self, seconds: float) -> bool:
        """等一段时间；其间要停了就提前返回 True。"""
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(seconds):
                await self._stopping.wait()
        return self._stopping.is_set()

    def _set_state(self, state: McpServerState) -> None:
        self.state = state
        self._changed()

    def _fail(self, reason: str) -> None:
        self.error = reason
        self._set_state("failed")
        self._settled.set()


def _connection(config: McpServerConfig) -> dict[str, Any]:
    session_kwargs = {"read_timeout_seconds": timedelta(seconds=config.call_timeout)}
    if config.transport == "stdio":
        # mcp 只把 PATH、HOME 等少数变量带给子进程；npm 的缓存目录要转过去，
        # 下载过的服务包才会留在数据卷里（重建容器后不用重新下载）
        inherited = {k: v for k, v in os.environ.items() if k.lower().startswith("npm_config_")}
        return {
            "transport": "stdio",
            "command": config.command,
            "args": config.args,
            "env": {**inherited, **config.env},
            "session_kwargs": session_kwargs,
        }
    return {
        "transport": config.transport,
        "url": config.url,
        "headers": config.headers,
        "session_kwargs": session_kwargs,
    }


def _signature(tools: Sequence[McpTool]) -> list[tuple[str, str, bool | None, str]]:
    """工具清单的指纹：名字、说明、只读声明、参数（重连后据此判断工具变了没有）。"""
    return [
        (
            tool.name,
            tool.description,
            tool.read_only,
            json.dumps(tool.tool.args_schema, sort_keys=True, ensure_ascii=False, default=str),
        )
        for tool in tools
    ]


def _read_only(metadata: dict[str, Any] | None) -> bool | None:
    value = (metadata or {}).get("readOnlyHint")
    return value if isinstance(value, bool) else None


def _first_error(exc: BaseException) -> BaseException:
    """异常组里第一个真正的错误（anyio 会把错误包成异常组）。"""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _reason(exc: Exception, config: McpServerConfig) -> str:
    """给用户看的失败原因：取异常组里第一个真正的错误；打码，MCP 页上不露出密钥
    （积压小问题 E5）。"""
    first = _first_error(exc)
    if isinstance(first, FileNotFoundError):
        return f"找不到命令 {config.command}"
    first_line = (str(first).strip().splitlines() or [type(first).__name__])[0]
    return f"连接失败：{redact(first_line)[:_REASON_LIMIT]}"  # 先打码再截断
