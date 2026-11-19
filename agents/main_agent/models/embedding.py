"""向量化（设计文档 4.1、8.5；D28）：把文字变成 768 维向量，意思相近的文字向量也相近。

可替换接口 Embedder。默认实现在后端进程里跑（onnx_embedder.py）；这里是接口和经 LiteLLM 网关
调用的实现（云端向量模型、端到端测试用）。
查询和文档要加的前缀跟着模型走，由实现来加：调用方只说明这批文字是查询还是文档。
每次请求后报告用量（设计文档 7.7：向量化不经过聊天回调，由实现直接报告），由组装根写进用量表。
"""

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from agents.main_agent.models.calls import current_call
from agents.main_agent.models.litellm_proxy import gateway_tags
from common.errors import UpstreamError

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 768  # 统一维度（D28）：表里的向量列按它建，换模型也要输出这个维度

type EmbedKind = Literal["query", "document"]  # 这批文字是用来搜的问句，还是存进去的内容


@dataclass(frozen=True)
class EmbeddingUsage:
    """一次向量化请求的用量（只算 token，设计 2026-10-19 4.11）。"""

    model: str
    input_tokens: int
    duration_ms: int


class Embedder(Protocol):
    @property
    def model(self) -> str:
        """所用的向量模型（记录到每个知识条目，换模型后据此重建向量）。"""
        ...

    async def embed(
        self, texts: Sequence[str], *, kind: EmbedKind = "document"
    ) -> list[list[float]]:
        """按输入顺序返回每段文字的向量。"""
        ...


class LiteLLMProxyEmbedder:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        batch_size: int = 32,
        transport: httpx.AsyncBaseTransport | None = None,
        on_usage: Callable[[EmbeddingUsage], Awaitable[None]] | None = None,
        query_prefix: str = "",
        document_prefix: str = "",
    ) -> None:
        self._prefixes: dict[EmbedKind, str] = {"query": query_prefix, "document": document_prefix}
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._batch_size = batch_size
        self._transport = transport  # 仅测试时注入
        self._on_usage = on_usage

    @property
    def model(self) -> str:
        return self._model

    async def embed(
        self, texts: Sequence[str], *, kind: EmbedKind = "document"
    ) -> list[list[float]]:
        texts = [self._prefixes[kind] + text for text in texts]
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            transport=self._transport,
            # 入库每批只有几段（设置 knowledge.ingest_batch_size）；网关到向量模型卡住时最多等
            # 30 秒就报"等待向量模型超时"（积压小问题 C10，原来 120 秒）。
            # 对话里的召回另有 5 秒上限，不受这里影响
            timeout=httpx.Timeout(30, connect=5),
        ) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = list(texts[start : start + self._batch_size])
                vectors.extend(await self._embed_batch(client, batch))
        return vectors

    async def _embed_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        # 原因会显示在知识库页和工具卡片上：只给一句中文，原始报错记进日志
        body: dict[str, Any] = {"model": self._model, "input": batch}
        if (call := current_call()) is not None:
            body.update(gateway_tags(call))  # 网关后台能按会话找到这次请求
        started = time.monotonic()
        try:
            response = await client.post("/embeddings", json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("向量化请求失败：%s", exc)
            raise UpstreamError(
                f"向量化服务不可用：模型网关返回 {exc.response.status_code}，"
                "网关里的向量模型可能没配好（模型页）"
            ) from exc
        except httpx.TimeoutException as exc:
            logger.warning("向量化请求超时：%s", exc)
            raise UpstreamError("向量化服务不可用：等待向量模型超时") from exc
        except httpx.HTTPError as exc:
            logger.warning("向量化请求失败：%s", exc)
            raise UpstreamError("向量化服务不可用：连不上模型网关") from exc
        try:
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors = [list(item["embedding"]) for item in data]
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("向量化服务返回了无法识别的数据：%s", response.text[:200])
            raise UpstreamError("向量化服务不可用：返回的数据无法识别") from exc
        for vector in vectors:
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise UpstreamError(
                    f"向量维度应为 {EMBEDDING_DIMENSIONS}，实际为 {len(vector)}：请检查向量模型配置"
                )
        await self._report(response, round((time.monotonic() - started) * 1000))
        return vectors

    async def _report(self, response: httpx.Response, duration_ms: int) -> None:
        if self._on_usage is None:
            return
        usage = response.json().get("usage") or {}
        try:
            await self._on_usage(
                EmbeddingUsage(
                    model=self._model,
                    input_tokens=int(usage.get("prompt_tokens") or 0),
                    duration_ms=duration_ms,
                )
            )
        except Exception:  # 用量记录失败不能影响向量化本身
            logger.exception("向量化的用量记录失败")
