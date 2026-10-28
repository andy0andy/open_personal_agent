"""运行与运行事件的数据访问。"""

from collections.abc import Sequence
from uuid import UUID

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from agents.main_agent.runtime import PermissionMode, UsageTotals
from backend.runs.schemas import RunAttachment, RunHistory, RunRecord
from backend.runtime import EventEnvelope
from common.db import Pool
from common.errors import ConflictError, NotFoundError
from common.ids import new_id

# 用户输入存在 input 里：{"message": 原文, "attachments": [附带的文件], "permission": 审批权限}
# （没有附件的旧记录不带 attachments，D23 之前的记录不带 permission）
_COLUMNS = (
    "id, thread_id, status, model, COALESCE(input->>'permission', 'ask') AS permission, "
    "input->>'message' AS message, "
    "COALESCE(input->'attachments', '[]'::jsonb) AS attachments, error, created_at, retry_of"
)


class RunRepo:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def create(
        self,
        *,
        thread_id: UUID,
        model: str,
        message: str,
        attachments: Sequence[RunAttachment] = (),
        permission: PermissionMode = "ask",
        retry_of: UUID | None = None,
    ) -> RunRecord:
        """新建一条运行中的记录；同一会话已有进行中的运行时抛 ConflictError（由唯一索引保证）。

        retry_of：这是"重试这一轮"发起的运行时，重试的是哪一次（D26）。
        """
        user_input = {
            "message": message,
            "attachments": [item.model_dump(mode="json") for item in attachments],
            "permission": permission,
        }
        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO runs (id, thread_id, status, model, input, retry_of) "
                    f"VALUES (%s, %s, 'running', %s, %s, %s) RETURNING {_COLUMNS}",
                    (new_id(), thread_id, model, Jsonb(user_input), retry_of),
                )
                row = await cur.fetchone()
        except UniqueViolation as exc:
            raise ConflictError("该会话已有进行中的运行，请等待它结束") from exc
        assert row is not None  # INSERT ... RETURNING 必有一行
        return RunRecord.model_validate(row)

    async def get(self, run_id: UUID) -> RunRecord:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM runs WHERE id = %s", (run_id,))
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"运行不存在：{run_id}")
        return RunRecord.model_validate(row)

    async def latest(self, thread_id: UUID) -> RunRecord | None:
        """会话里最近的一次运行；还没有运行时返回 None。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM runs WHERE thread_id = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            )
            row = await cur.fetchone()
        return RunRecord.model_validate(row) if row else None

    async def has_active(self, thread_id: UUID) -> bool:
        """该会话是否有进行中（排队 / 运行中 / 等待审批）的运行。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT EXISTS (SELECT 1 FROM runs WHERE thread_id = %s "
                "AND status IN ('queued', 'running', 'interrupted')) AS active",
                (thread_id,),
            )
            row = await cur.fetchone()
        return bool(row and row["active"])

    async def count_active(self, model: str) -> int:
        """用这个模型、还没结束的运行有几个（排队、运行中、等审批都算）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM runs WHERE model = %s "
                "AND status IN ('queued', 'running', 'interrupted')",
                (model,),
            )
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def count_running(self) -> int:
        """正在排队或运行的运行有几个（等待审批的不算）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM runs WHERE status IN ('queued', 'running')"
            )
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def finished_ids(self) -> list[UUID]:
        """全部已结束（顺利、失败、被停）的运行，按开始时间排列（升级后补建会话索引用）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id FROM runs WHERE status IN ('completed', 'failed', 'cancelled') "
                "ORDER BY created_at"
            )
            return [row["id"] for row in await cur.fetchall()]

    async def retried(self, run_id: UUID) -> bool:
        """这一轮是否已被"重试这一轮"替换（D26）：替换掉的那一轮不再写进会话索引。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT EXISTS (SELECT 1 FROM runs WHERE retry_of = %s) AS retried", (run_id,)
            )
            row = await cur.fetchone()
        return bool(row and row["retried"])

    async def completed_count(self, thread_id: UUID) -> int:
        """该会话里顺利结束的运行次数。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM runs WHERE thread_id = %s AND status = 'completed'",
                (thread_id,),
            )
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def first_message(self, thread_id: UUID) -> str:
        """该会话第一次运行的消息（会话的自动标题由它而来）；没有运行时为空字符串。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT input->>'message' AS message FROM runs WHERE thread_id = %s "
                "ORDER BY created_at LIMIT 1",
                (thread_id,),
            )
            row = await cur.fetchone()
        return str(row["message"]) if row else ""

    async def finish(
        self, run_id: UUID, *, status: str, error: str | None, usage: UsageTotals | None = None
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE runs SET status = %s, error = %s, usage = %s, finished_at = now() "
                "WHERE id = %s",
                (status, error, Jsonb(usage.model_dump()) if usage else None, run_id),
            )

    async def pause(self, run_id: UUID, *, usage: UsageTotals) -> None:
        """运行暂停等待审批：状态改为 interrupted，记下到此为止的用量合计。"""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE runs SET status = 'interrupted', usage = %s WHERE id = %s",
                (Jsonb(usage.model_dump()), run_id),
            )

    async def mark_resumed(self, run_id: UUID) -> bool:
        """等待审批的运行改回运行中；已被别的请求改过（重复提交）时返回 False。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE runs SET status = 'running' WHERE id = %s AND status = 'interrupted'",
                (run_id,),
            )
            return cur.rowcount == 1

    async def usage_totals(self, run_id: UUID) -> UsageTotals:
        """已记下的用量合计（暂停或结束时写入）；还没有时为空合计。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT usage FROM runs WHERE id = %s", (run_id,))
            row = await cur.fetchone()
        if row is None or row["usage"] is None:
            return UsageTotals()
        return UsageTotals.model_validate(row["usage"])

    async def add_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        if not events:
            return
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO run_events (run_id, seq, type, payload) VALUES (%s, %s, %s, %s)",
                [(run_id, e.seq, e.type, Jsonb(e.model_dump(mode="json"))) for e in events],
            )

    async def update_event(self, run_id: UUID, event: EventEnvelope) -> None:
        """改写已存的一个事件（按序号对上）。"""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE run_events SET payload = %s WHERE run_id = %s AND seq = %s",
                (Jsonb(event.model_dump(mode="json")), run_id, event.seq),
            )

    async def replace_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        """在一个事务里用 events 替换这次运行已存的全部事件。"""
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute("DELETE FROM run_events WHERE run_id = %s", (run_id,))
            if events:
                await cur.executemany(
                    "INSERT INTO run_events (run_id, seq, type, payload) VALUES (%s, %s, %s, %s)",
                    [(run_id, e.seq, e.type, Jsonb(e.model_dump(mode="json"))) for e in events],
                )

    async def events(self, run_id: UUID, *, after_seq: int = 0) -> list[EventEnvelope]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT payload FROM run_events WHERE run_id = %s AND seq > %s ORDER BY seq",
                (run_id, after_seq),
            )
            rows = await cur.fetchall()
        return [EventEnvelope.model_validate(row["payload"]) for row in rows]

    async def history(self, thread_id: UUID) -> list[RunHistory]:
        """会话的界面历史：按时间顺序的每次运行及其已存事件。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM runs WHERE thread_id = %s ORDER BY created_at",
                (thread_id,),
            )
            runs = await cur.fetchall()
            cur = await conn.execute(
                "SELECT e.run_id, e.payload FROM run_events e JOIN runs r ON r.id = e.run_id "
                "WHERE r.thread_id = %s ORDER BY e.run_id, e.seq",
                (thread_id,),
            )
            event_rows = await cur.fetchall()
        events: dict[UUID, list[EventEnvelope]] = {}
        for row in event_rows:
            events.setdefault(row["run_id"], []).append(
                EventEnvelope.model_validate(row["payload"])
            )
        return [RunHistory(**run, events=events.get(run["id"], [])) for run in runs]

    async def fail_unfinished(self) -> list[UUID]:
        """服务启动时调用：把上次进程退出时未跑完的运行标记为失败，返回这些运行的 ID
        （调用方给它们登记写会话索引：已分批写下的部分回答也要搜得到）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE runs SET status = 'failed', error = '服务重启中断', finished_at = now() "
                "WHERE status IN ('queued', 'running') RETURNING id"
            )
            return [row["id"] for row in await cur.fetchall()]
