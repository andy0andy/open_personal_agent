"""运行事件分批写入界面历史（设计文档 10.2 第 4 步）。

运行中每隔一小段时间（默认 200 毫秒）把新事件原样写入一批：进程中途退出时，已推送的内容
仍在界面历史里。运行结束时把这次运行的事件整体替换为合并后的版本（逐字片段合并成整段）。
"""

import asyncio
import logging
from collections.abc import Sequence
from uuid import UUID

from backend.runs.compaction import compact
from backend.runs.repo import RunRepo
from backend.runtime import EventEnvelope

logger = logging.getLogger(__name__)


class EventWriter:
    def __init__(
        self,
        runs: RunRepo,
        run_id: UUID,
        *,
        interval: float = 0.2,
        prior: Sequence[EventEnvelope] = (),
    ) -> None:
        self._runs = runs
        self._run_id = run_id
        self._interval = interval
        # 审批前已存好的事件（已合并过）：原样保留，再合并会让 full_text 的片段重复
        self._prior = list(prior)
        self._pending: list[EventEnvelope] = []
        self._loop: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._loop = asyncio.create_task(self._flush_periodically())

    def add(self, event: EventEnvelope) -> None:
        self._pending.append(event)

    async def finish(self, events: list[EventEnvelope]) -> None:
        """停止定时写入，并用合并后的完整事件替换这次运行已写入的内容。"""
        if self._loop is not None:
            self._loop.cancel()
            # 等定时写入真正停下（它可能正在写一批），再整体替换；
            # 与直接忽略 CancelledError 不同，收尾自己被取消时不会被吞掉
            await asyncio.gather(self._loop, return_exceptions=True)
        await self._runs.replace_events(self._run_id, [*self._prior, *compact(events)])

    async def _flush_periodically(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            batch, self._pending = self._pending, []
            if not batch:
                continue
            try:
                await self._runs.add_events(self._run_id, batch)
            except Exception:  # 后台任务边界：这一批写不进去，结束时的整体替换还会写入
                logger.exception("运行 %s 的事件分批写入失败", self._run_id)
