""" "重试这一轮"在真实的 Postgres 对话存档上分叉（D26；审查 M12：出错代价最高的一处）。"""

import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.main_agent.runtime import MainAgent, RunFinished
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FailingAtChatModel, FakeGateway, FakeSandbox
from common.db import Pool

pytestmark = pytest.mark.integration

SHORT = "c_000000f1"


async def _turn(
    agent: MainAgent, thread_id: str, message: str, retry_of: str | None = None
) -> tuple[str, str]:
    run_id = str(uuid.uuid4())
    events = [
        e
        async for e in agent.run(
            thread_id=thread_id,
            thread_short_id=SHORT,
            run_id=run_id,
            message=message,
            model="fake",
            retry_of=retry_of,
        )
    ]
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    return run_id, finished.status


async def _archive(agent: MainAgent, thread_id: str) -> list[tuple[str, Any]]:
    graph = agent._graph_for("fake", "ask")
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    return [(m.type, m.content) for m in state.values["messages"]]


async def _agent(db: Pool) -> MainAgent:
    checkpointer = AsyncPostgresSaver(db)
    await checkpointer.setup()
    model = FailingAtChatModel(fail_at=1, responses=[AIMessage("回答1"), AIMessage("回答2")])
    return MainAgent(
        gateway=FakeGateway(model),
        checkpointer=checkpointer,
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
    )


async def test_retry_forks_from_before_the_failed_run_on_postgres(db: Pool) -> None:
    agent, thread = await _agent(db), str(uuid.uuid4())
    assert (await _turn(agent, thread, "问题1"))[1] == "completed"
    failed, status = await _turn(agent, thread, "问题2")
    assert status == "failed"
    assert (await _turn(agent, thread, "问题2", retry_of=failed))[1] == "completed"
    assert await _archive(agent, thread) == [
        ("human", "问题1"),
        ("ai", "回答1"),
        ("human", "问题2"),
        ("ai", "回答2"),
    ]


async def test_resending_without_fork_keeps_the_failed_round(db: Pool) -> None:
    """对照：不分叉、直接再发一次时，存档里留着失败的那一轮（上面那条测试分得清两者）。"""
    agent, thread = await _agent(db), str(uuid.uuid4())
    await _turn(agent, thread, "问题1")
    await _turn(agent, thread, "问题2")
    await _turn(agent, thread, "问题2")
    humans = [content for kind, content in await _archive(agent, thread) if kind == "human"]
    assert humans == ["问题1", "问题2", "问题2"]
