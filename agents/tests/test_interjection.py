"""插话不打断（设计 2026-10-23 6.3）：运行中说的话排在队列里，主智能体下一次调用模型前送达。"""

import tempfile
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.interjections import Interjections
from agents.main_agent.runtime import MainAgent, ToolFinished, UserInterjected
from agents.main_agent.runtime.interjection import INTERJECTION_MARK
from agents.main_agent.runtime.interruption import INTERRUPTED_NOTE
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import (
    FakeGateway,
    FakeMcpClient,
    FakeSandbox,
    ScriptedChatModel,
    call,
    mcp_tool,
)

SHORT = "c_000000e1"
QUEUE = Interjections()


@tool
def demo_slow() -> str:
    """一个要跑一会儿的工具：跑的时候用户插了一句话"""
    QUEUE.put("改成英文")
    return "跑完了"


def _agent(model: ScriptedChatModel) -> MainAgent:
    return MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        mcp=FakeMcpClient([mcp_tool(demo_slow, read_only=True)]),
    )


async def _run(
    agent: MainAgent, run_id: str, message: str, queue: Interjections | None
) -> list[Any]:
    return [
        e
        async for e in agent.run(
            thread_id="t1",
            thread_short_id=SHORT,
            run_id=run_id,
            message=message,
            model="fake",
            interjections=queue,
        )
    ]


def _texts(messages: list[Any]) -> list[str]:
    return [str(m.content) for m in messages if isinstance(m, HumanMessage)]


async def test_interjection_is_delivered_before_next_model_call() -> None:
    QUEUE.take()
    model = ScriptedChatModel(
        responses=[call("demo_slow", {}, "c1"), AIMessage(content="好的，改成英文")]
    )
    events = await _run(_agent(model), "r1", "写一段介绍", QUEUE)
    # 第一次调用时还没有插话；第二次（工具跑完后）收到了
    assert INTERJECTION_MARK + "改成英文" not in _texts(model.received[0])
    assert INTERJECTION_MARK + "改成英文" in _texts(model.received[1])
    kinds = [type(e) for e in events if isinstance(e, ToolFinished | UserInterjected)]
    assert kinds == [ToolFinished, UserInterjected]
    [interjected] = [e for e in events if isinstance(e, UserInterjected)]
    assert (interjected.text, interjected.agent_path) == ("改成英文", ["main"])
    assert QUEUE.pending == 0


async def test_interjection_does_not_trigger_interrupted_note() -> None:
    """插话接在工具结果后面：下一轮开始前补"中断说明"的逻辑不能把它当成被打断的一轮。"""
    QUEUE.take()
    model = ScriptedChatModel(
        responses=[
            call("demo_slow", {}, "c1"),
            AIMessage(content="好的，改成英文"),
            AIMessage(content="你好"),
        ]
    )
    agent = _agent(model)
    await _run(agent, "r1", "写一段介绍", QUEUE)
    await _run(agent, "r2", "你好", None)
    assert all(INTERRUPTED_NOTE not in str(m.content) for m in model.received[-1])


async def test_subagent_does_not_take_interjections() -> None:
    """子智能体在跑时插话不给它：等主智能体下一次调用模型才送达。"""
    QUEUE.take()
    task = {
        "name": "task",
        "args": {"description": "查一下", "subagent_type": "general-purpose"},
        "id": "t1",
        "type": "tool_call",
    }
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[task]),
            call("demo_slow", {}, "c1"),  # 子智能体调用工具，跑的时候用户插话
            AIMessage(content="子智能体查好了"),
            AIMessage(content="好的，改成英文"),
        ]
    )
    await _run(_agent(model), "r1", "帮我查", QUEUE)
    marked = INTERJECTION_MARK + "改成英文"
    assert marked not in _texts(model.received[2])  # 子智能体收到工具结果后的那次调用
    assert marked in _texts(model.received[3])  # 主智能体接着调用模型时收到


def test_queue_closes_and_returns_what_was_not_delivered() -> None:
    queue = Interjections()
    assert queue.put("一")
    assert queue.put("二")
    assert queue.take() == ["一", "二"]
    assert queue.put("三")
    assert queue.close() == ["三"]
    assert queue.put("四") is False
    assert queue.close() == []
