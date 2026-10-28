"""知识库文档（设计文档 8.2）：登记、存原文件、后台处理（解析 → 切块 → 向量化写入）、
删除与重新处理。

处理在后台任务里进行：每次只向量化少数几段（本机向量模型一次只处理一个请求，
对话里的查询要排在后面，批太大会让查询久等）；进度写进登记表，页面据此显示。
"""

import asyncio
import hashlib
import logging
import re
from collections.abc import AsyncIterator, Callable
from pathlib import PurePath, PurePosixPath
from uuid import UUID

from agents.main_agent.knowledge.base import KnowledgeStore
from agents.main_agent.knowledge.blobs import BlobStore
from agents.main_agent.knowledge.chunking import chunk_markdown
from agents.main_agent.knowledge.documents import DocumentRepo, KnowledgeDocument
from agents.main_agent.knowledge.parsing import (
    EMPTY_FILE,
    DocumentParseError,
    DocumentParser,
    unsupported_reason,
)
from agents.main_agent.workspace import OpenedFile
from common.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    UnsupportedError,
    UpstreamError,
)
from common.ids import new_id

logger = logging.getLogger(__name__)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NAME_BYTES = 200  # 文件系统限制文件名不超过 255 字节，留出余量（存的时候还要加 .part）
_MAX_INTERRUPTIONS = 2


