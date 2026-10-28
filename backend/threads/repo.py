"""会话的数据访问。"""

from collections.abc import Sequence
from uuid import UUID

from agents.main_agent.runtime import PermissionMode
from backend.threads.schemas import Thread
from common.db import Pool
from common.errors import NotFoundError
from common.ids import new_id, short_id

_COLUMNS = "id, short_id, title, model, permission_mode, archived, created_at, updated_at"
_QUALIFIED = ", ".join(f"t.{column}" for column in _COLUMNS.split(", "))


def auto_title(first_message: str) -> str:
    """会话的自动标题：首条消息的前 30 个字（之后由后台按对话内容生成正式标题）。"""
    return first_message[:30]


class ThreadRepo:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def create(self, *, model: str, title: str = "") -> Thread:
        """新会话放在最上面（位置比现有最小的再小 1）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO threads (id, short_id, title, model, position) VALUES "
                "(%s, %s, %s, %s, (SELECT coalesce(min(position), 1) - 1 FROM threads)) "
                f"RETURNING {_COLUMNS}",
                (new_id(), short_id(), title, model),
            )
            row = await cur.fetchone()
        assert row is not None  # INSERT ... RETURNING 必有一行
        return Thread.model_validate(row)

    async def list_active(self) -> list[Thread]:
        """未归档的会话，带最近一次运行折算出的状态（只看最近一次：失败后又成功就不再标红）。"""
        return await self._listed(archived=False)

    async def list_archived(self) -> list[Thread]:
        """归档的会话（设计 2026-10-23 6.5），最近改过的在前。"""
        return await self._listed(archived=True)

    async def _listed(self, *, archived: bool) -> list[Thread]:
        # 顺利结束、结束时间晚于最后查看时间的亮"有新回答"（设计 2026-10-23 6.5）
        order = "t.updated_at DESC" if archived else "t.position, t.created_at DESC"
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_QUALIFIED}, CASE latest.status "
                "WHEN 'queued' THEN 'running' WHEN 'running' THEN 'running' "
                "WHEN 'interrupted' THEN 'waiting' WHEN 'failed' THEN 'failed' "
                "WHEN 'completed' THEN CASE WHEN latest.finished_at > t.last_viewed_at "
                "THEN 'new' END END AS activity "
                "FROM threads t LEFT JOIN LATERAL (SELECT status, finished_at FROM runs "
                "WHERE runs.thread_id = t.id ORDER BY runs.created_at DESC LIMIT 1) latest ON true "
                f"WHERE t.archived = %s ORDER BY {order}",
                (archived,),
            )
            rows = await cur.fetchall()
        return [Thread.model_validate(row) for row in rows]

    async def mark_viewed(self, thread_id: UUID) -> None:
        """记下"看过了"：清掉"有新回答"。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE threads SET last_viewed_at = now() WHERE id = %s", (thread_id,)
            )
        if cur.rowcount == 0:
            raise NotFoundError(f"会话不存在：{thread_id}")

    async def search_titles(self, query: str, *, limit: int = 20) -> list[Thread]:
        """标题里含这段文字的会话（不分大小写，含已归档的），最近改过的在前；% 与 _ 不当通配符。"""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM threads WHERE title ILIKE %s ESCAPE '\\' "
                "ORDER BY updated_at DESC LIMIT %s",
                (f"%{escaped}%", limit),
            )
            rows = await cur.fetchall()
        return [Thread.model_validate(row) for row in rows]

    async def titles(self, ids: Sequence[UUID]) -> dict[UUID, str]:
        """这些会话的标题；已删除的不在结果里。"""
        if not ids:
            return {}
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, title FROM threads WHERE id = ANY(%s)", (list(ids),)
            )
            rows = await cur.fetchall()
        return {row["id"]: row["title"] for row in rows}

    async def get(self, thread_id: UUID) -> Thread:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM threads WHERE id = %s", (thread_id,))
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"会话不存在：{thread_id}")
        return Thread.model_validate(row)

    async def update(
        self,
        thread_id: UUID,
        *,
        title: str | None = None,
        model: str | None = None,
        permission_mode: PermissionMode | None = None,
        archived: bool | None = None,
    ) -> Thread:
        """只改给了值的几项（列名来自固定的几项，值走参数）。"""
        changes = {
            "title": title,
            "model": model,
            "permission_mode": permission_mode,
            "archived": archived,
        }
        columns = [name for name, value in changes.items() if value is not None]
        if not columns:
            return await self.get(thread_id)
        assignments = ", ".join(f"{name} = %s" for name in columns)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE threads SET {assignments} WHERE id = %s RETURNING {_COLUMNS}",
                (*(changes[name] for name in columns), thread_id),
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"会话不存在：{thread_id}")
        return Thread.model_validate(row)

    async def reorder(self, thread_ids: list[UUID]) -> None:
        """按给定顺序保存会话位置（在一个事务里）。"""
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.executemany(
                "UPDATE threads SET position = %s WHERE id = %s",
                [(index, thread_id) for index, thread_id in enumerate(thread_ids)],
            )

    async def model_counts(self) -> dict[str, int]:
        """每个模型有几个会话在用（模型页删除前提示）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT model, count(*) AS n FROM threads GROUP BY model")
            rows = await cur.fetchall()
        return {row["model"]: row["n"] for row in rows}

    async def reassign_model(self, old: str, new: str) -> int:
        """模型被删后，在用它的会话改用 new；历史消息与用量不动。返回改了几个会话。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute("UPDATE threads SET model = %s WHERE model = %s", (new, old))
            return cur.rowcount

    async def delete(self, thread_id: UUID) -> None:
        """删除会话；运行与界面历史随外键级联删除。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM threads WHERE id = %s", (thread_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"会话不存在：{thread_id}")

    async def touch(self, thread_id: UUID, *, first_message: str) -> None:
        """记录一次新运行：刷新更新时间；标题为空时用自动标题（首条消息的前 30 个字）。"""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE threads SET updated_at = now(), "
                "title = CASE WHEN title = '' THEN %s ELSE title END WHERE id = %s",
                (auto_title(first_message), thread_id),
            )

    async def replace_title(self, thread_id: UUID, *, old: str, new: str) -> bool:
        """标题仍是 old 时才换成 new（期间用户改过名就不动），返回是否换了。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE threads SET title = %s WHERE id = %s AND title = %s",
                (new, thread_id, old),
            )
            return cur.rowcount > 0
