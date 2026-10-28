"""会话索引契约测试（设计 2026-10-23 6.1）：所有 ConversationIndex 实现都必须通过同一套测试。

PostgreSQL 实现与单元测试用的替身都跑；两者都用知识库同一套 jieba 分词。
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from agents.main_agent.conversations import (
    ConversationIndex,
    NewConversationTurn,
    PgConversationIndex,
)
from agents.tests.fakes import FakeConversationIndex
from common.db import Pool

pytestmark = pytest.mark.integration

type Factory = Callable[[], ConversationIndex]
START = datetime(2026, 10, 1, 9, tzinfo=UTC)


@pytest.fixture(params=["pg", "fake"])
def make(request: pytest.FixtureRequest, db: Pool) -> Factory:
    if request.param == "fake":
        return FakeConversationIndex
    return lambda: PgConversationIndex(db)


def _turn(
    thread: UUID, minutes: int, user: str, answer: str, *, title: str = "旅行计划"
) -> NewConversationTurn:
    return NewConversationTurn(
        thread_id=thread,
        run_id=uuid.uuid4(),
        title=title,
        started_at=START + timedelta(minutes=minutes),
        user_text=user,
        answer_text=answer,
    )


async def test_index_and_search_by_words(make: Factory) -> None:
    index = make()
    thread = uuid.uuid4()
    hit = _turn(thread, 0, "元旦想去云南玩五天", "可以考虑大理、丽江和香格里拉，预算五千到一万。")
    await index.index(hit)
    await index.index(_turn(thread, 1, "帮我写个周报", "好的，这是本周的工作总结。"))
    [found] = await index.search("香格里拉")
    assert (found.turn.run_id, found.turn.turn, found.turn.title) == (hit.run_id, 1, "旅行计划")
    assert "香格里拉" in found.snippet
    assert len(found.snippet) <= 130


async def test_search_reports_the_words_it_matched(make: Factory) -> None:
    """接口把命中用的词一并返回，界面据此加粗（积压小问题 B4）：搜"上海天气"命中"上海的天气"。"""
    index = make()
    await index.index(_turn(uuid.uuid4(), 0, "上海的天气怎么样", "明天多云。"))
    [found] = await index.search("上海天气")
    assert {"上海", "天气"} <= set(found.terms)
    assert all(len(term) > 1 for term in found.terms)  # 单字词不加粗：到处都是


async def test_reindex_same_run_overwrites(make: Factory) -> None:
    index = make()
    turn = _turn(uuid.uuid4(), 0, "问天气", "晴")
    await index.index(turn)
    await index.index(turn.model_copy(update={"answer_text": "下雨，记得带伞"}))
    assert await index.search("晴") == []
    [found] = await index.search("带伞")
    assert found.turn.answer_text == "下雨，记得带伞"


async def test_retry_replaces_the_old_run(make: Factory) -> None:
    """ "重试这一轮"后，失败的那一轮不再出现，轮次也不多算（界面上收成一行，D26）。"""
    index = make()
    thread = uuid.uuid4()
    failed = _turn(thread, 0, "整理发票", "（出错）")
    await index.index(failed)
    retried = _turn(thread, 1, "整理发票", "发票已整理好")
    await index.index(retried, replaces=failed.run_id)
    assert await index.search("出错") == []
    [found] = await index.search("发票")
    assert (found.turn.run_id, found.turn.turn) == (retried.run_id, 1)


async def test_retitle_and_delete_thread(make: Factory) -> None:
    index = make()
    thread, other = uuid.uuid4(), uuid.uuid4()
    await index.index(_turn(thread, 0, "咖啡豆怎么选", "看产地和烘焙度"))
    await index.index(_turn(other, 0, "咖啡机推荐", "半自动入门"))
    await index.retitle(thread, "咖啡")
    titles = {hit.turn.thread_id: hit.turn.title for hit in await index.search("咖啡")}
    assert titles[thread] == "咖啡"
    await index.delete_thread(thread)
    assert [hit.turn.thread_id for hit in await index.search("咖啡")] == [other]


async def test_around_and_turn_numbers(make: Factory) -> None:
    index = make()
    thread = uuid.uuid4()
    turns = [_turn(thread, i, f"第{i}问", f"第{i}答") for i in range(5)]
    for turn in reversed(turns):  # 写入顺序与时间先后无关
        await index.index(turn)
    middle = await index.around(thread, turns[2].run_id, window=1)
    assert [t.turn for t in middle] == [2, 3, 4]
    assert [t.run_id for t in middle] == [t.run_id for t in turns[1:4]]
    one = await index.turn(thread, turns[4].run_id)
    assert one is not None
    assert (one.turn, one.user_text) == (5, "第4问")
    assert await index.turn(thread, uuid.uuid4()) is None
    assert await index.around(thread, uuid.uuid4(), window=1) == []


async def test_recent_one_per_thread(make: Factory) -> None:
    index = make()
    first, second = uuid.uuid4(), uuid.uuid4()
    await index.index(_turn(first, 0, "早", "早上好", title="一"))
    await index.index(_turn(first, 5, "晚", "晚上好", title="一"))
    await index.index(_turn(second, 3, "中", "中午好", title="二"))
    recent = await index.recent(limit=10)
    assert [(t.title, t.user_text, t.turn) for t in recent] == [("一", "晚", 2), ("二", "中", 1)]
    assert len(await index.recent(limit=1)) == 1


@pytest.mark.parametrize("query", ["", "   ", "？！。,.", "<资料>"])
async def test_empty_or_punctuation_query_returns_nothing(make: Factory, query: str) -> None:
    index = make()
    await index.index(_turn(uuid.uuid4(), 0, "随便聊聊", "好的"))
    assert await index.search(query) == []


async def test_missing_lists_runs_without_rows(make: Factory) -> None:
    index = make()
    turn = _turn(uuid.uuid4(), 0, "有", "有")
    await index.index(turn)
    absent = uuid.uuid4()
    assert await index.missing([turn.run_id, absent]) == {absent}
    assert await index.missing([]) == set()


async def test_names_glued_to_neighbors_are_found(make: Factory) -> None:
    """分词会把名字和旁边的字粘在一起（"张伟明""叫旺财"）：原文里有就要搜得到（审查 I2）。"""
    index = make()
    thread = uuid.uuid4()
    colleague = _turn(thread, 0, "我同事张伟明天来北京", "好的，记得去接。")
    dog = _turn(thread, 1, "我家小狗叫旺财", "好名字，很喜庆。")
    await index.index(colleague)
    await index.index(dog)
    [found] = await index.search("张伟")
    assert found.turn.run_id == colleague.run_id
    assert "张伟" in found.snippet
    assert [hit.turn.run_id for hit in await index.search("旺财")] == [dog.run_id]


async def test_whole_query_in_the_text_comes_first(make: Factory) -> None:
    """原文里整段出现的，排在只是分词命中的前面（哪怕更早）。"""
    index = make()
    thread = uuid.uuid4()
    exact = _turn(thread, 0, "我想去云南大理住几天", "可以。")
    words_only = _turn(thread, 5, "大理在云南，风景很美", "是的。")
    await index.index(exact)
    await index.index(words_only)
    hits = await index.search("云南大理")
    assert [hit.turn.run_id for hit in hits] == [exact.run_id, words_only.run_id]
