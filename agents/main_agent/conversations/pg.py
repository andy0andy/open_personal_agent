"""ConversationIndex 的 PostgreSQL 实现：分词同知识库（jieba 分好再存进 tsvector）。"""

import asyncio
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from agents.main_agent.conversations.base import (
    ConversationHit,
    ConversationTurn,
    NewConversationTurn,
    hit_terms,
    snippet,
)
from agents.main_agent.knowledge import search_tokens
from common.db import Pool

# 轮次现算：同一会话里按开始时间排序的序号
_NUMBERED = (
    "WITH numbered AS (SELECT *, row_number() OVER "
    "(PARTITION BY thread_id ORDER BY started_at, run_id) AS turn FROM conversation_turns{where})"
)
_COLUMNS = "thread_id, run_id, title, started_at, user_text, answer_text, turn"


class PgConversationIndex:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def index(self, turn: NewConversationTurn, *, replaces: UUID | None = None) -> None:
        text = " ".join(
            await asyncio.to_thread(search_tokens, f"{turn.user_text}\n{turn.answer_text}")
        )
        async with self._pool.connection() as conn, conn.transaction():
            if replaces is not None:
                await conn.execute("DELETE FROM conversation_turns WHERE run_id = %s", (replaces,))
            await conn.execute(
                "INSERT INTO conversation_turns "
                "(run_id, thread_id, title, started_at, user_text, answer_text, search) "
                "VALUES (%s, %s, %s, %s, %s, %s, to_tsvector('simple', %s)) "
                "ON CONFLICT (run_id) DO UPDATE SET title = EXCLUDED.title, "
                "user_text = EXCLUDED.user_text, answer_text = EXCLUDED.answer_text, "
                "search = EXCLUDED.search",
                (
                    turn.run_id,
                    turn.thread_id,
                    turn.title,
                    turn.started_at,
                    turn.user_text,
                    turn.answer_text,
                    text,
                ),
            )

    async def retitle(self, thread_id: UUID, title: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE conversation_turns SET title = %s WHERE thread_id = %s", (title, thread_id)
            )

    async def delete_thread(self, thread_id: UUID) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM conversation_turns WHERE thread_id = %s", (thread_id,))

    async def search(self, query: str, *, limit: int = 10) -> list[ConversationHit]:
        words = await asyncio.to_thread(search_tokens, query)
        if not words:
            return []
        # 原文里整段出现的排在前面：分词会把名字和旁边的字粘在一起（"张伟明天"切成"张伟明"），
        # 只靠分词搜不到人名（审查 I2）；% 与 _ 不当通配符
        text = query.strip()
        pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        exact = await self._fetch(
            _NUMBERED.format(where="")
            + f" SELECT {_COLUMNS} FROM numbered WHERE user_text ILIKE %s ESCAPE '\\' "
            "OR answer_text ILIKE %s ESCAPE '\\' ORDER BY started_at DESC LIMIT %s",
            (pattern, pattern, limit),
        )
        ranked = await self._fetch(
            _NUMBERED.format(where="")
            + f" SELECT {_COLUMNS} FROM numbered, websearch_to_tsquery('simple', %s) AS q "
            "WHERE search @@ q ORDER BY ts_rank(search, q) DESC, started_at DESC LIMIT %s",
            (" OR ".join(words), limit),
        )
        turns = {turn.run_id: turn for turn in map(ConversationTurn.model_validate, ranked)}
        merged = {turn.run_id: turn for turn in map(ConversationTurn.model_validate, exact)}
        merged.update({run_id: turn for run_id, turn in turns.items() if run_id not in merged})
        terms = [text.lower(), *words]
        return [
            ConversationHit(turn=turn, snippet=snippet(turn, terms), terms=hit_terms(terms))
            for turn in list(merged.values())[:limit]
        ]

    async def around(self, thread_id: UUID, run_id: UUID, window: int) -> list[ConversationTurn]:
        rows = await self._fetch(
            _NUMBERED.format(where=" WHERE thread_id = %s")
            + f" SELECT {_COLUMNS} FROM numbered WHERE turn BETWEEN "
            "(SELECT turn FROM numbered WHERE run_id = %s) - %s "
            "AND (SELECT turn FROM numbered WHERE run_id = %s) + %s ORDER BY turn",
            (thread_id, run_id, window, run_id, window),
        )
        return [ConversationTurn.model_validate(row) for row in rows]

    async def turn(self, thread_id: UUID, run_id: UUID) -> ConversationTurn | None:
        rows = await self._fetch(
            _NUMBERED.format(where=" WHERE thread_id = %s")
            + f" SELECT {_COLUMNS} FROM numbered WHERE run_id = %s",
            (thread_id, run_id),
        )
        return ConversationTurn.model_validate(rows[0]) if rows else None

    async def recent(self, limit: int) -> list[ConversationTurn]:
        rows = await self._fetch(
            _NUMBERED.format(where="")
            + f", latest AS (SELECT DISTINCT ON (thread_id) {_COLUMNS} FROM numbered "
            "ORDER BY thread_id, started_at DESC) "
            "SELECT * FROM latest ORDER BY started_at DESC LIMIT %s",
            (limit,),
        )
        return [ConversationTurn.model_validate(row) for row in rows]

    async def missing(self, run_ids: Sequence[UUID]) -> set[UUID]:
        if not run_ids:
            return set()
        rows = await self._fetch(
            "SELECT run_id FROM conversation_turns WHERE run_id = ANY(%s)", (list(run_ids),)
        )
        return set(run_ids) - {row["run_id"] for row in rows}

    async def _fetch(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, params)
            return list(await cur.fetchall())
