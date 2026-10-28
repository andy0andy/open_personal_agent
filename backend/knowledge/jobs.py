"""知识库文档的后台处理（设计文档 8.2）：单独一条任务队列，
几分钟的大文档不挡住会话标题、记忆提取。"""

from typing import Any
from uuid import UUID

from agents.main_agent.knowledge import DocumentLibrary
from backend.runtime import JobHandler, JobQueue

DOCUMENT_INGEST = "document_ingest"


class DocumentJobs:
    def __init__(self, library: DocumentLibrary | None, jobs: JobQueue) -> None:
        self._library = library
        self._jobs = jobs

    def handlers(self) -> dict[str, JobHandler]:
        return {DOCUMENT_INGEST: self._ingest}

    async def submit(self, document_id: UUID) -> None:
        """登记一份文档的处理任务（上传、重新处理、会话文件加入知识库之后）。"""
        await self._jobs.enqueue(DOCUMENT_INGEST, {"document_id": str(document_id)})

    async def _ingest(self, payload: dict[str, Any]) -> None:
        # 处理失败只改文档状态、写明原因，不抛出：后台不必重试，用户可点"重新处理"
        if self._library is not None:
            await self._library.ingest(UUID(payload["document_id"]))
