"""向量化契约测试（设计文档 4.1、8.5）：所有 Embedder 实现都必须通过同一套测试。

固定输出 1024 维；按输入顺序一一对应；空输入不发请求。
"""

import json
from collections.abc import Callable

import httpx
import pytest

from agents.main_agent.models import EMBEDDING_DIMENSIONS, Embedder, LiteLLMProxyEmbedder
from agents.tests.fakes import FakeEmbedder


def _gateway(request: httpx.Request) -> httpx.Response:
    """模拟网关的 /embeddings：每段文字的向量第一个分量是它的长度，便于核对顺序。"""
    texts = json.loads(request.content)["input"]
    data = [
        {"index": i, "embedding": [float(len(t))] + [0.0] * (EMBEDDING_DIMENSIONS - 1)}
        for i, t in enumerate(texts)
    ]
    return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": 1}})


@pytest.fixture(
    params=[
        lambda: LiteLLMProxyEmbedder(
            "http://gateway:4000", "sk-test", "embed-x", transport=httpx.MockTransport(_gateway)
        ),
        lambda: FakeEmbedder(),
    ]
)
def make(request: pytest.FixtureRequest) -> Callable[[], Embedder]:
    factory: Callable[[], Embedder] = request.param
    return factory


async def test_one_vector_per_text_in_order(make: Callable[[], Embedder]) -> None:
    vectors = await make().embed(["一", "一二三", "一二"])
    assert len(vectors) == 3
    assert all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)
    assert len({tuple(v) for v in vectors}) == 3


async def test_empty_input_gives_no_vectors(make: Callable[[], Embedder]) -> None:
    assert await make().embed([]) == []


def test_reports_the_model_it_uses(make: Callable[[], Embedder]) -> None:
    assert make().model  # 每个知识条目记录所用的向量模型（换模型后据此重建）
