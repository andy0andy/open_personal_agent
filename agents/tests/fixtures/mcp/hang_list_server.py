"""测试用 MCP 服务：握手正常，取工具清单时一直不回（积压小问题 E6：取清单阶段超时）。"""

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

server: Server = Server("hang")


@server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]  # mcp 底层装饰器没有类型
async def list_tools() -> list[types.Tool]:
    await anyio.sleep(3600)  # 允许等待：被测的就是一直不回
    return []


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


anyio.run(main)
