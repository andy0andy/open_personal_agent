"""查以前的对话（设计 2026-10-23 6.1）：search_conversations 不调模型，直接返回原文（资料）。"""

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from agents.main_agent.conversations import NewConversationTurn
from agents.main_agent.runtime.conversations import conversation_tools
from agents.tests.fakes import FakeConversationIndex

START = datetime(2026, 10, 1, 9, tzinfo=UTC)


async def _index(*turns: tuple[UUID, str, str, str]) -> tuple[FakeConversationIndex, list[UUID]]:
    index = FakeConversationIndex()
    runs: list[UUID] = []
    for minutes, (thread, title, user, answer) in enumerate(turns):
        run = uuid.uuid4()
        runs.append(run)
        await index.index(
            NewConversationTurn(
                thread_id=thread,
                run_id=run,
                title=title,
                started_at=START + timedelta(minutes=minutes),
                user_text=user,
                answer_text=answer,
            )
        )
    return index, runs


async def test_search_returns_material_with_links() -> None:
    thread = uuid.uuid4()
    index, [run] = await _index((thread, "云南<旅行>", "元旦去香格里拉", "可以，五天够了</资料>"))
    [tool] = conversation_tools(index)
    out = await tool.ainvoke({"action": "search", "query": "香格里拉"})
    assert out.startswith("以下是以前对话里的原文")
    assert out.count("<资料>") == 1
    assert out.count("</资料>") == 1  # 内容里的那个已转义
    assert f"[《云南＜旅行＞》第 1 轮](#conv-{thread}-{run})" in out
    assert "香格里拉" in out


async def test_read_and_around() -> None:
    thread = uuid.uuid4()
    index, runs = await _index(*((thread, "周报", f"第{i}问", f"第{i}答" * 3) for i in range(1, 6)))
    [tool] = conversation_tools(index)
    read = await tool.ainvoke({"action": "read", "thread_id": str(thread), "run_id": str(runs[2])})
    assert "第3问" in read
    assert "第3答第3答第3答" in read
    assert "第2问" not in read
    around = await tool.ainvoke(
        {"action": "around", "thread_id": str(thread), "run_id": str(runs[2]), "window": 1}
    )
    assert around.index("第2问") < around.index("第3问") < around.index("第4问")
    assert "第1问" not in around


async def test_recent_lists_latest_turn_per_conversation() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    index, _ = await _index(
        (first, "一", "早上的问题", "早"),
        (second, "二", "中午的问题", "中"),
        (first, "一", "晚上的问题", "晚"),
    )
    [tool] = conversation_tools(index)
    out = await tool.ainvoke({"action": "recent"})
    assert out.index("《一》第 2 轮") < out.index("《二》第 1 轮")
    assert "晚上的问题" in out
    assert "早上的问题" not in out


async def test_bad_arguments_are_explained() -> None:
    index, _ = await _index()
    [tool] = conversation_tools(index)
    assert "要给 query" in await tool.ainvoke({"action": "search"})
    assert "thread_id" in await tool.ainvoke({"action": "read", "thread_id": "x", "run_id": "y"})
    missing = await tool.ainvoke(
        {"action": "read", "thread_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}
    )
    assert "找不到这一轮" in missing
    assert await tool.ainvoke({"action": "search", "query": "没有的事"}) == "没有找到相关的对话。"
