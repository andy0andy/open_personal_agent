"""MCP 客户端接口（设计文档 4.2 的 mcp_client 替换点）：连接 MCP 服务、取出工具。

接口只给出工具本身与它的来历（哪个服务、是否声明只读），连接方式等细节留在实现里。
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from config import McpServerConfig

# 服务断开（或正在重连）时调用工具得到的提示，作为出错的结果（设计 2026-10-23 5.8）。
# 运行层据此认出这是系统自己的提示、不是外部资料（5.9）
MCP_DISCONNECTED = "服务 {server} 暂时断开，正在重连；这次不要再调用它的工具"

# reconnecting：连上过、断开了，正在重连（设计 2026-10-23 5.8）
type McpServerState = Literal["disabled", "connecting", "connected", "reconnecting", "failed"]


@dataclass(frozen=True)
class McpTool:
    server: str  # 所属服务名
    name: str  # 带服务名前缀的工具名，如 files_write_file
    description: str
    read_only: bool | None  # 服务声明的"只读"（readOnlyHint）；没有声明时为 None
    tool: BaseTool


class McpServerStatus(BaseModel):
    """一个服务的连接状态，设置页显示。error 是给用户看的一句中文。"""

    name: str
    description: str
    transport: str
    state: McpServerState
    error: str | None = None
    tools: list[str] = []


class McpProbeResult(BaseModel):
    """测试连接的结果（管理页面的"测试连接"）：连上时列出工具名，失败时给一句中文原因。"""

    ok: bool
    tools: list[str] = []
    error: str | None = None


class McpClient(Protocol):
    async def connect(self, servers: Sequence[McpServerConfig]) -> None:
        """先关掉现有连接，再并行连接这些服务；每个服务都连上、失败或超时后才返回。"""
        ...

    def tools(self) -> list[McpTool]:
        """已连接（含正在重连）服务的工具，按服务在清单里的顺序。"""
        ...

    def on_tools_changed(self, callback: Callable[[], None]) -> None:
        """登记一个回调：connect 之外工具清单变了时调用（断线重连后工具不同了、服务没连上了）。"""
        ...

    def statuses(self) -> list[McpServerStatus]:
        """与清单同序；没有连接过时为空。"""
        ...

    async def probe(self, server: McpServerConfig) -> McpProbeResult:
        """单独连一次这个服务、列出工具后断开；不动现有的连接。"""
        ...

    async def close(self) -> None: ...
