import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_litellm import ChatLiteLLM

from agents.main_agent.models import LiteLLMProxyGateway, ModelStalledError, call_context
from agents.main_agent.models.litellm_proxy import first_chunk_timeout
from agents.tests.contracts.test_model_gateway_contract import MODEL_INFO_PAYLOAD


async def test_chat_model_targets_gateway_with_profile() -> None:
    gateway = LiteLLMProxyGateway(
        "http://gateway:4000/",
        "sk-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=MODEL_INFO_PAYLOAD)),
    )
    await gateway.list_models()

    model = gateway.chat_model("claude-opus-5-5")

    assert isinstance(model, ChatLiteLLM)
    assert model.model == "litellm_proxy/claude-opus-5-5"
    assert model.api_base == "http://gateway:4000"
    assert model.streaming is True
    assert model.profile == {"max_input_tokens": 1000000}


def test_requests_carry_thread_and_run_tags() -> None:
    """每次请求都带上会话与运行（设计文档 7.1：便于在网关后台按会话核对）。"""
    model = LiteLLMProxyGateway("http://gw", "k").chat_model("m")
    assert isinstance(model, ChatLiteLLM)
    with call_context("t1", "r1"):
        params = model._client_params  # 每次请求时现算的参数
    assert params["extra_body"] == {
        "litellm_session_id": "t1",
        "metadata": {"tags": ["thread:t1", "run:r1"]},
    }
    plain = model._client_params
    assert "extra_body" not in plain  # 不在调用归属里时不带
    assert {k: v for k, v in params.items() if k != "extra_body"} == plain  # 其余参数不受影响
    with call_context("t2", None):
        assert model._client_params["extra_body"]["metadata"] == {"tags": ["thread:t2"]}


def test_tags_are_merged_into_existing_metadata() -> None:
    """已带了 extra_body.metadata 时按键合并，不整个换掉（积压小问题 G3）。"""
    model = LiteLLMProxyGateway("http://gw", "k").chat_model("m")
    assert isinstance(model, ChatLiteLLM)
    model.model_kwargs = {
        **model.model_kwargs,
        "extra_body": {"metadata": {"tags": ["team:a"], "trace_id": "x1"}, "user": "u"},
    }
    with call_context("t1", "r1"):
        extra = model._client_params["extra_body"]
    assert extra == {
        "user": "u",
        "litellm_session_id": "t1",
        "metadata": {"tags": ["team:a", "thread:t1", "run:r1"], "trace_id": "x1"},
    }


async def test_stalled_stream_is_abandoned_after_idle_timeout() -> None:
    """模型发来一段后不再发数据（网络断了、上游卡住）：超过空闲时限就放弃，给出中文原因。"""

    requests: list[int] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        requests.append(1)
        chunk = {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "def fib"},
                    "finish_reason": None,
                }
            ],
        }
        writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n\r\n")
        writer.write(f"data: {json.dumps(chunk)}\n\n".encode())
        await writer.drain()
        await asyncio.sleep(30)  # 允许等待：替身服务器之后再也不发
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    # 同一进程里 litellm 第一次调用要约 0.5 秒才发出请求，时限给 3 秒，免得把冷启动当成卡住
    model = LiteLLMProxyGateway(
        f"http://127.0.0.1:{port}", "sk-test", stream_idle_timeout=3
    ).chat_model("m")
    received: list[object] = []

    async def consume() -> None:
        async for chunk in model.astream([HumanMessage("写斐波那契")]):
            received.append(chunk.content)

    started = time.monotonic()
    try:
        with pytest.raises(ModelStalledError, match="3 秒"):
            await consume()
    finally:
        server.close()
    assert "def fib" in received
    assert time.monotonic() - started < 10
    assert len(requests) == 1  # 已经有输出了：不重试（重发会让已显示的内容重复）


# ---- 只在还没输出时重试；等第一个字的时限随上下文放宽（设计 2026-10-23 4.3） ----

type Behaviour = Callable[[asyncio.StreamWriter], Awaitable[None]]

_SSE_HEADER = b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n\r\n"


def _sse(delta: dict[str, Any] | None, *, finish: str | None = None, usage: bool = False) -> bytes:
    """一段流式片段；delta 为 None 时是只带用量的片段。"""
    chunk: dict[str, Any] = {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
    }
    chunk["choices"] = (
        [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]
    )
    if usage:
        chunk["usage"] = {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}
    return f"data: {json.dumps(chunk)}\n\n".encode()


