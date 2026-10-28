"""知识存储的 PostgreSQL 实现。

pgvector 存向量（按意思检索）；jieba 分词后存进全文检索字段（按精确词检索）。
文档片段连上 knowledge_documents 取文档名，检索结果据此给出出处。
"""

import asyncio
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import ForeignKeyViolation

from agents.main_agent.knowledge.chunking import Chunk
from agents.main_agent.knowledge.models import (
    KnowledgeHit,
    KnowledgeItem,
    KnowledgeKind,
    NewKnowledge,
    clean_tags,
)
from agents.main_agent.knowledge.suspicious import suspicious_reason
from agents.main_agent.knowledge.tokens import search_tokens
from agents.main_agent.models import Embedder, estimate_text_tokens
from common.db import Pool
from common.errors import NotFoundError
from common.ids import new_id

_COLUMNS = (
    "i.id, i.kind, i.tags, i.pinned, i.content, i.source, i.source_thread_id, i.source_run_id, "
    "i.document_id, i.seq, i.section_path, i.page, d.title AS document_title, i.token_count, "
    "i.embedding_model, i.created_at, i.updated_at, i.suspicious, i.trusted"
)
# 可疑且未确认的记忆（设计 2026-10-23 6.6）不进检索、召回
_NOT_FLAGGED = "(i.suspicious IS NULL OR i.trusted)"
_FROM = "FROM knowledge_items i LEFT JOIN knowledge_documents d ON d.id = i.document_id"
_SELECT = f"SELECT {_COLUMNS} {_FROM}"
# Qwen3 向量模型对"查询"加一句任务说明效果更好（设计文档 8.5）；存进去的条目本身不加
QUERY_PREFIX = "Instruct: 根据问题找出相关的知识与记忆\nQuery: "
_RRF_K = 60  # 倒数排名融合的常数：排名靠前的差距被拉开，又不至于一家独大
_CANDIDATES = 4  # 每路先各取 top_k 的几倍再融合


def _vector(values: list[float]) -> str:
    return "[" + ",".join(map(str, values)) + "]"


async def _search_text(text: str) -> str:
    # jieba 分词是 CPU 活，文档片段多时不能挡住事件循环
    return " ".join(await asyncio.to_thread(search_tokens, text))


