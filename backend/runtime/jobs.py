"""后台任务队列（运行时替换点⑤，设计文档 10.9）：记忆提取、标题生成等运行结束后才做的事。

v1：任务存进 jobs 表，本进程里一个后台循环逐个处理（同一时间只处理一个）；
以后多进程时换成独立工作进程从表里抢任务，接口不变。

几条队列可以共用 jobs 表：每条只领取、只在启动时放回自己有处理函数的那几种任务。
文档入库单独一条，几分钟的大文档不会挡住会话标题、记忆提取。
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol
from uuid import UUID

from psycopg.types.json import Jsonb

from common.db import Pool
from common.ids import new_id

logger = logging.getLogger(__name__)

type JobHandler = Callable[[dict[str, Any]], Awaitable[None]]


class JobQueue(Protocol):
    async def enqueue(self, kind: str, payload: dict[str, Any]) -> UUID:
        """登记一个任务（立即返回），由后台按 kind 交给对应的处理函数。"""
        ...

    async def start(self, handlers: Mapping[str, JobHandler]) -> None:
        """开始在后台处理 handlers 里这几种任务；先把上次进程退出时正在处理的放回队列。"""
        ...

    async def stop(self) -> None:
        """停止处理。正在处理的任务被中断，保持"处理中"，下次启动时重做。"""
        ...


class TableJobQueue:
    def __init__(
        self,
        pool: Pool,
        *,
        poll_interval: float = 5.0,
        max_attempts: int = 3,
        retry_delay: float = 30.0,
    ) -> None:
        self._pool = pool
        self._poll_interval = poll_interval  # 没有新任务通知时，隔多久看一次到期的重试
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay  # 第 n 次失败后等 n 倍这么久再试
        self._handlers: Mapping[str, JobHandler] = {}
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None

    async def enqueue(self, kind: str, payload: dict[str, Any]) -> UUID:
        job_id = new_id()
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO jobs (id, kind, payload) VALUES (%s, %s, %s)",
                (job_id, kind, Jsonb(payload)),
            )
        self._wake.set()
        return job_id

    async def start(self, handlers: Mapping[str, JobHandler]) -> None:
        self._handlers = handlers
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status = 'queued', locked_at = NULL, updated_at = now() "
                "WHERE status = 'running' AND kind = ANY(%s)",
                (list(handlers),),
            )
        self._worker = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def _loop(self) -> None:
        while True:
            self._wake.clear()
            try:
                job = await self._claim()
            except Exception:  # 数据库暂时不可用：稍后再试，不让后台循环退出
                logger.exception("读取后台任务失败")
                job = None
            if job is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self._poll_interval)
                continue
            try:
                await self._run(job)
            except (
                Exception
            ):  # 写任务结果时数据库出错：这个任务保持"处理中"、下次启动时重做，循环继续
                logger.exception("后台任务 %s（%s）的结果没能写入数据库", job["id"], job["kind"])

    async def _claim(self) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1, "
                "updated_at = now() WHERE id = (SELECT id FROM jobs WHERE status = 'queued' "
                "AND kind = ANY(%s) AND run_at <= now() ORDER BY run_at "
                "FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id, kind, payload, attempts",
                (list(self._handlers),),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def _run(self, job: dict[str, Any]) -> None:
        handler = self._handlers[job["kind"]]  # 只领取有处理函数的种类
        try:
            await handler(job["payload"])
        except Exception as exc:  # 后台任务边界：一个任务出错不影响后面的任务
            logger.exception("后台任务 %s（%s）失败", job["id"], job["kind"])
            if job["attempts"] >= self._max_attempts:
                await self._finish(job["id"], "failed", str(exc))
            else:
                await self._retry(job["id"], str(exc), delay=self._retry_delay * job["attempts"])
            return
        await self._finish(job["id"], "done", None)

    async def _finish(self, job_id: UUID, status: str, error: str | None) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status = %s, last_error = %s, locked_at = NULL, "
                "updated_at = now() WHERE id = %s",
                (status, error, job_id),
            )

    async def _retry(self, job_id: UUID, error: str, *, delay: float) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status = 'queued', last_error = %s, locked_at = NULL, "
                "run_at = now() + make_interval(secs => %s), updated_at = now() WHERE id = %s",
                (error, delay, job_id),
            )
        self._wake.set()
