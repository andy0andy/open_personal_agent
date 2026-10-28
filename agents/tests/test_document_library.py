"""文档处理流程（设计文档 8.2）：登记、存原文件、解析、切块、分小批向量化写入、
失败带原因、重新处理。"""

import re
import shutil
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from agents.main_agent.knowledge import (
    DocumentLibrary,
    DocumentParser,
    DocumentRepo,
    LocalDiskBlobStore,
    MarkItDownParser,
    ParsedDocument,
    PgKnowledgeStore,
)
from agents.main_agent.models import Embedder
from agents.tests.fakes import FakeEmbedder
from common.db import Pool
from common.errors import (
    ConflictError,
    InvalidRequestError,
    TooLargeError,
    UnsupportedError,
    UpstreamError,
)

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).resolve().parent / "fixtures" / "documents"
VOCABULARY = ["报销", "请假", "订单"]


class _CountingEmbedder(FakeEmbedder):
    """记下每次请求向量化了几段。"""

    def __init__(self) -> None:
        super().__init__(VOCABULARY)
        self.batches: list[int] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(len(texts))
        return await super().embed(texts)


class _BrokenEmbedder(FakeEmbedder):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise UpstreamError("向量化服务不可用：连不上模型网关")


class _CountingParser(MarkItDownParser):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def parse(self, data: bytes, filename: str) -> ParsedDocument:
        self.calls += 1
        return await super().parse(data, filename)


type Factory = Callable[..., DocumentLibrary]


@pytest.fixture
def make(db: Pool, tmp_path: Path) -> Factory:
    blobs = LocalDiskBlobStore(tmp_path / "knowledge")

    def factory(
        *,
        embedder: Embedder | None = None,
        parser: DocumentParser | None = None,
        max_bytes: int = 50 * 1024 * 1024,
        chunk_tokens: int = 600,
    ) -> DocumentLibrary:
        return DocumentLibrary(
            DocumentRepo(db),
            PgKnowledgeStore(db, embedder or FakeEmbedder(VOCABULARY)),
            parser or MarkItDownParser(),
            blobs,
            chunk_tokens=chunk_tokens,
            max_bytes=max_bytes,
        )

    return factory