def _filters(
    *,
    kinds: Sequence[str] | None,
    tags: Sequence[str],
    pinned: bool | None = None,
    hide_flagged: bool = False,
    flagged: bool | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = [_NOT_FLAGGED if hide_flagged else "TRUE"]
    params: list[Any] = []
    if flagged is not None:
        clauses.append(_NOT_FLAGGED if not flagged else f"NOT {_NOT_FLAGGED}")
    if kinds is not None:
        clauses.append("i.kind = ANY(%s)")
        params.append(list(kinds))
    if tags:
        clauses.append("i.tags @> %s")
        params.append(list(tags))
    if pinned is not None:
        clauses.append("i.pinned = %s")
        params.append(pinned)
    return " AND ".join(clauses), params


async def _scan_past_filters(conn: AsyncConnection[Any]) -> None:
    """向量索引默认只扫前 40 个近邻，再按种类、标签筛选：文档片段多了以后结果可能不全。
    让它在筛选后不够数时继续往下扫（pgvector 0.8 起支持，只对当前事务生效）。"""
    await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")


def _chunk_text(title: str, chunk: Chunk) -> str:
    """向量化与分词用的文字带上文档名与章节：按章节名也能找到片段。"""
    return f"《{title}》{chunk.section_path or ''}\n{chunk.content}"


class PgKnowledgeStore:
    def __init__(self, pool: Pool, embedder: Embedder) -> None:
        self._pool = pool
        self._embedder = embedder

    async def add(self, new: NewKnowledge) -> KnowledgeItem:
        [vector] = await self._embedder.embed([new.content])
        item_id = new_id()
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO knowledge_items (id, kind, tags, pinned, content, source, "
                "source_thread_id, source_run_id, token_count, embedding, embedding_model, search, "
                "suspicious) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, "
                "to_tsvector('simple', %s), %s)",
                (
                    item_id,
                    new.kind,
                    new.tags,
                    new.pinned,
                    new.content,
                    new.source,
                    new.source_thread_id,
                    new.source_run_id,
                    estimate_text_tokens(new.content),
                    _vector(vector),
                    self._embedder.model,
                    await _search_text(new.content),
                    suspicious_reason(new.content) if new.kind == "memory" else None,
                ),
            )
        return await self.get(item_id)

    async def add_chunks(
        self, document_id: UUID, title: str, chunks: Sequence[Chunk]
    ) -> list[KnowledgeItem]:
        if not chunks:
            return []
        texts = [_chunk_text(title, chunk) for chunk in chunks]
        vectors = await self._embedder.embed(texts)
        rows = [
            (
                new_id(),
                chunk.content,
                document_id,
                chunk.seq,
                chunk.section_path,
                chunk.page,
                estimate_text_tokens(chunk.content),
                _vector(vector),
                self._embedder.model,
                await _search_text(text),
            )
            for chunk, text, vector in zip(chunks, texts, vectors, strict=True)
        ]
        try:
            async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO knowledge_items (id, kind, source, content, document_id, seq, "
                    "section_path, page, token_count, embedding, embedding_model, search) "
                    "VALUES (%s, 'document_chunk', 'document', %s, %s, %s, %s, %s, %s, "
                    "%s::vector, %s, to_tsvector('simple', %s))",
                    rows,
                )
        except ForeignKeyViolation as exc:  # 处理途中文档被删了
            raise NotFoundError(f"文档不存在：{document_id}") from exc
        items = {item.id: item for item in await self._items([row[0] for row in rows])}
        return [items[row[0]] for row in rows]

    async def delete_chunks(self, document_id: UUID) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM knowledge_items WHERE document_id = %s AND kind = 'document_chunk'",
                (document_id,),
            )
            return cur.rowcount

    async def around(self, item_id: UUID, window: int) -> list[KnowledgeItem]:
        item = await self.get(item_id)
        if item.document_id is None or item.seq is None:
            return [item]
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"{_SELECT} WHERE i.document_id = %s AND i.seq BETWEEN %s AND %s ORDER BY i.seq",
                (item.document_id, item.seq - window, item.seq + window),
            )
            rows = await cur.fetchall()
        return [KnowledgeItem.model_validate(row) for row in rows]

    async def get(self, item_id: UUID) -> KnowledgeItem:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"{_SELECT} WHERE i.id = %s", (item_id,))
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"知识条目不存在：{item_id}")
        return KnowledgeItem.model_validate(row)

    async def update(
        self,
        item_id: UUID,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
        trusted: bool | None = None,
    ) -> KnowledgeItem:
        current = await self.get(item_id)
        sets: list[str] = ["updated_at = now()"]
        params: list[Any] = []
        # 内容没变就不重新向量化：只改标签、常驻时，向量模型停掉也能改
        if content is not None and content != current.content:
            [vector] = await self._embedder.embed([content])
            sets += [
                "content = %s",
                "token_count = %s",
                "embedding = %s::vector",
                "embedding_model = %s",
                "search = to_tsvector('simple', %s)",
            ]
            params += [
                content,
                estimate_text_tokens(content),
                _vector(vector),
                self._embedder.model,
                await _search_text(content),
            ]
            if current.kind == "memory":  # 改了内容重新检查，之前的"确认无害"作废
                sets.append("suspicious = %s")
                params.append(suspicious_reason(content))
                if trusted is None:
                    trusted = False
        if tags is not None:
            sets.append("tags = %s")
            params.append(clean_tags(tags))
        if pinned is not None:
            sets.append("pinned = %s")
            params.append(pinned)
        if trusted is not None:
            sets.append("trusted = %s")
            params.append(trusted)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE knowledge_items SET {', '.join(sets)} WHERE id = %s RETURNING id",
                (*params, item_id),
            )
            if await cur.fetchone() is None:
                raise NotFoundError(f"知识条目不存在：{item_id}")
        return await self.get(item_id)

    async def delete(self, item_id: UUID) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM knowledge_items WHERE id = %s RETURNING id", (item_id,)
            )
            if await cur.fetchone() is None:
                raise NotFoundError(f"知识条目不存在：{item_id}")

    async def list_items(
        self,
        *,
        kind: KnowledgeKind | None = None,
        tags: Sequence[str] = (),
        pinned: bool | None = None,
        flagged: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        where, params = _filters(
            kinds=None if kind is None else [kind], tags=tags, pinned=pinned, flagged=flagged
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"{_SELECT} WHERE {where} ORDER BY i.created_at DESC, i.id LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            rows = await cur.fetchall()
        return [KnowledgeItem.model_validate(row) for row in rows]

    async def pinned(self) -> list[KnowledgeItem]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"{_SELECT} WHERE i.pinned ORDER BY i.created_at, i.id")
            rows = await cur.fetchall()
        return [KnowledgeItem.model_validate(row) for row in rows]

    async def find_memories(self, fragment: str, *, limit: int = 6) -> list[KnowledgeItem]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"{_SELECT} WHERE i.kind = 'memory' AND strpos(lower(i.content), lower(%s)) > 0 "
                "ORDER BY i.created_at, i.id LIMIT %s",
                (fragment, limit),
            )
            rows = await cur.fetchall()
        return [KnowledgeItem.model_validate(row) for row in rows]

    async def search(
        self,
        query: str,
        *,
        kinds: Sequence[KnowledgeKind] | None = None,
        tags: Sequence[str] = (),
        top_k: int = 5,
        include_suspicious: bool = False,
    ) -> list[KnowledgeHit]:
        [vector] = await self._embedder.embed([QUERY_PREFIX + query])
        where, params = _filters(kinds=kinds, tags=tags, hide_flagged=not include_suspicious)
        candidates = top_k * _CANDIDATES
        words = " OR ".join(await asyncio.to_thread(search_tokens, query))
        async with self._pool.connection() as conn, conn.transaction():
            await _scan_past_filters(conn)
            cur = await conn.execute(
                f"SELECT i.id FROM knowledge_items i WHERE {where} "
                "ORDER BY i.embedding <=> %s::vector LIMIT %s",
                (*params, _vector(vector), candidates),
            )
            by_meaning = [row["id"] for row in await cur.fetchall()]
            by_words: list[UUID] = []
            if words:
                cur = await conn.execute(
                    "SELECT i.id FROM knowledge_items i, websearch_to_tsquery('simple', %s) AS q "
                    f"WHERE i.search @@ q AND {where} ORDER BY ts_rank(i.search, q) DESC LIMIT %s",
                    (words, *params, candidates),
                )
                by_words = [row["id"] for row in await cur.fetchall()]
        # 倒数排名融合：每路排第 n 名得 1 / (60 + n) 分，两路都靠前的条目排最前
        scores: dict[UUID, float] = {}
        for ranking in (by_meaning, by_words):
            for rank, item_id in enumerate(ranking, start=1):
                scores[item_id] = scores.get(item_id, 0.0) + 1 / (_RRF_K + rank)
        best = sorted(scores, key=lambda item_id: scores[item_id], reverse=True)[:top_k]
        items = {item.id: item for item in await self._items(best)}
        # 排好名到取出条目之间可能有条目被删（知识库页、提取任务）：跳过
        return [
            KnowledgeHit(item=items[item_id], score=scores[item_id])
            for item_id in best
            if item_id in items
        ]

    async def recall(self, query: str, *, top_k: int, min_similarity: float) -> list[KnowledgeHit]:
        [vector] = await self._embedder.embed([QUERY_PREFIX + query])
        async with self._pool.connection() as conn, conn.transaction():
            await _scan_past_filters(conn)
            cur = await conn.execute(
                f"SELECT {_COLUMNS}, 1 - (i.embedding <=> %s::vector) AS similarity {_FROM} "
                f"WHERE i.kind = 'memory' AND NOT i.pinned AND {_NOT_FLAGGED} "
                "ORDER BY i.embedding <=> %s::vector LIMIT %s",
                (_vector(vector), _vector(vector), top_k),
            )
            rows = await cur.fetchall()
        return [
            KnowledgeHit(item=KnowledgeItem.model_validate(row), score=row["similarity"])
            for row in rows
            if row["similarity"] >= min_similarity
        ]

    async def _items(self, ids: list[UUID]) -> list[KnowledgeItem]:
        if not ids:
            return []
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"{_SELECT} WHERE i.id = ANY(%s)", (ids,))
            rows = await cur.fetchall()
        return [KnowledgeItem.model_validate(row) for row in rows]
