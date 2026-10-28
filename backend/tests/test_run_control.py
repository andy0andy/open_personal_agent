"""运行控制的契约测试：每个实现都要通过同一套测试。"""

import asyncio

import pytest

from backend.runtime import InProcessRunControl, RunControl


async def _wait_forever() -> None:
    await asyncio.Event().wait()


@pytest.fixture(params=[InProcessRunControl])
def control(request: pytest.FixtureRequest) -> RunControl:
    implementation: type[RunControl] = request.param
    return implementation()


async def test_cancel_running_task(control: RunControl) -> None:
    task = asyncio.create_task(_wait_forever())
    control.track("r1", task)

    assert control.cancel("r1") is True
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancel_unknown_or_finished_run_returns_false(control: RunControl) -> None:
    task = asyncio.create_task(asyncio.sleep(0))
    control.track("r1", task)
    await task

    assert control.cancel("r1") is False
    assert control.cancel("missing") is False


async def test_cancel_all_waits_for_cleanup(control: RunControl) -> None:
    cleaned: list[str] = []

    async def run() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.01)  # 允许等待：模拟收尾时还要写数据库
            cleaned.append("done")

    control.track("r1", asyncio.create_task(run()))
    await asyncio.sleep(0)
    await control.cancel_all()

    assert cleaned == ["done"]


async def test_cancel_is_idempotent(control: RunControl) -> None:
    task = asyncio.create_task(_wait_forever())
    control.track("r1", task)

    assert control.cancel("r1") is True
    assert control.cancel("r1") is True  # 连点停止：已在取消中，不再重复打断它的收尾
    assert task.cancelling() == 1
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancel_all_does_not_interrupt_a_run_already_stopping(control: RunControl) -> None:
    """用户刚点了停止、运行正在收尾（把已输出的部分写进对话存档）时服务停止：不能再打断收尾。"""
    cleaned: list[str] = []

    async def run() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.01)  # 允许等待：模拟收尾时写对话存档
            cleaned.append("done")
            raise

    task = asyncio.create_task(run())
    control.track("r1", task)
    await asyncio.sleep(0)
    control.cancel("r1")
    await asyncio.sleep(0)  # 让它进入收尾

    await control.cancel_all()

    assert cleaned == ["done"]
    assert task.cancelling() == 1


async def test_old_task_finishing_does_not_untrack_the_new_one(control: RunControl) -> None:
    """审批后恢复：暂停那一段的任务晚一点结束，不能把恢复后的新任务也注销掉（否则停不下来）。"""
    release = asyncio.Event()

    async def old_segment() -> None:
        await release.wait()

    old = asyncio.create_task(old_segment())
    control.track("r1", old)
    new = asyncio.create_task(_wait_forever())
    control.track("r1", new)
    release.set()
    await old
    assert control.cancel("r1") is True
    with pytest.raises(asyncio.CancelledError):
        await new
