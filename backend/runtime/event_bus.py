"""运行时替换点②：事件总线。v1 用进程内存实现；多进程时换成 PostgreSQL 通知或 Redis 消息流。"""

import asyncio
from collections.abc import AsyncIterator
from functools import partial
from typing import Protocol

from backend.runtime.envelope import EventEnvelope


class EventBus(Protocol):
    """按运行发布事件；订阅者可从任意序号之后开始接收，直到运行关闭。"""

    def has(self, run_id: str) -> bool: ...

    def open(self, run_id: str) -> None: ...

    async def publish(self, run_id: str, event: EventEnvelope) -> None: ...

    async def close(self, run_id: str) -> None: ...

    def subscribe(self, run_id: str, after_seq: int = 0) -> AsyncIterator[EventEnvelope]: ...

    def first_seq(self, run_id: str) -> int | None:
        """总线里这一段（审批后恢复时重新打开，从头算）的第一个序号；还没有事件时为 None。"""
        ...


class InMemoryEventBus:
    """单进程事件总线：每个运行一个事件列表；运行关闭后保留一段时间供断线重连补发。"""

    def __init__(self, *, retain_seconds: float = 60.0) -> None:
        self._events: dict[str, list[EventEnvelope]] = {}
        self._closed: set[str] = set()
        self._changed = asyncio.Condition()
        self._retain_seconds = retain_seconds
        self._forgetting: dict[str, asyncio.TimerHandle] = {}

    def has(self, run_id: str) -> bool:
        return run_id in self._events

    def open(self, run_id: str) -> None:
        """开始推送一个运行。审批后恢复时会重新打开同一运行：清掉上一段留下的关闭状态。"""
        self._events[run_id] = []
        self._closed.discard(run_id)
        if (handle := self._forgetting.pop(run_id, None)) is not None:
            handle.cancel()

    async def publish(self, run_id: str, event: EventEnvelope) -> None:
        async with self._changed:
            self._events[run_id].append(event)
            self._changed.notify_all()

    async def close(self, run_id: str) -> None:
        async with self._changed:
            self._closed.add(run_id)
            self._changed.notify_all()
        self._forgetting[run_id] = asyncio.get_running_loop().call_later(
            self._retain_seconds, self._forget, run_id
        )

    async def subscribe(self, run_id: str, after_seq: int = 0) -> AsyncIterator[EventEnvelope]:
        sent = after_seq
        while True:
            async with self._changed:
                await self._changed.wait_for(partial(self._ready, run_id, sent))
                pending = [e for e in self._events.get(run_id, []) if e.seq > sent]
                finished = run_id in self._closed or run_id not in self._events
            for event in pending:
                yield event
                sent = event.seq
            if finished and not pending:
                return

    def first_seq(self, run_id: str) -> int | None:
        events = self._events.get(run_id)
        return events[0].seq if events else None

    def _ready(self, run_id: str, sent: int) -> bool:
        events = self._events.get(run_id)
        return events is None or run_id in self._closed or (bool(events) and events[-1].seq > sent)

    def _forget(self, run_id: str) -> None:
        self._forgetting.pop(run_id, None)
        self._events.pop(run_id, None)
        self._closed.discard(run_id)