async def _role_then_hang(writer: asyncio.StreamWriter) -> None:
    writer.write(_SSE_HEADER + _sse({"role": "assistant"}))
    await writer.drain()
    await asyncio.sleep(30)  # 允许等待：替身服务器卡住不发


async def _answer_ok(writer: asyncio.StreamWriter) -> None:
    writer.write(_SSE_HEADER + _sse({"role": "assistant", "content": "ok"}))
    writer.write(_sse({}, finish="stop") + _sse(None, usage=True) + b"data: [DONE]\n\n")
    await writer.drain()


async def _role_and_usage_only(writer: asyncio.StreamWriter) -> None:
    writer.write(_SSE_HEADER + _sse({"role": "assistant"}) + _sse({}, finish="stop"))
    writer.write(_sse(None, usage=True) + b"data: [DONE]\n\n")
    await writer.drain()


async def _server_error(writer: asyncio.StreamWriter) -> None:
    body = json.dumps({"error": {"message": "upstream exploded"}}).encode()
    writer.write(
        b"HTTP/1.1 500 Internal Server Error\r\ncontent-type: application/json\r\n"
        + f"content-length: {len(body)}\r\n\r\n".encode()
        + body
    )
    await writer.drain()


async def _serve(behaviours: list[Behaviour]) -> tuple[asyncio.Server, list[int]]:
    """本机假网关：第 n 个请求按第 n 个剧本回（用完后重复最后一个），记下收到几个请求。"""
    seen: list[int] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        seen.append(len(seen) + 1)
        await behaviours[min(len(seen), len(behaviours)) - 1](writer)
        writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0), seen


async def _collect(server: asyncio.Server, idle: float) -> list[Any]:
    port = server.sockets[0].getsockname()[1]
    model = LiteLLMProxyGateway(
        f"http://127.0.0.1:{port}", "sk-test", stream_idle_timeout=idle
    ).chat_model("m")
    return [chunk async for chunk in model.astream([HumanMessage("你好")])]


def test_first_chunk_timeout_grows_with_input() -> None:
    assert first_chunk_timeout(0, 120) == 120
    assert first_chunk_timeout(100_000, 120) == 180
    assert first_chunk_timeout(1_000_000, 120) == 300
    assert first_chunk_timeout(1_000_000, 400) == 400


async def test_stall_before_any_output_retries_once() -> None:
    """还没有任何输出就卡住：自动重发一次同样的请求，用户看不出来。"""
    server, seen = await _serve([_role_then_hang, _answer_ok])
    try:
        chunks = await _collect(server, idle=3)
    finally:
        server.close()
    assert "".join(str(chunk.content) for chunk in chunks) == "ok"
    assert len(seen) == 2


async def test_second_stall_before_output_gives_up() -> None:
    server, seen = await _serve([_role_then_hang, _role_then_hang])
    try:
        with pytest.raises(ModelStalledError, match="还没有开始输出"):
            await _collect(server, idle=2)
    finally:
        server.close()
    assert len(seen) == 2


async def test_stream_without_content_still_returns_usage() -> None:
    """模型什么都没说就正常结束：扣住的片段照样交出去，用量不丢、不算卡住。"""
    server, seen = await _serve([_role_and_usage_only])
    try:
        chunks = await _collect(server, idle=3)
    finally:
        server.close()
    assert any(chunk.usage_metadata for chunk in chunks)
    assert len(seen) == 1


async def test_client_does_not_retry_failed_requests() -> None:
    """重试只留网关一层：后端客户端遇到出错不自己再发。"""
    server, seen = await _serve([_server_error])
    try:
        with pytest.raises(Exception, match="upstream exploded"):
            await _collect(server, idle=3)
    finally:
        server.close()
    assert len(seen) == 1


def test_stall_message_rounds_seconds_and_tells_whether_anything_was_output() -> None:
    """报错卡片上的原因：秒数取整；还没有任何输出时不说"已生成的内容保留"（审查 M9）。"""
    before = str(ModelStalledError(183.456, started=False))
    assert "183 秒" in before
    assert "183.456" not in before
    assert "还没有开始输出" in before
    assert "已生成的内容保留" not in before
    after = str(ModelStalledError(120))
    assert after.startswith("模型超过 120 秒没有发来新内容")
    assert "已生成的内容保留" in after