class DocumentLibrary:
    def __init__(
        self,
        documents: DocumentRepo,
        store: KnowledgeStore,
        parser: DocumentParser,
        blobs: BlobStore,
        *,
        chunk_tokens: int = 600,
        overlap_tokens: int = 80,
        batch_size: int = 2,
        max_bytes: int,
    ) -> None:
        self._documents = documents
        self._store = store
        self._parser = parser
        self._blobs = blobs
        self._chunk_tokens = chunk_tokens
        self._overlap_tokens = overlap_tokens
        self._batch_size = batch_size
        self._max_bytes = max_bytes

    async def add(
        self,
        filename: str,
        chunks: AsyncIterator[bytes],
        *,
        media_type: str,
        source_thread_id: UUID | None = None,
    ) -> KnowledgeDocument:
        """登记一份文档并存下原文件（状态"待处理"）；处理由调用方另行登记后台任务。"""
        name = _safe_name(filename)
        if (reason := unsupported_reason(name)) is not None:
            raise UnsupportedError(reason)
        document_id = new_id()
        key = f"{document_id}/{name}"
        digest = hashlib.sha256()
        size = await self._blobs.save(
            key, _hashing(chunks, digest.update), max_bytes=self._max_bytes
        )
        try:
            if size == 0:
                # 空文件当场说清楚：所有空文件的哈希都一样，进了查重会被当成重复（审查 Minor 1）
                raise InvalidRequestError(EMPTY_FILE)
            # 同一内容只留一份（积压小问题 C12）：改了名也认得出；内容不同的同名文件照常加入
            same = await self._documents.find_by_hash(digest.hexdigest())
            if same is not None:
                raise ConflictError(
                    f"《{same.filename}》已在知识库里（内容相同），要更新请先删除旧的"
                )
            return await self._documents.create(
                document_id=document_id,
                title=PurePath(name).stem,
                filename=name,
                media_type=media_type,
                size=size,
                blob_key=key,
                content_hash=digest.hexdigest(),
                source_thread_id=source_thread_id,
            )
        except BaseException:  # 没登记上（重复、登记失败）时不留下没人认领的原文件
            await self._blobs.delete(key)
            raise

    async def backfill_hashes(self) -> int:
        """给还没有内容哈希的文档（升级前加入的，或从升级前的备份恢复的）补算，返回补了几份。

        每次启动都调，没有要补的就只是一次查询。原文件丢了、读不出的记个占位（空字符串）：
        它只是挡不住重复，之后不再每次去读、每次警告；意料之外的错误只跳过这一份，下次启动再试。
        """
        filled = 0
        for document_id, key in await self._documents.without_hash():
            try:
                data = await self._blobs.read(key)
            except (NotFoundError, OSError) as exc:
                logger.warning("文档 %s 的原文件读不出来，没法补算内容哈希：%s", document_id, exc)
                await self._documents.set_hash(document_id, "")
                continue
            except Exception:  # 补算边界：一份出意外不能挡住后面的（审查 Minor 2）
                logger.exception("补算文档 %s 的内容哈希时出错", document_id)
                continue
            await self._documents.set_hash(document_id, hashlib.sha256(data).hexdigest())
            filled += 1
        return filled

    async def list_documents(self) -> list[KnowledgeDocument]:
        return await self._documents.list_documents()

    async def get(self, document_id: UUID) -> KnowledgeDocument:
        return await self._documents.get(document_id)

    async def open(self, document_id: UUID) -> OpenedFile:
        return await self._blobs.open(await self._documents.blob_key(document_id))

    async def delete(self, document_id: UUID) -> None:
        """先删登记（片段随外键删除），再删原文件。"""
        key = await self._documents.blob_key(document_id)
        await self._documents.delete(document_id)
        await self._blobs.delete(key)

    async def reprocess(self, document_id: UUID) -> KnowledgeDocument:
        """改回"待处理"（清空原因）；由调用方另行登记后台任务。"""
        document = await self._documents.get(document_id)
        if document.status == "processing":
            raise ConflictError("文档正在处理，请稍后再试")
        await self._documents.update_status(document_id, "pending")
        return await self._documents.get(document_id)

    async def ingest(self, document_id: UUID) -> None:
        """处理一份文档。失败只改状态并写明原因，不抛出：后台任务不必重试，用户点"重新处理"。"""
        try:
            document = await self._documents.get(document_id)
        except NotFoundError:
            return  # 处理前就被删了
        if document.status in ("done", "failed"):
            # 重复登记的任务（"等待处理"时又点了重新处理）：已经做完的不再整份重做（C9）；
            # 要重做先点"重新处理"，它会把状态改回"待处理"
            return
        if document.status == "processing":
            # 上次处理到一半服务停了（重启，或文件大到把服务撑崩）：接着做一次；
            # 再次中断就放弃，免得每次启动都重做、反复撑崩服务
            interruptions = await self._documents.count_interruption(document_id)
            if interruptions >= _MAX_INTERRUPTIONS:
                await self._fail(
                    document_id,
                    "处理时服务中断了两次：文件可能太大或太复杂；可以拆小后重新上传，"
                    "或点\u201c重新处理\u201d再试",
                )
                return
        await self._documents.update_status(document_id, "processing", chunk_total=0, item_count=0)
        written = 0
        try:
            data = await self._blobs.read(await self._documents.blob_key(document_id))
            parsed = await self._parser.parse(data, document.filename)
            chunks = await asyncio.to_thread(
                chunk_markdown,
                parsed.markdown,
                target_tokens=self._chunk_tokens,
                overlap_tokens=self._overlap_tokens,
            )
            await self._documents.update_status(
                document_id, "processing", chunk_total=len(chunks), item_count=0
            )
            await self._store.delete_chunks(document_id)  # 重新处理、重启后重做都不重复
            for start in range(0, len(chunks), self._batch_size):
                batch = chunks[start : start + self._batch_size]
                await self._store.add_chunks(document_id, document.title, batch)
                written += len(batch)
                await self._documents.update_status(document_id, "processing", item_count=written)
        except DocumentParseError as exc:
            await self._fail(document_id, str(exc))
            return
        except UpstreamError as exc:
            await self._fail(document_id, f"{exc}；向量模型恢复后点“重新处理”")
            return
        except NotFoundError:
            if await self._exists(document_id):
                await self._fail(document_id, "原文件不见了：请删除后重新上传")
            return  # 否则是处理途中文档被删了
        except Exception:  # 处理边界：意料之外的错误也要落到"失败"，不能一直停在"处理中"
            logger.exception("文档 %s 处理时出错", document_id)
            await self._fail(document_id, "处理时出错：请点\u201c重新处理\u201d再试")
            return
        await self._documents.update_status(document_id, "done", item_count=written)

    async def _fail(self, document_id: UUID, reason: str) -> None:
        logger.warning("文档 %s 处理失败：%s", document_id, reason)
        await self._documents.update_status(document_id, "failed", error=reason)

    async def _exists(self, document_id: UUID) -> bool:
        try:
            await self._documents.get(document_id)
        except NotFoundError:
            return False
        return True


async def _hashing(
    chunks: AsyncIterator[bytes], update: Callable[[bytes], None]
) -> AsyncIterator[bytes]:
    """边存边算哈希：不用把整个文件读进内存再算。"""
    async for chunk in chunks:
        update(chunk)
        yield chunk


def _safe_name(filename: str) -> str:
    """只留文件名本身：去掉目录部分、控制字符和开头的点；超过 200 字节的保留开头与后缀。"""
    name = _CONTROL.sub("", PurePosixPath(filename.replace("\\", "/")).name).lstrip(". ")
    if not name:
        return "未命名"
    if len(name.encode()) <= _NAME_BYTES:
        return name
    suffix = PurePath(name).suffix
    budget = _NAME_BYTES - len(suffix.encode())
    stem = name[: -len(suffix)] if suffix else name
    while len(stem.encode()) > budget:
        stem = stem[:-1]
    return stem + suffix
