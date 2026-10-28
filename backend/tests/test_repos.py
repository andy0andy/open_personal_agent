import uuid

import pytest

from agents.main_agent.runtime import MessageDelta, RunFinished, UsageTotals
from backend.runs import RunRepo
from backend.runtime import EventEnvelope
from backend.threads import ThreadRepo
from common.db import Pool
from common.errors import ConflictError, NotFoundError

pytestmark = pytest.mark.integration


async def test_thread_create_list_get_touch(db: Pool) -> None:
    threads = ThreadRepo(db)
    created = await threads.create(model="m")
    assert created.title == ""

    await threads.touch(created.id, first_message="第一条消息" * 10)
    await threads.touch(created.id, first_message="第二条消息")

    fetched = await threads.get(created.id)
    assert fetched.title == ("第一条消息" * 10)[:30]
    assert [t.id for t in await threads.list_active()] == [created.id]


async def test_get_missing_thread_raises(db: Pool) -> None:
    with pytest.raises(NotFoundError):
        await ThreadRepo(db).get(uuid.uuid4())


async def test_only_one_active_run_per_thread(db: Pool) -> None:
    thread = await ThreadRepo(db).create(model="m")
    runs = RunRepo(db)
    first = await runs.create(thread_id=thread.id, model="m", message="a")
    with pytest.raises(ConflictError):
        await runs.create(thread_id=thread.id, model="m", message="b")

    await runs.finish(first.id, status="completed", error=None)
    second = await runs.create(thread_id=thread.id, model="m", message="b")
    assert second.status == "running"


async def test_events_and_history(db: Pool) -> None:
    thread = await ThreadRepo(db).create(model="m")
    runs = RunRepo(db)
    run = await runs.create(thread_id=thread.id, model="m", message="hi")
    events = [
        EventEnvelope.wrap(MessageDelta(message_id="m1", text="好"), seq=1, run_id=str(run.id)),
        EventEnvelope.wrap(RunFinished(status="completed"), seq=2, run_id=str(run.id)),
    ]
    await runs.add_events(run.id, events)
    await runs.finish(run.id, status="completed", error=None)

    assert [e.seq for e in await runs.events(run.id, after_seq=1)] == [2]
    [history] = await runs.history(thread.id)
    assert (history.message, history.status) == ("hi", "completed")
    assert [e.type for e in history.events] == ["message.delta", "run.finished"]


async def test_fail_unfinished(db: Pool) -> None:
    thread = await ThreadRepo(db).create(model="m")
    runs = RunRepo(db)
    run = await runs.create(thread_id=thread.id, model="m", message="hi")

    assert await runs.fail_unfinished() == [run.id]  # 启动时给它们登记写索引（B7）
    stored = await runs.get(run.id)
    assert (stored.status, stored.error) == ("failed", "服务重启中断")


async def test_replace_events_swaps_whole_run(db: Pool) -> None:
    thread = await ThreadRepo(db).create(model="m")
    runs = RunRepo(db)
    run = await runs.create(thread_id=thread.id, model="m", message="hi")
    raw = [
        EventEnvelope.wrap(MessageDelta(message_id="m1", text=t), seq=i, run_id=str(run.id))
        for i, t in enumerate("你好", start=1)
    ]
    await runs.add_events(run.id, raw)
    merged = raw[1].model_copy(update={"data": {"message_id": "m1", "text": "你好"}})

    await runs.replace_events(run.id, [merged])

    assert [(e.seq, e.data["text"]) for e in await runs.events(run.id)] == [(2, "你好")]


async def test_new_thread_on_top_and_activity_keeps_custom_order(db: Pool) -> None:
    threads = ThreadRepo(db)
    first = await threads.create(model="m")
    second = await threads.create(model="m")
    assert [t.id for t in await threads.list_active()] == [second.id, first.id]

    await threads.touch(first.id, first_message="再聊一句")  # 有新对话也不改变位置
    assert [t.id for t in await threads.list_active()] == [second.id, first.id]

    await threads.reorder([first.id, second.id])
    third = await threads.create(model="m")
    assert [t.id for t in await threads.list_active()] == [third.id, first.id, second.id]


async def test_reorder_ignores_unknown_ids(db: Pool) -> None:
    """排序里有不存在的会话（如另一个标签页刚删掉的）：忽略它，其余照常排序。"""
    threads = ThreadRepo(db)
    first = await threads.create(model="m")
    second = await threads.create(model="m")

    await threads.reorder([uuid.uuid4(), first.id, second.id])

    assert [t.id for t in await threads.list_active()] == [first.id, second.id]


