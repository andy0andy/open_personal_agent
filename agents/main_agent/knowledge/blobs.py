"""原文件存储接口（设计文档 4.2 的 blob_storage）：知识库文档的原文件。

v1 存本地磁盘（.workdata/knowledge/）；以后可换对象存储，接口不变。键的形式为 `<文档 ID>/<文件名>`。
"""

from collections.abc import AsyncIterator
from typing import Protocol

from agents.main_agent.workspace import OpenedFile


class BlobStore(Protocol):
    async def save(self, key: str, chunks: AsyncIterator[bytes], *, max_bytes: int) -> int:
        """边收边写，返回大小；超过 max_bytes 抛 TooLargeError，不留下不完整的文件。"""
        ...

    async def read(self, key: str) -> bytes:
        """整个读出（解析用）；不存在抛 NotFoundError。"""
        ...

    async def open(self, key: str) -> OpenedFile:
        """打开供分块读取（下载用）；不存在抛 NotFoundError。"""
        ...

    async def delete(self, key: str) -> None:
        """不存在也不报错。"""
        ...