async def _stream(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def _upload(library: DocumentLibrary, name: str) -> UUID:
    data = (SAMPLES / name).read_bytes()
    document = await library.add(name, _stream(data), media_type="application/octet-stream")
    assert (document.status, document.title, document.size) == (
        "pending",
        Path(name).stem,
        len(data),
    )
    return document.id


async def test_ingest_makes_searchable_chunks_with_locations(make: Factory, db: Pool) -> None:
    library = make()
    document_id = await _upload(library, "handbook.docx")
    await library.ingest(document_id)
    document = await library.get(document_id)
    assert document.status == "done"
    assert document.item_count == document.chunk_total > 0
    hits = await PgKnowledgeStore(db, FakeEmbedder(VOCABULARY)).search("报销", top_k=1)
    assert hits[0].item.document_id == document_id
    assert "第二章 报销" in (hits[0].item.section_path or "")
    assert hits[0].item.document_title == "handbook"


async def test_embedding_requests_stay_small(make: Factory) -> None:
    """后台每次只向量化 2 段：本机向量模型一次只处理一个请求，对话里的查询不至于久等。"""
    embedder = _CountingEmbedder()
    library = make(embedder=embedder)
    document_id = await _upload(library, "design.pdf")
    await library.ingest(document_id)
    assert (await library.get(document_id)).status == "done"
    assert embedder.batches
    assert max(embedder.batches) <= 2


async def test_unparseable_file_fails_with_reason(make: Factory) -> None:
    library = make()
    document_id = await _upload(library, "scan.pdf")
    await library.ingest(document_id)
    document = await library.get(document_id)
    assert document.status == "failed"
    assert "没有提取到文字" in (document.error or "")


async def test_embedding_down_fails_with_hint_then_reprocess_works(make: Factory) -> None:
    broken = make(embedder=_BrokenEmbedder())
    document_id = await _upload(broken, "handbook.docx")
    await broken.ingest(document_id)
    failed = await broken.get(document_id)
    assert failed.status == "failed"
    assert "向量化服务不可用" in (failed.error or "")
    assert "重新处理" in (failed.error or "")

    healthy = make()
    reset = await healthy.reprocess(document_id)
    assert (reset.status, reset.error) == ("pending", None)
    await healthy.ingest(document_id)
    assert (await healthy.get(document_id)).status == "done"


async def test_reprocess_replaces_chunks(make: Factory, db: Pool) -> None:
    library = make()
    document_id = await _upload(library, "handbook.docx")
    await library.ingest(document_id)
    first = (await library.get(document_id)).item_count
    await library.reprocess(document_id)
    await library.ingest(document_id)
    store = PgKnowledgeStore(db, FakeEmbedder())
    chunks = await store.list_items(kind="document_chunk")
    assert len(chunks) == first == (await library.get(document_id)).item_count  # 没有重复片段


class _BrokenParser:
    async def parse(self, data: bytes, filename: str) -> ParsedDocument:
        raise RuntimeError("意料之外的错误")


async def test_unexpected_error_fails_with_a_reason(make: Factory) -> None:
    """意料之外的错误也不能让文档一直停在"处理中"：标为失败，可以重新处理。"""
    library = make(parser=_BrokenParser())
    document_id = await _upload(library, "faq.html")
    await library.ingest(document_id)
    failed = await library.get(document_id)
    assert failed.status == "failed"
    assert "重新处理" in (failed.error or "")
    assert (await library.reprocess(document_id)).status == "pending"


async def test_one_interruption_is_retried(make: Factory, db: Pool) -> None:
    """处理到一半服务重启（文档还是"处理中"）：重启后接着处理一次。"""
    library = make()
    document_id = await _upload(library, "faq.html")
    await DocumentRepo(db).update_status(document_id, "processing")
    await library.ingest(document_id)
    assert (await library.get(document_id)).status == "done"


async def test_interrupted_twice_fails_instead_of_retrying_forever(make: Factory, db: Pool) -> None:
    """处理时服务连续中断两次（如文件大到把服务撑崩）：标为失败并说明，不再在每次启动时重做。"""
    library = make()
    repo = DocumentRepo(db)
    document_id = await _upload(library, "faq.html")
    await repo.update_status(document_id, "processing")
    await repo.count_interruption(document_id)  # 上一次重启时已经接着处理过一次
    await library.ingest(document_id)
    failed = await library.get(document_id)
    assert failed.status == "failed"
    assert "中断" in (failed.error or "")
    await library.reprocess(document_id)  # 重新处理时清零
    await library.ingest(document_id)
    assert (await library.get(document_id)).status == "done"


async def test_long_chinese_filename_is_shortened(make: Factory) -> None:
    """文件名超过文件系统的 255 字节限制时截短（保留后缀），不能报错。"""
    library = make()
    name = "很长的文件名" * 30 + ".html"  # 约 540 字节
    data = (SAMPLES / "faq.html").read_bytes()
    document = await library.add(name, _stream(data), media_type="text/html")
    assert len(document.filename.encode()) <= 200
    assert document.filename.endswith(".html")


class _DeletingParser:
    """解析时文档被用户删掉了。"""

    def __init__(self, library: Callable[[], DocumentLibrary]) -> None:
        self._library = library
        self.document_id: UUID | None = None

    async def parse(self, data: bytes, filename: str) -> ParsedDocument:
        assert self.document_id is not None
        await self._library().delete(self.document_id)
        return ParsedDocument(markdown="# 标题\n\n正文。")


async def test_document_deleted_while_processing_stops_quietly(make: Factory, db: Pool) -> None:
    holder: dict[str, Any] = {}
    parser = _DeletingParser(lambda: holder["library"])
    library = make(parser=parser)
    holder["library"] = library
    document_id = await _upload(library, "faq.html")
    parser.document_id = document_id
    await library.ingest(document_id)  # 不抛异常
    assert await library.list_documents() == []
    assert await PgKnowledgeStore(db, FakeEmbedder()).list_items(kind="document_chunk") == []


async def test_unsupported_or_too_large_files_are_refused(make: Factory, tmp_path: Path) -> None:
    library = make(max_bytes=10)
    with pytest.raises(UnsupportedError, match="另存为"):
        await library.add("old.doc", _stream(b"x"), media_type="application/msword")
    with pytest.raises(TooLargeError):
        await library.add("big.txt", _stream(b"x" * 11), media_type="text/plain")
    assert await library.list_documents() == []
    assert list((tmp_path / "knowledge").rglob("*.*")) == []  # 没有残留的原文件


async def test_duplicate_job_after_done_is_skipped(make: Factory) -> None:
    """同一份文档登记了两个处理任务（"等待处理"时又点了重新处理）：
    做完后第二个直接跳过（积压小问题 C9）。"""
    parser = _CountingParser()
    library = make(parser=parser)
    document_id = await _upload(library, "handbook.docx")
    await library.ingest(document_id)
    await library.ingest(document_id)
    assert parser.calls == 1
    assert (await library.get(document_id)).status == "done"


async def test_adding_the_same_content_twice_is_refused(make: Factory, tmp_path: Path) -> None:
    """内容完全相同（SHA-256）的文件再加一次：拒绝，并删掉刚存下的原文件（积压小问题 C12）。"""
    library = make()
    await _upload(library, "handbook.docx")
    data = (SAMPLES / "handbook.docx").read_bytes()
    with pytest.raises(ConflictError, match=re.escape("《handbook.docx》已在知识库里（内容相同）")):
        await library.add("员工手册.docx", _stream(data), media_type="application/octet-stream")
    assert len(await library.list_documents()) == 1
    assert len([p for p in (tmp_path / "knowledge").rglob("*") if p.is_file()]) == 1


async def test_same_name_different_content_is_allowed(make: Factory) -> None:
    library = make()
    for text in ("第一版", "第二版"):
        await library.add("笔记.txt", _stream(text.encode()), media_type="text/plain")
    assert len(await library.list_documents()) == 2


async def test_old_documents_get_their_hash_filled_in(
    make: Factory, db: Pool, tmp_path: Path
) -> None:
    """升级前加入的文档没有哈希：补算后同样挡得住；原文件丢了的跳过，不报错（积压小问题 C12）。"""
    library = make()
    kept = await _upload(library, "handbook.docx")
    lost = await _upload(library, "faq.html")
    async with db.connection() as conn:
        await conn.execute("UPDATE knowledge_documents SET content_hash = NULL")
    shutil.rmtree(tmp_path / "knowledge" / str(lost))  # 原文件丢了
    assert await library.backfill_hashes() == 1
    data = (SAMPLES / "handbook.docx").read_bytes()
    with pytest.raises(ConflictError):
        await library.add("again.docx", _stream(data), media_type="application/octet-stream")
    assert {d.id for d in await library.list_documents()} == {kept, lost}
    # 原文件丢了的记个占位，之后每次启动不再重复去读、重复警告（审查 Minor 3）
    assert await library.backfill_hashes() == 0
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM knowledge_documents WHERE content_hash IS NULL"
        )
        row = await cur.fetchone()
    assert row is not None
    assert row["n"] == 0


