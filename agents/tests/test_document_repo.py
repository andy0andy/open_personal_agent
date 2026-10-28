"""知识库文档登记（设计文档 11 节 knowledge_documents）：状态、进度；
删除文档时片段随外键一起删除。"""

import uuid

import pytest

from agents.main_agent.knowledge import DocumentRepo, NewKnowledge, PgKnowledgeStore
from agents.tests.fakes import FakeEmbedder
from common.db import Pool
from common.errors import NotFoundError

pytestmark = pytest.mark.integration

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def test_create_list_and_update_status(db: Pool) -> None:
    repo = DocumentRepo(db)
    first = await repo.create(
        document_id=uuid.uuid4(),
        title="员工手册",
        filename="员工手册.docx",
        media_type=DOCX,
        size=10,
        blob_key="k1",
    )
    second = await repo.create(
        document_id=uuid.uuid4(),
        title="设计",
        filename="设计.pdf",
        media_type="application/pdf",
        size=20,
        blob_key="k2",
    )
    assert (first.status, first.chunk_total, first.item_count, first.error) == (
        "pending",
        0,
        0,
        None,
    )
    assert [d.id for d in await repo.list_documents()] == [second.id, first.id]  # 新的在前

    await repo.update_status(first.id, "failed", error="原因")
    failed = await repo.get(first.id)
    assert (failed.status, failed.error) == ("failed", "原因")

    await repo.update_status(first.id, "processing", chunk_total=30, item_count=12)
    processing = await repo.get(first.id)
    assert (processing.status, processing.error) == ("processing", None)  # 原因随新状态清掉
    assert (processing.chunk_total, processing.item_count) == (30, 12)
    await repo.update_status(first.id, "done", item_count=30)
    done = await repo.get(first.id)
    assert (done.status, done.chunk_total, done.item_count) == ("done", 30, 30)  # 没给的不变
    assert await repo.blob_key(first.id) == "k1"


async def test_deleting_a_document_removes_its_chunks(db: Pool) -> None:
    repo = DocumentRepo(db)
    document = await repo.create(
        document_id=uuid.uuid4(),
        title="设计",
        filename="设计.pdf",
        media_type="application/pdf",
        size=20,
        blob_key="k",
    )
    store = PgKnowledgeStore(db, FakeEmbedder())
    item = await store.add(NewKnowledge(content="一段内容", source="manual"))
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE knowledge_items SET kind = 'document_chunk', document_id = %s WHERE id = %s",
            (document.id, item.id),
        )
    await repo.delete(document.id)
    with pytest.raises(NotFoundError):
        await store.get(item.id)


async def test_missing_document_is_not_found(db: Pool) -> None:
    repo = DocumentRepo(db)
    missing = uuid.uuid4()
    with pytest.raises(NotFoundError):
        await repo.get(missing)
    with pytest.raises(NotFoundError):
        await repo.blob_key(missing)
    with pytest.raises(NotFoundError):
        await repo.delete(missing)
