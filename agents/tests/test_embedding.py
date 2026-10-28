"""LiteLLM 网关向量化实现：分批请求、带密钥、出错时给出看得懂的原因。"""

import json

import httpx
import pytest

from agents.main_agent.models import (
    EMBEDDING_DIMENSIONS,
    EmbeddingUsage,
    LiteLLMProxyEmbedder,
    call_context,
)
from common.errors import UpstreamError


async def test_sends_model_and_key_in_batches() -> None:
    requests: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        texts = json.loads(request.content)["input"]
        vector = [0.5] * EMBEDDING_DIMENSIONS
        return httpx.Response(
            200, json={"data": [{"index": i, "embedding": vector} for i in range(len(texts))]}
        )

    embedder = LiteLLMProxyEmbedder(
        "http://gateway:4000",
        "sk-test",
        "embed-qwen3-0.6b",
        batch_size=2,
        transport=httpx.MockTransport(gateway),
    )
    vectors = await embedder.embed(["a", "b", "c"])
    assert len(vectors) == 3
    assert [json.loads(r.content) for r in requests] == [
        {"model": "embed-qwen3-0.6b", "input": ["a", "b"]},
        {"model": "embed-qwen3-0.6b", "input": ["c"]},
    ]
    assert requests[0].url == "http://gateway:4000/embeddings"
    assert requests[0].headers["authorization"] == "Bearer sk-test"


async def test_unavailable_gateway_or_wrong_size_is_explained() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    embedder = LiteLLMProxyEmbedder(
        "http://gateway:4000", "k", "m", transport=httpx.MockTransport(refuse)
    )
    with pytest.raises(UpstreamError, match="向量化服务不可用"):
        await embedder.embed(["a"])

    def small(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 768}]})

    embedder = LiteLLMProxyEmbedder(
        "http://gateway:4000", "k", "m", transport=httpx.MockTransport(small)
    )
    with pytest.raises(UpstreamError, match="向量维度应为 1024，实际为 768"):
        await embedder.embed(["a"])


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")


def _hang(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out")


def _server_error(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": {"message": "OllamaException - Cannot connect"}})


def _odd_reply(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"unexpected": True})


@pytest.mark.parametrize(
    ("respond", "reason"),
    [
        (_refuse, "连不上模型网关"),
        (_hang, "超时"),
        (_server_error, "模型网关返回 500"),
        (_odd_reply, "无法识别"),
    ],
)
async def test_failures_are_explained_in_plain_chinese(respond: object, reason: str) -> None:
    """原因用一句中文说明（会显示在知识库页和工具卡片上），不带 httpx 的英文原文与网页链接。"""
    embedder = LiteLLMProxyEmbedder(
        "http://gateway:4000",
        "k",
        "m",
        transport=httpx.MockTransport(respond),  # type: ignore[arg-type]
    )
    with pytest.raises(UpstreamError) as caught:
        await embedder.embed(["a"])
    message = str(caught.value)
    assert message.startswith("向量化服务不可用")
    assert reason in message
    assert "http" not in message


def _gateway(requests: list[httpx.Request]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        texts = json.loads(request.content)["input"]
        vector = [0.5] * EMBEDDING_DIMENSIONS
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": vector} for i in range(len(texts))],
                "usage": {"prompt_tokens": 4, "completion_tokens": 0},
            },
        )

    return httpx.MockTransport(handle)


async def test_reports_usage_after_each_request() -> None:
    """设计文档 7.7：向量化调用也记入用量（本机模型不花钱，但次数与 token 要统计到）。"""
    reported: list[EmbeddingUsage] = []

    async def on_usage(usage: EmbeddingUsage) -> None:
        reported.append(usage)

    requests: list[httpx.Request] = []
    embedder = LiteLLMProxyEmbedder(
        "http://gateway:4000",
        "sk-test",
        "embed-qwen3-0.6b",
        transport=_gateway(requests),
        on_usage=on_usage,
    )
    await embedder.embed(["你好", "世界"])
    [usage] = reported
    assert (usage.model, usage.input_tokens) == ("embed-qwen3-0.6b", 4)
    assert usage.duration_ms >= 0


async def test_usage_callback_failure_does_not_break_embedding() -> None:
    async def broken(usage: EmbeddingUsage) -> None:
        raise RuntimeError("数据库断开")

    embedder = LiteLLMProxyEmbedder("http://g", "k", "m", transport=_gateway([]), on_usage=broken)
    assert len(await embedder.embed(["a"])) == 1


async def test_requests_in_a_call_context_carry_tags() -> None:
    requests: list[httpx.Request] = []
    embedder = LiteLLMProxyEmbedder("http://g", "k", "m", transport=_gateway(requests))
    with call_context("t1", None):
        await embedder.embed(["a"])
    body = json.loads(requests[0].content)
    assert body["litellm_session_id"] == "t1"
    assert body["metadata"] == {"tags": ["thread:t1"]}


async def test_gives_up_after_30_seconds() -> None:
    """向量请求最多等 30 秒、连接 5 秒（积压小问题 C10）：
    网关到 Ollama 卡住时不用每批等满 2 分钟。"""
    requests: list[httpx.Request] = []
    embedder = LiteLLMProxyEmbedder("http://g", "k", "m", transport=_gateway(requests))
    await embedder.embed(["a"])
    timeout = requests[0].extensions["timeout"]
    assert (timeout["read"], timeout["connect"]) == (30, 5)
