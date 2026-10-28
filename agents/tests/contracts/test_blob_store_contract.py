"""原文件存储契约测试（设计文档 4.2 的 blob_storage）：所有 BlobStore 实现都必须通过同一套测试。"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agents.main_agent.knowledge import BlobStore, LocalDiskBlobStore
from common.errors import NotFoundError, TooLargeError

KEY = f"{uuid.UUID(int=7)}/员工手册.pdf"


@pytest.fixture(params=["local_disk"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> BlobStore:
    return LocalDiskBlobStore(tmp_path / "knowledge")


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def test_saves_reads_and_opens(store: BlobStore) -> None:
    assert await store.save(KEY, _chunks(b"ab", b"cd"), max_bytes=10) == 4
    assert await store.read(KEY) == b"abcd"
    opened = await store.open(KEY)
    assert opened.size == 4
    assert b"".join([chunk async for chunk in opened.chunks]) == b"abcd"


async def test_over_the_limit_leaves_nothing(store: BlobStore) -> None:
    with pytest.raises(TooLargeError):
        await store.save(KEY, _chunks(b"ab", b"cd"), max_bytes=3)
    with pytest.raises(NotFoundError):
        await store.open(KEY)


async def test_delete_is_idempotent(store: BlobStore) -> None:
    await store.save(KEY, _chunks(b"x"), max_bytes=10)
    await store.delete(KEY)
    await store.delete(KEY)
    with pytest.raises(NotFoundError):
        await store.read(KEY)


@pytest.mark.parametrize("key", ["../x", "/etc/passwd", f"{uuid.UUID(int=7)}/../../x", "x/y"])
async def test_keys_cannot_escape_the_root(store: BlobStore, key: str) -> None:
    with pytest.raises(ValueError, match="键"):
        await store.save(key, _chunks(b"x"), max_bytes=10)