async def test_rename_thread(db: Pool) -> None:
    threads = ThreadRepo(db)
    created = await threads.create(model="m")
    renamed = await threads.update(created.id, title="西游记读后感")
    assert renamed.title == "西游记读后感"
    await threads.touch(created.id, first_message="首条消息")  # 已有标题时不被首条消息覆盖
    assert (await threads.get(created.id)).title == "西游记读后感"
    with pytest.raises(NotFoundError):
        await threads.update(uuid.uuid4(), title="不存在")


async def test_delete_thread_removes_runs_and_history(db: Pool) -> None:
    threads, runs = ThreadRepo(db), RunRepo(db)
    thread = await threads.create(model="m")
    run = await runs.create(thread_id=thread.id, model="m", message="hi")
    event = EventEnvelope.wrap(MessageDelta(message_id="m1", text="你"), seq=1, run_id=str(run.id))
    await runs.add_events(run.id, [event])
    assert await runs.has_active(thread.id) is True  # 新建的运行处于进行中
    await runs.finish(run.id, status="completed", error=None)
    assert await runs.has_active(thread.id) is False

    await threads.delete(thread.id)

    with pytest.raises(NotFoundError):
        await threads.get(thread.id)
    with pytest.raises(NotFoundError):
        await runs.get(run.id)
    assert await runs.events(run.id) == []
    with pytest.raises(NotFoundError):
        await threads.delete(thread.id)


async def test_list_active_reports_latest_run_activity(db: Pool) -> None:
    """会话列表的状态点（设计 2026-10-22 第 5 节）：只看每个会话最近一次运行。"""
    threads, runs = ThreadRepo(db), RunRepo(db)
    usage = UsageTotals()

    running = await threads.create(model="m")
    await runs.create(thread_id=running.id, model="m", message="a")

    waiting = await threads.create(model="m")
    paused = await runs.create(thread_id=waiting.id, model="m", message="a")
    await runs.pause(paused.id, usage=usage)

    failed = await threads.create(model="m")
    broken = await runs.create(thread_id=failed.id, model="m", message="a")
    await runs.finish(broken.id, status="failed", error="出错了")

    completed = await threads.create(model="m")
    done = await runs.create(thread_id=completed.id, model="m", message="a")
    await runs.finish(done.id, status="completed", error=None)

    recovered = await threads.create(model="m")
    earlier = await runs.create(thread_id=recovered.id, model="m", message="a")
    await runs.finish(earlier.id, status="failed", error="出错了")
    later = await runs.create(thread_id=recovered.id, model="m", message="b")
    await runs.finish(later.id, status="completed", error=None)

    idle = await threads.create(model="m")

    seen = await threads.create(model="m")
    viewed = await runs.create(thread_id=seen.id, model="m", message="a")
    await runs.finish(viewed.id, status="completed", error=None)
    await threads.mark_viewed(seen.id)

    activity = {thread.id: thread.activity for thread in await threads.list_active()}
    # 顺利结束、之后还没看过的亮"有新回答"（设计 2026-10-23 6.5）
    assert activity == {
        running.id: "running",
        waiting.id: "waiting",
        failed.id: "failed",
        completed.id: "new",
        recovered.id: "new",
        idle.id: None,
        seen.id: None,
    }
    # 其他接口不算状态
    assert (await threads.get(running.id)).activity is None


async def test_latest_run_and_retry_of_round_trip(db: Pool) -> None:
    thread = await ThreadRepo(db).create(model="m")
    runs = RunRepo(db)
    assert await runs.latest(thread.id) is None
    first = await runs.create(thread_id=thread.id, model="m", message="a")
    await runs.finish(first.id, status="failed", error="boom")
    retried = await runs.create(thread_id=thread.id, model="m2", message="a", retry_of=first.id)
    assert retried.retry_of == first.id
    assert (await runs.get(retried.id)).retry_of == first.id
    latest = await runs.latest(thread.id)
    assert latest is not None
    assert latest.id == retried.id
    [history_first, history_retried] = await runs.history(thread.id)
    assert (history_first.retry_of, history_retried.retry_of) == (None, first.id)


async def test_archived_threads_are_listed_apart(db: Pool) -> None:
    """归档（设计 2026-10-23 6.5）：不在主列表里，在归档列表里；取消归档回到主列表。"""
    threads = ThreadRepo(db)
    kept = await threads.create(model="m", title="留着")
    old = await threads.create(model="m", title="旧的")
    updated = await threads.update(old.id, archived=True)
    assert updated.archived is True
    assert [t.id for t in await threads.list_active()] == [kept.id]
    assert [t.id for t in await threads.list_archived()] == [old.id]
    await threads.update(old.id, archived=False)
    assert {t.id for t in await threads.list_active()} == {kept.id, old.id}
    assert await threads.list_archived() == []
