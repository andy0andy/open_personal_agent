"""MCP 客户端契约测试（设计文档 4.2 mcp_client）：所有 McpClient 实现都必须通过同一套测试。

用测试用服务 fixtures/mcp/demo_server.py（以当前 Python 启动，不需要 Node）。
"""

import asyncio
import os
import re
import signal
import socket
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from agents.main_agent.integrations import McpAdaptersClient, McpClient
from agents.main_agent.integrations.mcp_adapters import ReconnectTiming
from agents.tests.waiting import until
from config import McpServerConfig

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "mcp" / "demo_server.py"
type Factory = Callable[[], McpClient]


def demo(**fields: object) -> McpServerConfig:
    return McpServerConfig.model_validate(
        {"name": "demo", "command": sys.executable, "args": [str(DEMO)], **fields}
    )


# 断线重连的时间间隔调小（正式为每 30 秒 ping、1/2/4/8/16 秒重试、之后每 5 分钟）
FAST = ReconnectTiming(ping_interval=0.2, ping_timeout=2, retry_delays=(0.1,) * 5, retry_later=0.5)


@pytest.fixture(params=["mcp_adapters"])
def make(request: pytest.FixtureRequest) -> Factory:
    return lambda: McpAdaptersClient(timing=FAST)


@pytest.fixture
async def client(make: Factory) -> AsyncIterator[McpClient]:
    client = make()
    await client.connect([demo()])
    yield client
    await client.close()


async def _call(client: McpClient, name: str, args: dict[str, object]) -> ToolMessage:
    tool = next(t.tool for t in client.tools() if t.name == name)
    result = await tool.ainvoke({"type": "tool_call", "id": "c1", "name": name, "args": args})
    assert isinstance(result, ToolMessage)
    return result


def _text(message: ToolMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(str(block.get("text", "")) for block in content if isinstance(block, dict))


def _pid(message: ToolMessage) -> int:
    match = re.search(r"pid=(\d+)", _text(message))
    assert match is not None
    return int(match.group(1))


async def test_tools_carry_prefix_and_read_only(client: McpClient) -> None:
    tools = {t.name: t for t in client.tools()}
    assert set(tools) == {"demo_list_notes", "demo_add_note", "demo_fail", "demo_hang"}
    assert (tools["demo_list_notes"].read_only, tools["demo_add_note"].read_only) == (True, None)
    assert tools["demo_add_note"].server == "demo"
    assert tools["demo_add_note"].description == "记下一条笔记"
    [status] = client.statuses()
    assert (status.name, status.state, status.error) == ("demo", "connected", None)
    assert set(status.tools) == set(tools)


async def test_one_process_serves_all_calls(client: McpClient) -> None:
    added = await _call(client, "demo_add_note", {"text": "买牛奶"})
    listed = await _call(client, "demo_list_notes", {})
    assert "买牛奶" in _text(listed)
    assert _pid(added) == _pid(listed)


async def test_tool_failure_is_reported(client: McpClient) -> None:
    result = await _call(client, "demo_fail", {})
    assert result.status == "error"
    assert "坏了" in _text(result)


async def test_slow_call_times_out(make: Factory) -> None:
    client = make()
    await client.connect([demo(call_timeout=1)])
    try:
        async with asyncio.timeout(5):
            # 说中文、是 TimeoutError：调用方据此认出是我们自己的话（积压小问题 E8）
            with pytest.raises(TimeoutError, match="调用超时（1 秒）"):
                await _call(client, "demo_hang", {})
    finally:
        await client.close()


async def test_broken_server_fails_with_reason(make: Factory) -> None:
    client = make()
    broken = demo(name="broken", command="no-such-command-xyz", args=[])
    await client.connect([demo(), broken])
    try:
        statuses = client.statuses()
        assert [s.state for s in statuses] == ["connected", "failed"]
        assert "找不到命令 no-such-command-xyz" in (statuses[1].error or "")
        assert {t.server for t in client.tools()} == {"demo"}
    finally:
        await client.close()


async def test_missing_env_and_disabled_are_not_started(make: Factory) -> None:
    client = make()
    await client.connect([demo(missing_env=["TOKEN"]), demo(name="off", enabled=False)])
    try:
        statuses = client.statuses()
        assert [s.state for s in statuses] == ["failed", "disabled"]
        assert "TOKEN" in (statuses[0].error or "")
        assert client.tools() == []
    finally:
        await client.close()


async def _exited(pid: int) -> bool:
    """进程是否已退出（最多等 3 秒）。"""
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.1)  # 允许等待：有上限的轮询（进程退出没有可等的事件）
    return False


async def test_connect_again_replaces_servers(make: Factory) -> None:
    client = make()
    await client.connect([demo()])
    pid = _pid(await _call(client, "demo_list_notes", {}))
    await client.connect([])
    assert (client.tools(), client.statuses()) == ([], [])
    assert await _exited(pid)


async def test_close_stops_servers(make: Factory) -> None:
    client = make()
    await client.connect([demo()])
    pid = _pid(await _call(client, "demo_list_notes", {}))
    await client.close()
    assert await _exited(pid)


async def test_probe_lists_tools_without_touching_connections(client: McpClient) -> None:
    """测试连接：单独连一次、列出工具后断开，已有的连接不受影响（管理页面的"测试连接"）。"""
    other = demo().model_copy(update={"name": "other"})
    result = await client.probe(other)
    assert result.ok is True
    assert result.error is None
    assert "other_add_note" in result.tools
    [status] = client.statuses()
    assert (status.name, status.state) == ("demo", "connected")


