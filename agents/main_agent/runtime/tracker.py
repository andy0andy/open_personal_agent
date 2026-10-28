"""运行跟踪器：挂在一次运行的回调上（设计文档 7.7），覆盖主智能体、子智能体、自动压缩的模型调用。

四件事：
1. 记下"子智能体命名空间 → 派出它的 task 调用 ID"。输出流里子智能体片段的命名空间形如
   "tools:<随机ID>"，与调用 ID 无关；只有工具开始回调同时给出两者，并行派出多个子智能体也不会混淆。
2. 每次模型调用结束时生成一条用量事件，等运行循环取走后推送。
3. 运行被中断时，估算尚未结束的调用的用量：中断后网关不返回用量，按发送的内容与已输出的文字
   粗略估算，再用该模型最近一次完成的调用校准（token 数按"实际 / 估算"的比例）。只算 token，
   不算费用（设计 2026-10-19 4.11）。
4. 主智能体每次调用模型时，按最终请求算出上下文各部分的大小（设计 2026-10-23 4.7）。
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, GenerationChunk, LLMResult

from agents.main_agent.models import (
    ModelStalledError,
    estimate_input_tokens,
    estimate_text_tokens,
    version_name,
)
from agents.main_agent.runtime.context_usage import context_usage
from agents.main_agent.runtime.events import MAIN, ContextUsage, InterruptedUsage, UsageReported

logger = logging.getLogger(__name__)


@dataclass
class Calibration:
    """某个模型版本最近一次完成的调用留下的校准值，由同一个主智能体的各次运行共享。"""

    token_ratio: float = 1.0  # 实际输入 / 粗略估算的输入


@dataclass
class _Call:
    """一次进行中的模型调用。"""

    started: float
    metadata: dict[str, Any]
    estimated_input: int
    output: list[str] = field(default_factory=list)  # 已输出的文字与思考片段


class RunTracker(AsyncCallbackHandler):
    def __init__(
        self,
        *,
        calibration: dict[str, Calibration] | None = None,
        context_limit: int | None = None,
    ) -> None:
        self._calls: dict[str, str] = {}
        self._started: dict[UUID, _Call] = {}
        self._usage: list[UsageReported] = []
        self._context: list[ContextUsage] = []
        self._context_limit = context_limit  # 主智能体所用模型的上下文上限
        self._calibration = calibration if calibration is not None else {}  # 模型版本 → 校准值
        self._estimate_failed = False
        self._context_failed = False

    def agent_path(self, namespace: Sequence[str]) -> list[str]:
        """由输出流的命名空间推导 agent_path；未登记的段原样保留。"""
        return [MAIN, *(self._calls.get(segment, segment) for segment in namespace)]

    def drain_usage(self) -> list[UsageReported]:
        """取走目前收集到的用量事件。"""
        usage, self._usage = self._usage, []
        return usage

    def drain_context(self) -> list[ContextUsage]:
        """取走目前收集到的上下文占用事件。"""
        context, self._context = self._context, []
        return context

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        call_id = kwargs.get("tool_call_id")
        namespace = (metadata or {}).get("langgraph_checkpoint_ns", "")
        if call_id and namespace:
            # 形如 "tools:<父>|tools:<本次>"，最后一段就是这次工具调用（子智能体）所在的命名空间
            self._calls[namespace.split("|")[-1]] = call_id

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        tools = (kwargs.get("invocation_params") or {}).get("tools")
        request = messages[0] if messages else []
        metadata = metadata or {}
        try:
            estimated = estimate_input_tokens(request, tools)
        except Exception:  # 估算只用于显示，失败不能影响调用本身
            if not self._estimate_failed:  # 每次调用都会遇到同样的内容：一次运行只提示一次
                self._estimate_failed = True
                logger.warning("估算输入 token 失败，本次运行不再提示", exc_info=True)
            estimated = 0
        self._started[run_id] = _Call(time.monotonic(), metadata, estimated)
        if estimated and _is_main_call(metadata):
            try:  # 分段算不出来只是这次不显示分段，不影响中断时的估算
                self._context.append(
                    context_usage(
                        request,
                        tools,
                        whole=estimated,
                        ratio=self._ratio(metadata),
                        limit=self._context_limit,
                    )
                )
            except Exception:
                if not self._context_failed:
                    self._context_failed = True
                    logger.warning("计算上下文分段失败，本次运行不再提示", exc_info=True)

    async def on_llm_new_token(
        self,
        token: str | list[str | dict[str, Any]],
        *,
        chunk: GenerationChunk | ChatGenerationChunk | None = None,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        call = self._started.get(run_id)
        if call is None:
            return
        if isinstance(token, str):
            call.output.append(token)
        else:  # 内容块形式：文字块与思考块都算输出
            for block in token:
                text = (
                    block if isinstance(block, str) else block.get("text") or block.get("thinking")
                )
                if isinstance(text, str):
                    call.output.append(text)
        if isinstance(chunk, ChatGenerationChunk):
            reasoning = chunk.message.additional_kwargs.get("reasoning_content")
            if isinstance(reasoning, str):
                call.output.append(reasoning)

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        # 卡住被放弃的调用照样花了钱（输入与已输出的部分），留着给 interrupted_usage 估算
        if not isinstance(error, ModelStalledError):
            self._started.pop(run_id, None)

    def interrupted_usage(self) -> InterruptedUsage | None:
        """估算尚未结束的调用（被中断）的用量；没有进行中的调用时返回 None。"""
        if not self._started:
            return None
        input_tokens = output_tokens = 0
        for call in self._started.values():
            ratio = self._ratio(call.metadata)
            input_tokens += round(call.estimated_input * ratio)
            output_tokens += round(estimate_text_tokens("".join(call.output)) * ratio)
        return InterruptedUsage(input_tokens=input_tokens, output_tokens=output_tokens)

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        call = self._started.pop(run_id, None)
        started, metadata = (call.started, call.metadata) if call else (time.monotonic(), {})
        generation = response.generations[0][0] if response.generations else None
        if not isinstance(generation, ChatGeneration):
            return
        message = generation.message
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            return
        input_details = usage.get("input_token_details") or {}
        output_details = usage.get("output_token_details") or {}
        requested = version_name(metadata.get("ls_model_name") or "")
        self._calibrate(requested, call, usage["input_tokens"])
        # 命名空间形如 "tools:<子智能体>|model:<本次调用>"，去掉最后一段即调用方所在的智能体
        namespace = metadata.get("langgraph_checkpoint_ns", "").split("|")[:-1]
        self._usage.append(
            UsageReported(
                agent_path=self.agent_path(namespace),
                caller=_caller(metadata),
                requested_model=requested,
                actual_model=version_name(message.response_metadata.get("model_name") or requested),
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_read_tokens=input_details.get("cache_read", 0),
                cache_write_tokens=input_details.get("cache_creation", 0),
                reasoning_tokens=output_details.get("reasoning", 0),
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        )

    def _ratio(self, metadata: dict[str, Any]) -> float:
        model = version_name(metadata.get("ls_model_name") or "")
        return self._calibration.get(model, Calibration()).token_ratio

    def _calibrate(self, model: str, call: _Call | None, input_tokens: int) -> None:
        if call and call.estimated_input:
            self._calibration.setdefault(model, Calibration()).token_ratio = (
                input_tokens / call.estimated_input
            )


def is_compaction(metadata: dict[str, Any]) -> bool:
    """上下文自动压缩（生成摘要）时的模型调用：LangChain 给它打了 lc_source 标记。"""
    return metadata.get("lc_source") == "summarization"


def _is_main_call(metadata: dict[str, Any]) -> bool:
    """主智能体这一层的模型调用（不是子智能体、上下文压缩）。"""
    namespace = metadata.get("langgraph_checkpoint_ns", "").split("|")[:-1]
    return _caller(metadata) == MAIN and not namespace


def _caller(metadata: dict[str, Any]) -> str:
    """调用方：主智能体为 main，子智能体为其名称，上下文自动压缩为 compaction。"""
    if is_compaction(metadata):
        return "compaction"
    return str(metadata.get("lc_agent_name") or MAIN)
