"""workspace_files 表（设计文档 9.3、11.1）：登记会话里的上传与产物，下载地址用这里的 ID。"""

import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from common.db import Pool
from common.errors import NotFoundError

_NAMESPACE = uuid.UUID("6f1c2a5e-8d1b-4b7a-9f3e-2c4d5e6f7a8b")
_COLUMNS = "id, thread_id, path, source, media_type, size, created_at, updated_at"

type FileSource = Literal["upload", "output"]


def workspace_file_id(thread_id: UUID, path: str) -> UUID:
    """会话 + 路径决定文件 ID：改动后仍是同一个文件，推送产物事件时不必先查数据库。"""
    return uuid.uuid5(_NAMESPACE, f"{thread_id}:{path}")


class WorkspaceFile(BaseModel):
    id: UUID
    thread_id: UUID
    path: str  # 相对会话目录，如 outputs/chart.png
    source: FileSource
    media_type: str
    size: int
    created_at: datetime
    updated_at: datetime


class WorkspaceFileRepo:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def record(
        self, thread_id: UUID, path: str, *, source: FileSource, size: int, media_type: str
    ) -> WorkspaceFile:
        """登记一个文件；已登记过（同会话同路径）则更新大小与类型。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO workspace_files (id, thread_id, path, source, media_type, size) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET size = EXCLUDED.size, "
                "media_type = EXCLUDED.media_type, updated_at = now() "
                f"RETURNING {_COLUMNS}",
                (workspace_file_id(thread_id, path), thread_id, path, source, media_type, size),
            )
            row = await cur.fetchone()
        return WorkspaceFile.model_validate(row)

    async def get(self, file_id: UUID) -> WorkspaceFile:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM workspace_files WHERE id = %s", (file_id,)
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"文件不存在：{file_id}")
        return WorkspaceFile.model_validate(row)

    async def for_thread(self, thread_id: UUID) -> list[WorkspaceFile]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM workspace_files WHERE thread_id = %s ORDER BY path",
                (thread_id,),
            )
            rows = await cur.fetchall()
        return [WorkspaceFile.model_validate(row) for row in rows]

    async def delete_for_thread(self, thread_id: UUID) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM workspace_files WHERE thread_id = %s", (thread_id,))
