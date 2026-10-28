"""知识库文档的登记（设计文档 11 节 knowledge_documents）：文件名、处理状态与进度。

文档切出的片段是 knowledge_items 里的条目，删除文档时随外键一起删除。
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from common.db import Pool
from common.errors import NotFoundError

type DocumentStatus = Literal["pending", "processing", "done", "failed"]

_COLUMNS = (
    "id, title, filename, media_type, size, status, error, chunk_total, item_count, "
    "source_thread_id, created_at, updated_at"
)


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: UUID
    title: str
    filename: str
    media_type: str
    size: int
    status: DocumentStatus
    error: str | None  # 失败原因（直接给用户看）
    chunk_total: int  # 切出的片段数（处理中显示进度用）
    item_count: int  # 已写入知识库的片段数
    source_thread_id: UUID | None  # 从会话文件加入时的来源会话
    created_at: datetime
    updated_at: datetime


class DocumentRepo:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def create(
        self,
        *,
        document_id: UUID,
        title: str,
        filename: str,
        media_type: str,
        size: int,
        blob_key: str,
        content_hash: str | None = None,
        source_thread_id: UUID | None = None,
    ) -> KnowledgeDocument:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO knowledge_documents (id, title, filename, media_type, size, blob_key, "
                f"content_hash, source_thread_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                f"RETURNING {_COLUMNS}",
                (
                    document_id,
                    title,
                    filename,
                    media_type,
                    size,
                    blob_key,
                    content_hash,
                    source_thread_id,
                ),
            )
            row = await cur.fetchone()
        assert row is not None  # INSERT ... RETURNING 必有一行
        return KnowledgeDocument.model_validate(row)

    async def get(self, document_id: UUID) -> KnowledgeDocument:
        return KnowledgeDocument.model_validate(await self._row(_COLUMNS, document_id))

    async def blob_key(self, document_id: UUID) -> str:
        return str((await self._row("blob_key", document_id))["blob_key"])

    async def find_by_hash(self, content_hash: str) -> KnowledgeDocument | None:
        """内容（SHA-256）相同的那份文档；没有时为 None（积压小问题 C12）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM knowledge_documents WHERE content_hash = %s "
                "ORDER BY created_at LIMIT 1",
                (content_hash,),
            )
            row = await cur.fetchone()
        return KnowledgeDocument.model_validate(row) if row else None

    async def without_hash(self) -> list[tuple[UUID, str]]:
        """还没有内容哈希的文档（升级前加入的）：(文档 ID, 原文件的存储键)。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, blob_key FROM knowledge_documents WHERE content_hash IS NULL "
                "ORDER BY created_at"
            )
            return [(row["id"], row["blob_key"]) for row in await cur.fetchall()]

    async def set_hash(self, document_id: UUID, content_hash: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE knowledge_documents SET content_hash = %s WHERE id = %s",
                (content_hash, document_id),
            )

    async def list_documents(self) -> list[KnowledgeDocument]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM knowledge_documents ORDER BY created_at DESC, id"
            )
            rows = await cur.fetchall()
        return [KnowledgeDocument.model_validate(row) for row in rows]

    async def update_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        *,
        error: str | None = None,
        chunk_total: int | None = None,
        item_count: int | None = None,
    ) -> None:
        """改状态；原因随新状态一起改（不给即清空），片段数不给的保持不变。
        改回"待处理"（重新处理）时，中断次数清零。"""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE knowledge_documents SET status = %s, error = %s, "
                "chunk_total = COALESCE(%s, chunk_total), item_count = COALESCE(%s, item_count), "
                "interruptions = CASE WHEN %s = 'pending' THEN 0 ELSE interruptions END, "
                "updated_at = now() WHERE id = %s",
                (status, error, chunk_total, item_count, status, document_id),
            )

    async def count_interruption(self, document_id: UUID) -> int:
        """记一次"处理时服务中断"，返回累计次数。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE knowledge_documents SET interruptions = interruptions + 1 "
                "WHERE id = %s RETURNING interruptions",
                (document_id,),
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"文档不存在：{document_id}")
        return int(row["interruptions"])

    async def delete(self, document_id: UUID) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM knowledge_documents WHERE id = %s", (document_id,)
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"文档不存在：{document_id}")

    async def _row(self, columns: str, document_id: UUID) -> dict[str, Any]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {columns} FROM knowledge_documents WHERE id = %s", (document_id,)
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"文档不存在：{document_id}")
        return dict(row)
