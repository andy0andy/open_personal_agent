import asyncio
from uuid import UUID

import pytest

from agents.main_agent.runtime import MessageDelta
from backend.runs import RunRepo
from backend.runs.writer import EventWriter
from backend.runtime import EventEnvelope
from backend.threads import ThreadRepo
from common.db import Pool

pytestmark = pytest.mark.integration


class _SlowFlushRunRepo(RunRepo):
    """模拟数据库驱动：正在写一批时被取消，还要再过一会儿才真正停下。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.writing = asyncio.Event()

    async def add_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        self.writing.set()
        try:
            await asyncio.sleep(0.3)  # 允许等待：替身模拟写一批要一会儿
        except asyncio.CancelledError:
            await asyncio.sleep(0.1)  # 允许等待：替身模拟被取消后还要过一会儿才停下
            raise
        await super().add_events(run_id, events)


async def test_finish_does_not_swallow_its_own_cancellation(db: Pool) -> None:
    thread = await ThreadRepo(db).create(model="m")
    runs = _SlowFlushRunRepo(db)
    run = await runs.create(thread_id=thread.id, model="m", message="hi")
    event = EventEnvelope.wrap(MessageDelta(message_id="m1", text="你"), seq=1, run_id="r")
    writer = EventWriter(runs, run.id, interval=0.01)
    writer.start()
    writer.add(event)
    await asyncio.wait_for(runs.writing.wait(), timeout=5)  # 定时写入正在写这一批

    finishing = asyncio.create_task(writer.finish([event]))
    await asyncio.sleep(0)  # 让收尾先开始
    finishing.cancel()

    # 收尾自己被取消时要照常抛出，不能当作"定时写入已停下"继续去整体替换
    with pytest.raises(asyncio.CancelledError):
        await finishing


async def test_finish_keeps_prior_events_as_they_are(db: Pool) -> None:
    """恢复后的一段：之前已合并过的事件原样保留，新片段单独合并。

    再合并一次会让带 full_text 的片段重复。
    """
    thread = await ThreadRepo(db).create(model="m")
    runs = RunRepo(db)
    run = await runs.create(thread_id=thread.id, model="m", message="hi")
    merged = EventEnvelope.wrap(MessageDelta(message_id="m1", text="你好"), seq=2, run_id="r")
    merged = merged.model_copy(update={"data": {**merged.data, "full_text": True}})
    new = [
        EventEnvelope.wrap(MessageDelta(message_id="m2", text=text), seq=seq, run_id="r")
        for seq, text in ((3, "再"), (4, "见"))
    ]
    await runs.add_events(run.id, [merged])
    writer = EventWriter(runs, run.id, interval=0.01, prior=[merged])
    await writer.finish(new)
    stored = await runs.events(run.id)
    assert [(e.seq, e.data["text"]) for e in stored] == [(2, "你好"), (4, "再见")]