class _OneBadBlob(LocalDiskBlobStore):
    """读某一份原文件时出意料之外的错。"""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.bad: str | None = None

    async def read(self, key: str) -> bytes:
        if key == self.bad:
            raise RuntimeError("意外")
        return await super().read(key)


async def test_one_unexpected_failure_does_not_stop_the_backfill(db: Pool, tmp_path: Path) -> None:
    """补算时一份出了意外错误：记日志、跳过它，后面的照补（审查 Minor 2）；它下次启动再试。"""
    blobs = _OneBadBlob(tmp_path / "knowledge")
    library = DocumentLibrary(
        DocumentRepo(db),
        PgKnowledgeStore(db, FakeEmbedder(VOCABULARY)),
        MarkItDownParser(),
        blobs,
        max_bytes=50 * 1024 * 1024,
    )
    first = await _upload(library, "handbook.docx")
    await _upload(library, "faq.html")
    async with db.connection() as conn:
        await conn.execute("UPDATE knowledge_documents SET content_hash = NULL")
    blobs.bad = await DocumentRepo(db).blob_key(first)
    assert await library.backfill_hashes() == 1
    blobs.bad = None
    assert await library.backfill_hashes() == 1  # 意外的那份下次再试


async def test_empty_file_is_refused_at_once(make: Factory, tmp_path: Path) -> None:
    """空文件当场就说"文件是空的"，不登记、不留原文件（审查 Minor 1：原来第二个空文件被当成重复，
    提示的是第一个空文件的名字）。"""
    library = make()
    for name in ("会议纪要.md", "周报.txt"):
        with pytest.raises(InvalidRequestError, match="文件是空的：没有内容可以加入知识库"):
            await library.add(name, _stream(b""), media_type="text/plain")
    assert await library.list_documents() == []
    assert [p for p in (tmp_path / "knowledge").rglob("*") if p.is_file()] == []
