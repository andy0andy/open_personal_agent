"""测试用 MCP 服务（标准输入输出方式）：只读、有副作用、出错、卡住各一个工具。

契约测试与真实模型验证用 `sys.executable` 启动它，不需要 Node。断线重连的测试用这些环境变量
（前三个的值是文件路径）：DEMO_STARTS 每次启动记一行进程号；DEMO_REFUSE 文件存在时启动即退出
（连不上）；DEMO_EXTRA 文件存在时多一个工具 extra（重连后工具变了）；DEMO_EXIT_AFTER 启动后
过这么多秒自己退出（刚连上就断）；DEMO_HTTP_PORT 给了端口时改用网络方式（streamable-http，
地址 http://127.0.0.1:<端口>/mcp）运行。
"""

import os
import sys
import threading
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("demo", log_level="WARNING")
NOTES: list[str] = []


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_notes() -> str:
    """列出已记下的笔记"""
    return f"pid={os.getpid()} notes={NOTES}"


@mcp.tool()
def add_note(text: str) -> str:
    """记下一条笔记"""
    NOTES.append(text)
    return f"pid={os.getpid()} added {text}"


@mcp.tool()
def fail() -> str:
    """总是出错"""
    raise ValueError("坏了")


@mcp.tool()
async def hang() -> str:
    """一直不返回"""
    await anyio.sleep(3600)  # 允许等待：模拟一直不返回的工具
    return "never"


def extra() -> str:
    """重连后才有的工具"""
    return "extra"


def _flag(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


if __name__ == "__main__":
    if (starts := _flag("DEMO_STARTS")) is not None:
        with starts.open("a") as file:
            file.write(f"{os.getpid()}\n")
    if (refuse := _flag("DEMO_REFUSE")) is not None and refuse.exists():
        sys.exit(1)
    if (flag := _flag("DEMO_EXTRA")) is not None and flag.exists():
        mcp.add_tool(extra)
    if exit_after := os.environ.get("DEMO_EXIT_AFTER"):
        threading.Timer(float(exit_after), os._exit, args=(0,)).start()
    if port := os.environ.get("DEMO_HTTP_PORT"):
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = int(port)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
