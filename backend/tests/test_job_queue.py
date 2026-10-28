"""后台任务队列（运行时替换点⑤，设计文档 10.9）：任务存进 jobs 表，进程内的后台循环逐个处理。

契约：按类型交给处理函数；失败按间隔重试，到上限记为失败；进程中途退出时正在处理的任务下次启动后重做。
"""

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest

from backend.runtime import JobQueue, TableJobQueue
from common.db import Pool

pytestmark = pytest.mark.integration

type Factory = Callable[..., JobQueue]


@pytest.fixture(params=["table"])
def make(request: pytest.FixtureRequest, db: Pool) -> Factory:
    def factory(**options: Any) -> JobQueue:
        return TableJobQueue(db, **{"poll_interval": 10.0, "retry_delay": 0.0, **options})

    return factory


async def _status(db: Pool, job_id: object) -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT status, attempts, last_error FROM jobs WHERE id = %s", (job_id,)
        )
        row = await cur.fetchone()
    assert row is not None
    return dict(row)


async def _until(condition: Callable[[], Any]) -> None:
    for _ in range(150):  # 最多等 3 秒
        if await condition():
            return
        await asyncio.sleep(0.02)  # 允许等待：有上限的轮询
    raise AssertionError("3 秒内没有等到预期的状态")


async def test_handles_jobs_by_kind_right_after_enqueue(make: Factory, db: Pool) -> None:
    """新任务立即唤醒后台循环，不用等下一次轮询（轮询间隔设成了 10 秒）。"""
    seen: list[dict[str, Any]] = []

    async def note(payload: dict[str, Any]) -> None:
        seen.append(payload)

    queue = make()
    await queue.start({"note": note})
    try:
        job = await queue.enqueue("note", {"run_id": "r1"})
        await _until(lambda: _done(db, job))
    finally:
        await queue.stop()
    assert seen == [{"run_id": "r1"}]


async def _done(db: Pool, job_id: object) -> bool:
    return str((await _status(db, job_id))["status"]) == "done"


async def test_failures_are_retried_then_recorded(make: Factory, db: Pool) -> None:
    calls = 0

    async def flaky(payload: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError(f"第 {calls} 次失败")

    queue = make(max_attempts=3)
    await queue.start({"flaky": flaky})
    try:
        job = await queue.enqueue("flaky", {})

        async def failed() -> bool:
            return str((await _status(db, job))["status"]) == "failed"

        await _until(failed)
    finally:
        await queue.stop()
    assert await _status(db, job) == {
        "status": "failed",
        "attempts": 3,
        "last_error": "第 3 次失败",
    }


async def test_kinds_without_a_handler_are_left_for_other_queues(make: Factory, db: Pool) -> None:
    """几条队列共用 jobs 表、各管各的种类：自己不处理的种类不领取，留给别的队列。"""

    async def note(payload: dict[str, Any]) -> None:
        pass

    queue = make(poll_interval=0.05)
    await queue.start({"note": note})
    try:
        other = await queue.enqueue("other", {})
        mine = await queue.enqueue("note", {})
        await _until(lambda: _done(db, mine))
        await asyncio.sleep(0.2)  # 允许等待：断言几个领取周期里都没领它，只能等够时长
    finally:
        await queue.stop()
    assert (await _status(db, other)) == {"status": "queued", "attempts": 0, "last_error": None}


async def test_lanes_do_not_block_each_other(make: Factory, db: Pool) -> None:
    """一条队列在处理很慢的任务（如几分钟的文档入库）时，另一条照常处理（如会话标题）。"""
    release = asyncio.Event()

    async def slow(payload: dict[str, Any]) -> None:
        await asyncio.wait_for(release.wait(), 3)

    async def quick(payload: dict[str, Any]) -> None:
        pass

    documents, followups = make(), make()
    await documents.start({"slow": slow})
    await followups.start({"quick": quick})
    try:
        long_job = await documents.enqueue("slow", {})
        short_job = await followups.enqueue("quick", {})
        await _until(lambda: _done(db, short_job))
        assert str((await _status(db, long_job))["status"]) == "running"
        release.set()
        await _until(lambda: _done(db, long_job))
    finally:
        await documents.stop()
        await followups.stop()


async def test_start_requeues_only_its_own_kinds(make: Factory, db: Pool) -> None:
    """启动时只把自己那几种"处理中"的任务放回队列：另一条队列正在处理的不动。"""
    ids = {}
    async with db.connection() as conn:
        for kind in ("mine", "theirs"):
            cur = await conn.execute(
                "INSERT INTO jobs (id, kind, status) VALUES (gen_random_uuid(), %s, 'running') "
                "RETURNING id",
                (kind,),
            )
            row = await cur.fetchone()
            assert row is not None
            ids[kind] = row["id"]

    async def handle(payload: dict[str, Any]) -> None:
        pass

    queue = make()
    await queue.start({"mine": handle})
    try:
        await _until(lambda: _done(db, ids["mine"]))
    finally:
        await queue.stop()
    assert str((await _status(db, ids["theirs"]))["status"]) == "running"


async def test_interrupted_jobs_run_again_after_restart(make: Factory, db: Pool) -> None:
    """服务停止时正在处理的任务不算失败：下次启动重新处理（如服务重启时正在提取记忆）。"""
    started = asyncio.Event()
    finished: list[str] = []

    async def slow(payload: dict[str, Any]) -> None:
        started.set()
        await asyncio.sleep(30)  # 允许等待：替身模拟一直做不完

    async def quick(payload: dict[str, Any]) -> None:
        finished.append("ok")

    first = make()
    await first.start({"work": slow})
    job = await first.enqueue("work", {})
    await asyncio.wait_for(started.wait(), 3)
    await first.stop()
    assert (await _status(db, job))["status"] == "running"

    second = make()
    await second.start({"work": quick})
    try:
        await _until(lambda: _done(db, job))
    finally:
        await second.stop()
    assert finished == ["ok"]


class _FlakyFinishQueue(TableJobQueue):
    """第一次写任务结果时数据库出错（如数据库容器重启）。"""

    failed = False

    async def _finish(self, job_id: UUID, status: str, error: str | None) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("数据库暂时不可用")
        await super()._finish(job_id, status, error)


async def test_database_error_does_not_stop_the_loop(db: Pool) -> None:
    """写结果时数据库出了一次错：后台循环不退出，后面的任务照常处理；
    出错的那个保持"处理中"，下次启动时重做。"""
    seen: list[int] = []

    async def note(payload: dict[str, Any]) -> None:
        seen.append(payload["n"])

    queue = _FlakyFinishQueue(db, poll_interval=0.05, retry_delay=0.0)
    await queue.start({"note": note})
    try:
        first = await queue.enqueue("note", {"n": 1})
        second = await queue.enqueue("note", {"n": 2})
        await _until(lambda: _done(db, second))
    finally:
        await queue.stop()
    assert seen == [1, 2]
    assert str((await _status(db, first))["status"]) == "running"
