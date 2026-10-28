import asyncio

from agents.main_agent.runtime import MessageDelta, RunFinished
from agents.tests.waiting import until
from backend.runtime import EventEnvelope, InMemoryEventBus


def _env(seq: int, text: str = "x") -> EventEnvelope:
    return EventEnvelope.wrap(MessageDelta(message_id="m", text=text), seq=seq, run_id="r1")


async def _collect(bus: InMemoryEventBus, after: int = 0) -> list[int]:
    return [event.seq async for event in bus.subscribe("r1", after)]


async def test_subscriber_gets_past_and_future_events_until_close() -> None:
    bus = InMemoryEventBus()
    bus.open("r1")
    await bus.publish("r1", _env(1))
    subscriber = asyncio.create_task(_collect(bus))
    await asyncio.sleep(0)
    await bus.publish("r1", _env(2))
    await bus.close("r1")
    assert await asyncio.wait_for(subscriber, timeout=1) == [1, 2]


async def test_subscribe_after_seq_skips_seen_events() -> None:
    bus = InMemoryEventBus()
    bus.open("r1")
    for seq in (1, 2, 3):
        await bus.publish("r1", _env(seq))
    await bus.close("r1")
    assert await _collect(bus, after=2) == [3]


async def test_closed_run_is_forgotten_after_retention() -> None:
    bus = InMemoryEventBus(retain_seconds=0.01)
    bus.open("r1")
    await bus.close("r1")
    await until(lambda: not bus.has("r1"), what="过了保留时间忘掉这次运行")


def test_wrap_moves_type_and_path_out_of_data() -> None:
    envelope = EventEnvelope.wrap(RunFinished(status="completed"), seq=7, run_id="r1")
    assert (envelope.type, envelope.agent_path, envelope.seq) == ("run.finished", ["main"], 7)
    assert envelope.data == {
        "status": "completed",
        "error": None,
        "error_kind": None,
        "retryable": False,
        "usage": None,
        "interrupted_usage": None,
        "undelivered": [],  # 没送达的插话（设计 2026-10-23 6.3）
        "next_run_id": None,
    }


async def test_reopened_run_streams_new_events_and_is_kept() -> None:
    """审批后恢复：同一运行关闭后重新打开，新事件照常推送，也不会被之前安排的"过一会儿忘掉"删掉。"""
    bus = InMemoryEventBus(retain_seconds=0.05)
    bus.open("r1")
    await bus.publish("r1", _env(4))
    await bus.close("r1")
    bus.open("r1")
    subscriber = asyncio.create_task(_collect(bus, after=4))
    await asyncio.sleep(0.1)  # 允许等待：断言超过保留时间后仍在，只能等够时长
    assert bus.has("r1")
    await bus.publish("r1", _env(5))
    await bus.close("r1")
    assert await asyncio.wait_for(subscriber, timeout=1) == [5]


async def test_first_seq_is_where_this_segment_starts() -> None:
    """总线里这一段的第一个序号（审批后恢复时重新打开，从头算）：拼接库里的历史用它。"""
    bus = InMemoryEventBus()
    bus.open("r1")
    assert bus.first_seq("r1") is None
    await bus.publish("r1", _env(1))
    await bus.publish("r1", _env(2))
    assert bus.first_seq("r1") == 1
    bus.open("r1")  # 审批后恢复
    assert bus.first_seq("r1") is None
    await bus.publish("r1", _env(5))
    assert bus.first_seq("r1") == 5
    assert bus.first_seq("unknown") is None