async def test_probe_reports_failure(make: Factory) -> None:
    client = make()
    result = await client.probe(McpServerConfig(name="ghost", command="no-such-command-x"))
    assert (result.ok, result.tools) == (False, [])
    assert result.error == "找不到命令 no-such-command-x"
    await client.close()


DISCONNECTED = "服务 demo 暂时断开，正在重连；这次不要再调用它的工具"


async def _until(check: Callable[[], bool], seconds: float = 15) -> None:
    """等到条件成立（状态由后台任务改，没有可等的事件，只能隔一会儿看一次）。"""
    for _ in range(int(seconds / 0.02)):
        if check():
            return
        await asyncio.sleep(0.02)  # 允许等待：有上限的轮询
    raise AssertionError("等待超时")


def _state(client: McpClient) -> str:
    [status] = client.statuses()
    return status.state


async def test_dead_server_is_reconnected(make: Factory) -> None:
    """服务进程挂了：状态先是"重连中"，再回到"已连接"，之后调用照常（新进程）；工具没变不通知。"""
    client = make()
    await client.connect([demo()])
    changed: list[int] = []
    client.on_tools_changed(lambda: changed.append(1))
    try:
        pid = _pid(await _call(client, "demo_list_notes", {}))
        os.kill(pid, signal.SIGKILL)
        await _until(lambda: _state(client) == "reconnecting")
        assert {t.name for t in client.tools()} >= {"demo_list_notes"}  # 重连中工具还在
        await _until(lambda: _state(client) == "connected")
        assert _pid(await _call(client, "demo_list_notes", {})) != pid
        assert changed == []
    finally:
        await client.close()


async def test_call_while_reconnecting_returns_a_message(make: Factory) -> None:
    """刚断开（还没发现或正在重连）时调用：不抛异常，返回一句中文提示，作为出错的结果。"""
    client = make()
    await client.connect([demo()])
    try:
        pid = _pid(await _call(client, "demo_list_notes", {}))
        os.kill(pid, signal.SIGKILL)
        async with asyncio.timeout(5):
            result = await _call(client, "demo_add_note", {"text": "x"})
        assert (result.status, _text(result)) == ("error", DISCONNECTED)
        await _until(lambda: _state(client) == "reconnecting")
        result = await _call(client, "demo_add_note", {"text": "x"})
        assert (result.status, _text(result)) == ("error", DISCONNECTED)
    finally:
        await client.close()


async def test_gives_up_after_five_tries_then_retries_later(make: Factory, tmp_path: Path) -> None:
    starts, refuse = tmp_path / "starts", tmp_path / "refuse"
    client = make()
    await client.connect([demo(env={"DEMO_STARTS": str(starts), "DEMO_REFUSE": str(refuse)})])
    try:
        pid = _pid(await _call(client, "demo_list_notes", {}))
        refuse.touch()
        os.kill(pid, signal.SIGKILL)
        await _until(lambda: _state(client) == "failed")
        assert len(starts.read_text().split()) == 6  # 第一次启动 + 重试 5 次
        [status] = client.statuses()
        assert status.error
        assert client.tools() == []  # 没连上：工具不再交给智能体
        refuse.unlink()
        await _until(lambda: _state(client) == "connected")  # 之后隔一段时间再试
        assert _text(await _call(client, "demo_list_notes", {})).startswith("pid=")
    finally:
        await client.close()


async def test_tool_change_after_reconnect_is_reported(make: Factory, tmp_path: Path) -> None:
    extra = tmp_path / "extra"
    client = make()
    await client.connect([demo(env={"DEMO_EXTRA": str(extra)})])
    changed: list[set[str]] = []
    client.on_tools_changed(lambda: changed.append({t.name for t in client.tools()}))
    try:
        pid = _pid(await _call(client, "demo_list_notes", {}))
        extra.touch()
        os.kill(pid, signal.SIGKILL)
        await _until(lambda: "demo_extra" in {t.name for t in client.tools()})
        assert changed
        assert "demo_extra" in changed[-1]
        assert _text(await _call(client, "demo_extra", {})) == "extra"
    finally:
        await client.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _http_demo(port: int) -> asyncio.subprocess.Process:
    """以网络方式（streamable-http）启动测试服务，等它开始监听。"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(DEMO),
        env={**os.environ, "DEMO_HTTP_PORT": str(port)},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def listening() -> bool:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            return False
        writer.close()
        return True

    await until(listening, within=15, what="测试服务开始监听")
    return process


async def test_http_server_is_reconnected(make: Factory) -> None:
    """网络方式（streamable_http）的服务断了也会重连，回来后调用照常（积压小问题 I16：
    原来断线重连只测了标准输入输出方式）。"""
    port = _free_port()
    server = await _http_demo(port)
    client = make()
    config = McpServerConfig.model_validate(
        {"name": "demo", "transport": "streamable_http", "url": f"http://127.0.0.1:{port}/mcp"}
    )
    try:
        await client.connect([config])
        assert _state(client) == "connected"
        server.kill()
        await server.wait()
        await until(lambda: _state(client) != "connected", within=10, what="发现断开")
        server = await _http_demo(port)
        await until(lambda: _state(client) == "connected", within=20, what="重新连上")
        assert "notes=" in _text(await _call(client, "demo_list_notes", {}))
    finally:
        await client.close()
        if server.returncode is None:
            server.kill()
            await server.wait()
