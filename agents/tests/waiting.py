"""测试里等某件事发生（设计 2026-10-23 7.6：不靠固定等待保证先后顺序）。"""

import asyncio
import time
from collections.abc import Awaitable, Callable


async def until(
    check: Callable[[], bool | Awaitable[bool]], *, within: float = 5.0, what: str = "条件"
) -> None:
    """每 0.01 秒看一次 check，成立就返回；超过 within 秒还不成立就让测试失败。"""
    deadline = time.monotonic() + within
    while True:
        result = check()
        if isinstance(result, Awaitable):
            result = await result
        if result:
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"等了 {within} 秒，{what}还没成立")
        await asyncio.sleep(0.01)  # 允许等待：有上限的轮询
