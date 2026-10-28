import dataclasses
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agents.main_agent.models import (
    EmbeddingUsage,
    estimate_input_tokens,
    estimate_text_tokens,
)
from agents.main_agent.runtime import InterruptedUsage, UsageReported, UsageTotals
from agents.main_agent.runtime.tracker import Calibration, RunTracker


def _result(usage: dict[str, Any] | None, response_metadata: dict[str, Any]) -> LLMResult:
    message = AIMessage(content="x", usage_metadata=usage, response_metadata=response_metadata)
    return LLMResult(generations=[[ChatGeneration(message=message)]])


USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "total_tokens": 120,
    "input_token_details": {"cache_read": 30, "cache_creation": 5},
    "output_token_details": {"reasoning": 7},
}


async def _call(tracker: RunTracker, metadata: dict[str, Any], result: LLMResult) -> None:
    run_id = uuid4()
    await tracker.on_chat_model_start({}, [[]], run_id=run_id, metadata=metadata)
    await tracker.on_llm_end(result, run_id=run_id)


async def test_model_call_produces_usage_event() -> None:
    tracker = RunTracker()
    metadata = {
        "ls_model_name": "litellm_proxy/claude-opus-4-6",
        "langgraph_checkpoint_ns": "model:1",
    }
    response_metadata = {"model_name": "litellm_proxy/claude-opus-4-6", "response_cost": 0.05}
    await _call(tracker, metadata, _result(USAGE, response_metadata))

    [usage] = tracker.drain_usage()
    assert usage.model_dump(exclude={"duration_ms"}) == UsageReported(
        caller="main",
        requested_model="claude-opus-4-6",
        actual_model="claude-opus-4-6",
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=30,
        cache_write_tokens=5,
        reasoning_tokens=7,
    ).model_dump(exclude={"duration_ms"})
    assert tracker.drain_usage() == []  # 取走后清空


async def test_subagent_call_is_attributed_to_its_task_call() -> None:
    tracker = RunTracker()
    # 工具开始回调同时给出调用 ID 与子智能体将使用的命名空间
    await tracker.on_tool_start(
        {"name": "task"},
        "",
        run_id=uuid4(),
        metadata={"langgraph_checkpoint_ns": "tools:ns-a"},
        tool_call_id="c1",
    )
    metadata = {
        "lc_agent_name": "general-purpose",
        "ls_model_name": "m",
        "langgraph_checkpoint_ns": "tools:ns-a|model:2",
    }
    await _call(tracker, metadata, _result(USAGE, {}))

    [usage] = tracker.drain_usage()
    assert (usage.caller, usage.agent_path) == ("general-purpose", ["main", "c1"])
    assert tracker.agent_path(("tools:ns-a",)) == ["main", "c1"]


async def test_compaction_call_is_labeled() -> None:
    tracker = RunTracker()
    await _call(tracker, {"lc_source": "summarization", "ls_model_name": "m"}, _result(USAGE, {}))
    assert tracker.drain_usage()[0].caller == "compaction"


async def test_call_without_usage_is_skipped() -> None:
    tracker = RunTracker()
    await _call(tracker, {}, _result(None, {}))
    assert tracker.drain_usage() == []


async def test_interrupted_call_is_estimated_with_calibration() -> None:
    calibration: dict[str, Calibration] = {}
    tracker = RunTracker(calibration=calibration)
    messages: list[BaseMessage] = [HumanMessage("写一篇长文")]
    metadata = {"ls_model_name": "litellm_proxy/m"}
    raw_input = estimate_input_tokens(messages)

    # 一次完整的调用：网关报的实际输入是粗略估算的 2 倍，记下校准系数
    first = uuid4()
    await tracker.on_chat_model_start({}, [messages], run_id=first, metadata=metadata)
    await tracker.on_llm_end(_result({**USAGE, "input_tokens": raw_input * 2}, {}), run_id=first)
    assert calibration["m"].token_ratio == 2.0
    assert tracker.interrupted_usage() is None  # 已结束的调用不算被中断

    # 下一次调用输出到一半被中断：按校准系数估算 token
    second = uuid4()
    await tracker.on_chat_model_start({}, [messages], run_id=second, metadata=metadata)
    await tracker.on_llm_new_token("你好", run_id=second)
    estimate = tracker.interrupted_usage()

    output = round(estimate_text_tokens("你好") * 2)
    assert estimate is not None
    assert (estimate.input_tokens, estimate.output_tokens) == (raw_input * 2, output)


