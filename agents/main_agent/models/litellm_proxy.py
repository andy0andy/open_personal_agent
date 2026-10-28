"""模型网关实现：LiteLLM 网关，智能体侧用 langchain-litellm 的 ChatLiteLLM 调用。"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_litellm import ChatLiteLLM

from agents.main_agent.models.base import ModelInfo, ModelSpec, ModelStalledError, ModelTestResult
from agents.main_agent.models.calls import CallContext, current_call
from agents.main_agent.models.estimate import estimate_input_tokens
from common.errors import UpstreamError

logger = logging.getLogger(__name__)

# 提示缓存的断点（设计 2026-10-23 4.1）：系统消息一个、最后一条消息一个（网关最多 4 个）。
# 网关转发时给这两处加上缓存标记，Claude 据此缓存"工具 + 系统提示词"和到上一轮为止的对话
CACHE_POINTS: list[dict[str, Any]] = [
    {"location": "message", "role": "system"},
    {"location": "message", "index": -1},
]


# 等第一个片段的时限随上下文放宽（设计 2026-10-23 4.3）：上下文越长，模型开口越慢
_FIRST_CHUNK_STEP = 60.0  # 每 10 万输入 token 多等这么多秒
_FIRST_CHUNK_PER = 100_000
_FIRST_CHUNK_MAX = 300.0


def first_chunk_timeout(input_tokens: int, idle: float) -> float:
    """等第一个有内容的片段最多多少秒：空闲时限 + 每 10 万输入 token 加 60 秒，最多 300 秒
    （空闲时限本身设得更长时以它为准）。"""
    extra = _FIRST_CHUNK_STEP * input_tokens / _FIRST_CHUNK_PER
    return min(idle + extra, max(idle, _FIRST_CHUNK_MAX))


class LiteLLMProxyGateway:
    """通过 LiteLLM 网关访问所有模型版本。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        stream_idle_timeout: float = 120,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._stream_idle_timeout = stream_idle_timeout
        self._transport = transport  # 仅测试时注入
        self._known: dict[str, ModelInfo] = {}

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, transport=self._transport, timeout=10
            ) as client:
                resp = await client.get(
                    "/model/info", headers={"Authorization": f"Bearer {self._api_key}"}
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(f"模型网关不可用：{exc}") from exc
        models = [_to_model_info(item) for item in resp.json()["data"]]
        self._known = {model.name: model for model in models}
        return models

    def model_info(self, name: str) -> ModelInfo | None:
        return self._known.get(name)

    # ---- 管理页面（D21）：网关的模型管理接口，存进网关数据库，不用重启网关 ----

    async def add_model(self, spec: ModelSpec) -> ModelInfo:
        saved = await self._admin("POST", "/model/new", _deployment(spec))
        return await self._listed(spec, str(saved.get("model_id") or ""))

    async def update_model(self, model_id: str, spec: ModelSpec) -> ModelInfo:
        """整份替换：先按新内容新增一份，再删掉旧的。

        先行验证（2026-10-18）：网关的 PATCH 是合并写入，传 null 也去不掉已有的参数，
        关掉"思考"后 thinking 还会留在网关里。删旧的失败时把新的也删掉，不留同名的两份
        （网关会把调用分摊到同名的几份上）。
        """
        saved = await self._admin("POST", "/model/new", _deployment(spec))
        new_id = str(saved.get("model_id") or "")
        try:
            await self._admin("POST", "/model/delete", {"id": model_id})
        except UpstreamError:
            if new_id:
                with contextlib.suppress(UpstreamError):
                    await self._admin("POST", "/model/delete", {"id": new_id})
            raise
        return await self._listed(spec, new_id)

    async def delete_model(self, model_id: str) -> None:
        await self._admin("POST", "/model/delete", {"id": model_id})
        await self.list_models()

    async def test_model(self, name: str) -> ModelTestResult:
        info = self._known.get(name)
        body: dict[str, Any]
        if info is not None and info.mode == "embedding":
            path, body = "/embeddings", {"model": name, "input": "ping"}
        else:
            path = "/chat/completions"
            body = {
                "model": name,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
        started = time.monotonic()
        try:
            async with self._client(timeout=60) as client:
                resp = await client.post(path, json=body)
        except httpx.HTTPError as exc:
            return ModelTestResult(ok=False, latency_ms=_since(started), error=f"调用失败：{exc}")
        if resp.status_code >= 400:
            return ModelTestResult(
                ok=False, latency_ms=_since(started), error=f"调用失败：{_reason(resp)}"
            )
        return ModelTestResult(ok=True, latency_ms=_since(started))

    def _client(self, timeout: float = 10) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            transport=self._transport,
            timeout=timeout,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    async def _admin(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._client() as client:
                resp = await client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"模型网关不可用：{exc}") from exc
        if resp.status_code >= 400:
            raise UpstreamError(f"网关拒绝了：{_reason(resp)}")
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def _listed(self, spec: ModelSpec, model_id: str) -> ModelInfo:
        """保存后重新拉清单；网关的清单可能稍后才更新，那时先按保存的内容回给页面。"""
        with contextlib.suppress(UpstreamError):
            await self.list_models()
        return self._known.get(spec.name) or ModelInfo(
            name=spec.name,
            mode=spec.mode,
            max_input_tokens=spec.max_input_tokens,
            input_cost_per_token=spec.input_cost_per_token,
            output_cost_per_token=spec.output_cost_per_token,
            supports_reasoning=spec.supports_reasoning,
            supports_vision=spec.supports_vision,
            id=model_id or None,
            upstream=spec.upstream,
            max_output_tokens=spec.max_output_tokens,
            supports_function_calling=spec.supports_function_calling,
            supports_prompt_caching=spec.supports_prompt_caching,
        )

    def chat_model(self, name: str) -> BaseChatModel:
        info = self._known.get(name)
        # deepagents 按 profile 里的上下文长度决定何时压缩；网关信息缺失时交给它的默认值
        profile = None
        if info and info.max_input_tokens:
            profile = {"max_input_tokens": info.max_input_tokens}
        return _TaggedChatLiteLLM(
            model=f"litellm_proxy/{name}",
            api_base=self._base_url,
            api_key=self._api_key,
            streaming=True,
            stream_options={"include_usage": True},
            profile=profile,
            stream_idle_timeout=self._stream_idle_timeout,
            # 重试只留网关一层（设计 2026-10-23 4.3）：客户端（OpenAI SDK）默认还会自己重试 2 次
            model_kwargs={"max_retries": 0},
        )


class _TaggedChatLiteLLM(ChatLiteLLM):
    """每次请求带上会话与运行（call_context），网关后台的日志里能按会话、按运行找到。

    要经 extra_body 传给网关（先行探测）：metadata、tags 这两个参数名与 LangChain 自己的冲突，
    直接传的 litellm_session_id 也到不了网关。_client_params 每次请求时现算，在这里并入。

    回答中途上游不再发数据（网络断了、上游卡住）时，各层都不会很快超时，运行会一直挂着；
    所以每等下一段内容最多 stream_idle_timeout 秒，超过就放弃这次调用（ModelStalledError）。
    还没有任何输出就卡住时自动重发一次（设计 2026-10-23 4.3）：开头的空片段先扣住，
    收到第一个有内容的片段才算"已有输出"；等它的时限随上下文放宽（first_chunk_timeout）。
    """

    stream_idle_timeout: float = 120

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        first_wait = first_chunk_timeout(
            _input_tokens(messages, kwargs.get("tools")), self.stream_idle_timeout
        )
        for attempt in (1, 2):
            stream = super()._astream(messages, stop, run_manager, **kwargs)
            held: list[ChatGenerationChunk] = []  # 还没有内容时收到的空片段
            started = False
            try:
                while True:
                    timer = asyncio.timeout(self.stream_idle_timeout if started else first_wait)
                    try:
                        async with timer:
                            chunk = await anext(stream)
                    except StopAsyncIteration:
                        for item in held:
                            yield item
                        return
                    except TimeoutError as exc:
                        if not timer.expired():
                            raise
                        if started:
                            raise ModelStalledError(self.stream_idle_timeout) from exc
                        if attempt == 2:
                            raise ModelStalledError(first_wait, started=False) from exc
                        logger.warning("模型 %.0f 秒没有开始输出，重发一次同样的请求", first_wait)
                        break
                    if not started and not _has_output(chunk):
                        held.append(chunk)
                        continue
                    if not started:
                        started = True
                        for item in held:
                            yield item
                    yield chunk
            finally:
                if isinstance(stream, AsyncGenerator):
                    await stream.aclose()  # 关掉连接：网关随之取消上游的请求

    @property
    def _client_params(self) -> dict[str, Any]:
        params = super()._client_params
        call = current_call()
        if call is None:
            return params
        return {**params, "extra_body": _with_tags(params.get("extra_body") or {}, call)}


def _input_tokens(messages: list[BaseMessage], tools: Any) -> int:
    """这次请求大约多少输入 token（只用来放宽等第一个字的时限，估不出来时按 0）。"""
    try:
        return estimate_input_tokens(messages, tools if isinstance(tools, list) else None)
    except Exception:  # 估算失败不能影响调用本身
        logger.warning("估算输入 token 失败，按默认时限等待", exc_info=True)
        return 0


def _has_output(chunk: ChatGenerationChunk) -> bool:
    """片段里有没有真正的输出：文字、思考或工具调用（只有角色、用量的空片段不算）。"""
    message = chunk.message
    if message.content:
        return True
    if isinstance(message, AIMessageChunk) and message.tool_call_chunks:
        return True
    return bool(message.additional_kwargs.get("reasoning_content"))


def gateway_tags(call: CallContext) -> dict[str, Any]:
    """LiteLLM 网关认的会话与标签字段（向量化请求同样用它）。"""
    tags = [f"thread:{call.thread_id}"]
    if call.run_id is not None:
        tags.append(f"run:{call.run_id}")
    return {"litellm_session_id": call.thread_id, "metadata": {"tags": tags}}


def _with_tags(extra_body: dict[str, Any], call: CallContext) -> dict[str, Any]:
    """把会话与运行的标签并进已有的 extra_body：metadata 按键合并、tags 接在原有的后面，
    不把原来的整个换掉（积压小问题 G3）。"""
    tags = gateway_tags(call)
    metadata = dict(extra_body.get("metadata") or {})
    metadata["tags"] = [*metadata.get("tags", []), *tags["metadata"]["tags"]]
    return {**extra_body, "litellm_session_id": tags["litellm_session_id"], "metadata": metadata}


def _to_model_info(item: dict[str, Any]) -> ModelInfo:
    info = item.get("model_info") or {}
    params = item.get("litellm_params") or {}
    return ModelInfo(
        name=item["model_name"],
        mode=info.get("mode") or "chat",
        max_input_tokens=info.get("max_input_tokens"),
        input_cost_per_token=info.get("input_cost_per_token"),
        output_cost_per_token=info.get("output_cost_per_token"),
        supports_reasoning=bool(info.get("supports_reasoning")),
        supports_vision=bool(info.get("supports_vision")),
        id=info.get("id") if info.get("db_model") else None,
        upstream=params.get("model"),
        max_output_tokens=info.get("max_output_tokens"),
        supports_function_calling=bool(info.get("supports_function_calling")),
        # 以真正生效的缓存断点为准，不看 model_info 里的记录
        supports_prompt_caching=bool(params.get("cache_control_injection_points")),
    )


def _deployment(spec: ModelSpec) -> dict[str, Any]:
    """网关的一条模型部署。先行验证：价格必须放在调用参数里，放在模型信息里会被丢掉。"""
    params: dict[str, Any] = {
        "model": spec.upstream,
        "api_base": spec.api_base,
        "input_cost_per_token": spec.input_cost_per_token,
        "output_cost_per_token": spec.output_cost_per_token,
        **spec.extra_params,
    }
    if spec.supports_prompt_caching:
        params["cache_control_injection_points"] = CACHE_POINTS
    if spec.api_key:
        params["api_key"] = spec.api_key
    info = {
        "mode": spec.mode,
        "max_input_tokens": spec.max_input_tokens,
        "max_output_tokens": spec.max_output_tokens,
        "supports_reasoning": spec.supports_reasoning,
        "supports_vision": spec.supports_vision,
        "supports_function_calling": spec.supports_function_calling,
        "supports_prompt_caching": spec.supports_prompt_caching,
    }
    return {
        "model_name": spec.name,
        "litellm_params": params,
        "model_info": {k: v for k, v in info.items() if v is not None},
    }


def _reason(resp: httpx.Response) -> str:
    """网关的错误原因（取 error.message，取不到时用状态码）。"""
    try:
        error = resp.json().get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
    except ValueError:
        message = None
    return str(message or f"HTTP {resp.status_code}")[:300]


def _since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
