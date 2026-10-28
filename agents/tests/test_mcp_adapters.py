"""langchain-mcp-adapters 实现的细节（契约之外）：断线检测不误伤正在干活的服务。"""

import asyncio
import sys
from pathlib import Path

import pytest

from agents.main_agent.integrations import mcp_adapters
from agents.main_agent.integrations.mcp_adapters import McpAdaptersClient, ReconnectTiming
from agents.tests.waiting import until
from config import McpServerConfig

DEMO = Path(__file__).resolve().parent / "fixtures" / "mcp" / "demo_server.py"
FAST = ReconnectTiming(ping_interval=0.1, ping_timeout=2, retry_delays=(0.1,) * 5, retry_later=0.5)


async def test_no_ping_while_a_call_is_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """有调用在进行时不 ping：一次只处理一个请求的服务正忙时答不上 ping，不能因此判断开、
    把正在进行的调用打断（审查 Minor 5）。"""
    client = McpAdaptersClient(timing=FAST)
    config = McpServerConfig.model_validate(
        {"name": "demo", "command": sys.executable, "args": [str(DEMO)], "call_timeout": 30}
    )
    await client.connect([config])
    try:
        [connection] = client._connections
        pings: list[int] = []
        alive = connection._alive

        async def counting(session: object) -> bool:
            pings.append(1)
            return await alive(session)  # type: ignore[arg-type]

        monkeypatch.setattr(connection, "_alive", counting)
        tool = next(t.tool for t in client.tools() if t.name == "demo_hang")
        call = asyncio.create_task(
            tool.ainvoke({"type": "tool_call", "id": "c1", "name": "demo_hang", "args": {}})
        )
        await asyncio.sleep(0.6)  # 允许等待：断言 6 个 ping 间隔里都没有 ping，只能等够时长
        assert pings == []
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        await until(lambda: bool(pings), within=2.5, what="调用结束后照常 ping")
    finally:
        await client.close()


async def test_missing_env_hint_points_to_dotenv() -> None:
    """缺环境变量的服务不启动，提示按现在的做法写
    （积压小问题 F20：原来叫人改 docker-compose.yml）。"""
    client = McpAdaptersClient(timing=FAST)
    config = McpServerConfig.model_validate(
        {"name": "gh", "command": "npx", "missing_env": ["GITHUB_TOKEN"]}
    )
    await client.connect([config])
    try:
        [connection] = client._connections
        assert connection.error is not None
        assert "make restart" in connection.error
        assert "docker-compose" not in connection.error
    finally:
        await client.close()


async def test_server_that_drops_right_after_connecting_backs_off(tmp_path: Path) -> None:
    """刚连上就断的服务不再一直重启（积压小问题 E3）：连上后没稳定一段时间就不重设快速重试，
    一组用完就记成没连上，隔一段时间再试。"""
    starts = tmp_path / "starts"
    timing = ReconnectTiming(
        ping_interval=0.1, ping_timeout=2, retry_delays=(0.1,) * 5, retry_later=30, stable_after=5
    )
    client = McpAdaptersClient(timing=timing)
    env = {"DEMO_STARTS": str(starts), "DEMO_EXIT_AFTER": "0.3"}
    config = McpServerConfig.model_validate(
        {"name": "demo", "command": sys.executable, "args": [str(DEMO)], "env": env}
    )
    await client.connect([config])
    try:
        await until(lambda: client.statuses()[0].state == "failed", within=20, what="记成没连上")
        assert len(starts.read_text().split()) <= 1 + 5
    finally:
        await client.close()


HANG_LIST = Path(__file__).resolve().parent / "fixtures" / "mcp" / "hang_list_server.py"


async def test_timeout_while_listing_tools_says_timeout() -> None:
    """握手正常、取工具清单时不回：说"连接超时（1 秒）"（积压小问题 E6：原来只剩"连接失败：
    TimeoutError"）。"""
    config = McpServerConfig.model_validate(
        {"name": "hang", "command": sys.executable, "args": [str(HANG_LIST)], "connect_timeout": 1}
    )
    result = await McpAdaptersClient(timing=FAST).probe(config)
    assert result.error == "连接超时（1 秒）"


def test_failure_reason_is_redacted() -> None:
    """MCP 页上的失败原因打码（积压小问题 E5）。"""
    config = McpServerConfig.model_validate({"name": "demo", "command": "npx"})
    reason = mcp_adapters._reason(RuntimeError("token=sk-live-abcdef0123456789 rejected"), config)
    assert "sk-live-abcdef0123456789" not in reason


async def test_start_fallback_keeps_retrying(monkeypatch: pytest.MonkeyPatch) -> None:
    """启动时连接卡过了兜底时间：先记成没连上，之后照常隔一段时间再试（原来直接停掉，再也不试）。"""
    monkeypatch.setattr(mcp_adapters, "_STOP_TIMEOUT", 0.1)
    attempts = 0

    async def stuck(self: object) -> tuple[bool, str]:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.5)  # 允许等待：替身模拟连接与清理一直卡着
        return False, "卡住了"

    monkeypatch.setattr(mcp_adapters._Connection, "_attempt", stuck)
    timing = ReconnectTiming(ping_interval=0.1, ping_timeout=2, retry_delays=(), retry_later=0.1)
    client = McpAdaptersClient(timing=timing)
    config = McpServerConfig.model_validate(
        {"name": "demo", "command": "x", "connect_timeout": 0.1}
    )
    await client.connect([config])
    try:
        assert client.statuses()[0].state == "failed"
        await until(lambda: attempts >= 2, what="之后照常再试")
    finally:
        await client.close()


async def test_missing_env_hint_mentions_blanked_gateway_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """要的变量在后端被置成空（网关专用的密钥）：提示在 .env 里另起一个名字（积压小问题 E17）。"""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    client = McpAdaptersClient(timing=FAST)
    config = McpServerConfig.model_validate(
        {"name": "oa", "command": "npx", "missing_env": ["OPENAI_API_KEY"]}
    )
    await client.connect([config])
    try:
        [connection] = client._connections
        assert connection.error is not None
        assert "给 MCP 用请在 .env 另起一个名字" in connection.error
    finally:
        await client.close()


def test_reason_is_redacted_before_it_is_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    """密钥正好跨在截断处时也整段打码（第三批审查 Minor 2：原来先截断后打码，漏出前半截）。"""
    secret = "ghp_" + "a" * 36
    monkeypatch.setenv("GH_TOKEN", secret)
    config = McpServerConfig.model_validate({"name": "demo", "command": "npx"})
    reason = mcp_adapters._reason(RuntimeError("x" * 180 + secret), config)
    assert secret[:19] not in reason