async def test_estimate_failure_is_logged_once_per_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """估算失败（如遇到不认识的消息格式）只提示一次，不在每次模型调用时都刷一遍错误堆栈。"""

    def broken(*args: object) -> int:
        raise ValueError("不认识的内容")

    monkeypatch.setattr("agents.main_agent.runtime.tracker.estimate_input_tokens", broken)
    tracker = RunTracker()
    for _ in range(3):
        await tracker.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=uuid4(), metadata={})

    assert [r.levelname for r in caplog.records] == ["WARNING"]


def test_usage_has_no_cost() -> None:
    """后台不再算费用（设计 2026-10-19 4.11）：用量只有输入、输出两个数（另记缓存与思考的明细）。"""
    for model in (UsageReported, UsageTotals, InterruptedUsage):
        assert "cost" not in model.model_fields
    assert "cost" not in {field.name for field in dataclasses.fields(EmbeddingUsage)}


async def test_tracker_ignores_gateway_cost() -> None:
    """网关算出的费用不读；输入、输出照网关报的 token。"""
    tracker = RunTracker()
    metadata = {"ls_model_name": "litellm_proxy/m"}
    await _call(tracker, metadata, _result(USAGE, {"response_cost": 0.05}))
    [usage] = tracker.drain_usage()
    assert (usage.input_tokens, usage.output_tokens) == (100, 20)
    assert "cost" not in usage.model_dump()


async def test_interrupted_estimate_has_tokens_only() -> None:
    tracker = RunTracker()
    run_id = uuid4()
    await tracker.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=run_id, metadata={})
    estimate = tracker.interrupted_usage()
    assert estimate is not None
    assert set(estimate.model_dump()) == {"input_tokens", "output_tokens"}


# ---- 上下文占用分段（设计 2026-10-23 4.7）：主智能体每次调用模型前记一条 ----


async def _start(tracker: RunTracker, metadata: dict[str, Any]) -> None:
    messages: list[BaseMessage] = [HumanMessage("你好")]
    await tracker.on_chat_model_start({}, [messages], run_id=uuid4(), metadata=metadata)


async def test_main_model_call_reports_context_usage() -> None:
    tracker = RunTracker(context_limit=200_000)
    await _start(tracker, {"ls_model_name": "m", "langgraph_checkpoint_ns": "model:1"})
    [usage] = tracker.drain_context()
    assert usage.total > 0
    assert usage.max_input_tokens == 200_000
    assert tracker.drain_context() == []  # 取走后清空


async def test_subagent_and_compaction_calls_report_no_context() -> None:
    tracker = RunTracker(context_limit=200_000)
    await _start(
        tracker,
        {"lc_agent_name": "general-purpose", "langgraph_checkpoint_ns": "tools:a|model:2"},
    )
    await _start(tracker, {"lc_source": "summarization", "langgraph_checkpoint_ns": "model:3"})
    await _start(tracker, {"lc_agent_name": "memory_extraction"})
    assert tracker.drain_context() == []


async def test_context_failure_keeps_the_interrupted_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """分段算出错只是这次不显示分段：被中断时的估算照常（审查 M6）。"""

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("分段算不出来")

    monkeypatch.setattr("agents.main_agent.runtime.tracker.context_usage", broken)
    tracker = RunTracker(context_limit=200_000)
    await _start(tracker, {"ls_model_name": "m", "langgraph_checkpoint_ns": "model:1"})
    assert tracker.drain_context() == []
    estimate = tracker.interrupted_usage()
    assert estimate is not None
    assert estimate.input_tokens > 0
