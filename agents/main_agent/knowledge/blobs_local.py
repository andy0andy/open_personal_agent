"""原文件存储的本地磁盘实现：文件存在 <root>/<文档 ID>/<文件名>。"""

import asyncio
import contextlib
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

from agents.main_agent.workspace import OpenedFile
from common.errors import NotFoundError, TooLargeError

_KEY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[^/\\\x00]+")
_CHUNK = 64 * 1024


class LocalDiskBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def save(self, key: str, chunks: AsyncIterator[bytes], *, max_bytes: int) -> int:
        target = self._path(key)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        partial = target.with_name(f"{target.name}.part")
        handle = await asyncio.to_thread(partial.open, "wb")
        size = 0
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise TooLargeError(f"文件超过 {max_bytes // (1024 * 1024)}MB 上限")
                await asyncio.to_thread(handle.write, chunk)
        except BaseException:  # 超限、请求中断（取消）都不留下不完整的文件
            handle.close()
            await asyncio.to_thread(partial.unlink, missing_ok=True)
            await asyncio.to_thread(_remove_if_empty, target.parent)
            raise
        handle.close()
        # 写完再改名：中途失败时不会留下一个看起来完整的文件
        await asyncio.to_thread(os.replace, partial, target)
        return size

    async def read(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except FileNotFoundError as exc:
            raise NotFoundError(f"原文件不存在：{key}") from exc

    async def open(self, key: str) -> OpenedFile:
        target = self._path(key)
        try:
            handle = await asyncio.to_thread(target.open, "rb")
        except FileNotFoundError as exc:
            raise NotFoundError(f"原文件不存在：{key}") from exc
        return OpenedFile(size=os.fstat(handle.fileno()).st_size, chunks=_read_chunks(handle))

    async def delete(self, key: str) -> None:
        target = self._path(key)
        await asyncio.to_thread(target.unlink, missing_ok=True)
        await asyncio.to_thread(_remove_if_empty, target.parent)

    def _path(self, key: str) -> Path:
        name = key.rpartition("/")[2]
        if not _KEY.fullmatch(key) or name in (".", ".."):
            raise ValueError(f"原文件的键格式不正确：{key}")
        return self._root / key


async def _read_chunks(handle: BinaryIO) -> AsyncIterator[bytes]:
    try:
        while chunk := await asyncio.to_thread(handle.read, _CHUNK):
            yield chunk
    finally:
        handle.close()


def _remove_if_empty(directory: Path) -> None:
    with contextlib.suppress(OSError):  # 不存在或还有文件
        directory.rmdir()
