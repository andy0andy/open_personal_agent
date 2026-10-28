"""知识库文档接口（设计文档 8.2、11.2）：上传、处理、列表、下载原文、重新处理、删除；
片段的前后文；会话文件加入知识库。处理由测试直接调用（接口只负责登记后台任务）。"""

import uuid
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import pytest
from httpx import AsyncClient

from agents.main_agent.knowledge import (
    DocumentLibrary,
    DocumentRepo,
    LocalDiskBlobStore,
    MarkItDownParser,
    PgKnowledgeStore,
)
from agents.tests.fakes import FakeEmbedder, ScriptedChatModel
from backend.runtime import JobHandler
from backend.tests.conftest import ClientFactory
from common.db import Pool

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).resolve().parents[2] / "agents" / "tests" / "fixtures" / "documents"
VOCABULARY = ["报销", "请假", "退款"]


class _RecordingQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, kind: str, payload: dict[str, Any]) -> UUID:
        self.enqueued.append((kind, payload))
        return uuid.uuid4()

    async def start(self, handlers: Mapping[str, JobHandler]) -> None:
        pass

    async def stop(self) -> None:
        pass


class _Setup:
    def __init__(self, db: Pool, tmp_path: Path, **options: Any) -> None:
        self.store = PgKnowledgeStore(db, FakeEmbedder(VOCABULARY))
        self.library = DocumentLibrary(
            DocumentRepo(db),
            self.store,
            MarkItDownParser(),
            LocalDiskBlobStore(tmp_path / "knowledge"),
            **{"max_bytes": 50 * 1024 * 1024, **options},
        )
        self.queue = _RecordingQueue()

    def client(self, make_client: ClientFactory) -> Any:
        return make_client(
            ScriptedChatModel(responses=[]),
            knowledge=self.store,
            documents=self.library,
            document_queue=self.queue,
        )


async def _upload(client: AsyncClient, name: str, data: bytes | None = None) -> Any:
    return await client.post(
        "/api/knowledge/documents",
        content=data if data is not None else (SAMPLES / name).read_bytes(),
        headers={"X-File-Name": quote(name), "Content-Type": "application/octet-stream"},
    )


async def test_upload_then_process_then_search(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    setup = _Setup(db, tmp_path)
    async with setup.client(make_client) as client:
        uploaded = await _upload(client, "员工手册.docx", (SAMPLES / "handbook.docx").read_bytes())
        assert uploaded.status_code == 201, uploaded.text
        document = uploaded.json()
        assert (document["status"], document["title"]) == ("pending", "员工手册")
        assert setup.queue.enqueued == [("document_ingest", {"document_id": document["id"]})]

        await setup.library.ingest(UUID(document["id"]))
        done = (await client.get(f"/api/knowledge/documents/{document['id']}")).json()
        assert done["status"] == "done"
        assert [d["id"] for d in (await client.get("/api/knowledge/documents")).json()] == [
            document["id"]
        ]
        hits = await client.get(
            "/api/knowledge/items", params={"kind": "document_chunk", "q": "报销"}
        )
        assert hits.json()[0]["document_id"] == document["id"]


async def test_unsupported_file_is_refused(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    setup = _Setup(db, tmp_path)
    async with setup.client(make_client) as client:
        refused = await _upload(client, "old.doc")
        assert refused.status_code == 415
        assert "另存为" in refused.json()["detail"]
    assert setup.queue.enqueued == []


async def test_too_large_file_is_refused(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    setup = _Setup(db, tmp_path, max_bytes=10)
    async with setup.client(make_client) as client:
        assert (await _upload(client, "faq.html")).status_code == 413


async def test_declared_size_over_the_limit_is_refused_before_reading(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    """请求头声明的大小已超过上限：不读请求体就拒绝（积压小问题 C5，原来要先传满上限才报错）。"""
    read = False

    async def body() -> AsyncIterator[bytes]:
        nonlocal read
        read = True
        yield b"x"

    setup = _Setup(db, tmp_path)
    async with setup.client(make_client) as client:
        refused = await client.post(
            "/api/knowledge/documents",
            content=body(),
            headers={
                "X-File-Name": "big.txt",
                "Content-Type": "application/octet-stream",
                "Content-Length": str(1024**4),  # 远超任何上限
            },
        )
    assert refused.status_code == 413
    assert read is False
    assert setup.queue.enqueued == []


async def test_same_content_twice_is_refused_on_both_paths(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    """同一内容第二次加入（知识库页上传、会话文件"加入知识库"两条路）都 409，
    不留原文件（积压小问题 C12）。"""
    setup = _Setup(db, tmp_path)
    data = (SAMPLES / "faq.html").read_bytes()
    async with setup.client(make_client) as client:
        first = await _upload(client, "faq.html", data)
        assert first.status_code == 201
        again = await _upload(client, "常见问题.html", data)  # 改了名也认得出
        assert again.status_code == 409
        assert again.json()["detail"] == "《faq.html》已在知识库里（内容相同），要更新请先删除旧的"

        thread = (await client.post("/api/threads", json={})).json()
        file = (
            await client.post(
                f"/api/threads/{thread['id']}/files",
                content=data,
                headers={"X-File-Name": "faq.html", "Content-Type": "application/octet-stream"},
            )
        ).json()
        joined = await client.post(
            f"/api/threads/{thread['id']}/files/{file['id']}/knowledge", json={}
        )
        assert joined.status_code == 409
        listed = (await client.get("/api/knowledge/documents")).json()
    assert [d["id"] for d in listed] == [first.json()["id"]]
    assert len(setup.queue.enqueued) == 1
    blobs = [p for p in (tmp_path / "knowledge").rglob("*") if p.is_file()]
    assert len(blobs) == 1  # 被拒的那份原文件已删掉


async def test_same_name_with_different_content_is_allowed(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    setup = _Setup(db, tmp_path)
    async with setup.client(make_client) as client:
        assert (await _upload(client, "笔记.txt", "第一版".encode())).status_code == 201
        assert (await _upload(client, "笔记.txt", "第二版".encode())).status_code == 201


async def test_download_reprocess_and_delete(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    setup = _Setup(db, tmp_path)
    data = (SAMPLES / "faq.html").read_bytes()
    async with setup.client(make_client) as client:
        document = (await _upload(client, "faq.html")).json()
        url = f"/api/knowledge/documents/{document['id']}"
        await setup.library.ingest(UUID(document["id"]))

        content = await client.get(f"{url}/content")
        assert content.status_code == 200
        assert content.content == data
        assert content.headers["content-security-policy"] == "sandbox"
        assert content.headers["x-content-type-options"] == "nosniff"
        assert content.headers["content-disposition"] == "inline; filename*=UTF-8''faq.html"

        again = await client.post(f"{url}/reprocess", json={})
        assert (again.status_code, again.json()["status"]) == (200, "pending")
        assert len(setup.queue.enqueued) == 2

        assert (await client.delete(url)).status_code == 204
        assert (await client.get(url)).status_code == 404
        assert (await client.get(f"{url}/content")).status_code == 404
        chunks = await client.get("/api/knowledge/items", params={"kind": "document_chunk"})
        assert chunks.json() == []


async def test_context_of_a_chunk(make_client: ClientFactory, db: Pool, tmp_path: Path) -> None:
    setup = _Setup(db, tmp_path)
    async with setup.client(make_client) as client:
        document = (
            await _upload(client, "员工手册.docx", (SAMPLES / "handbook.docx").read_bytes())
        ).json()
        await setup.library.ingest(UUID(document["id"]))
        chunks = sorted(
            await setup.store.list_items(kind="document_chunk"), key=lambda item: item.seq or 0
        )
        assert len(chunks) >= 3
        middle = chunks[1]
        context = await client.get(
            f"/api/knowledge/items/{middle.id}/context", params={"window": 1}
        )
        body = context.json()
        assert body["target_id"] == str(middle.id)
        assert [item["seq"] for item in body["items"]] == [0, 1, 2]
        assert body["document"]["title"] == "员工手册"


async def test_context_of_a_missing_item_is_404(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    setup = _Setup(db, tmp_path)
    async with setup.client(make_client) as client:
        missing = await client.get(f"/api/knowledge/items/{uuid.uuid4()}/context")
        assert missing.status_code == 404


async def test_session_file_joins_the_knowledge_base(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    setup = _Setup(db, tmp_path)
    async with setup.client(make_client) as client:
        thread = (await client.post("/api/threads", json={})).json()
        other = (await client.post("/api/threads", json={})).json()
        file = (
            await client.post(
                f"/api/threads/{thread['id']}/files",
                content=(SAMPLES / "sales.xlsx").read_bytes(),
                headers={"X-File-Name": "sales.xlsx", "Content-Type": "application/octet-stream"},
            )
        ).json()
        joined = await client.post(
            f"/api/threads/{thread['id']}/files/{file['id']}/knowledge", json={}
        )
        assert joined.status_code == 201, joined.text
        document = joined.json()
        assert (document["title"], document["source_thread_id"]) == ("sales", thread["id"])
        assert setup.queue.enqueued == [("document_ingest", {"document_id": document["id"]})]
        wrong = await client.post(
            f"/api/threads/{other['id']}/files/{file['id']}/knowledge", json={}
        )
        assert wrong.status_code == 404  # 别的会话的文件

        assert (await client.delete(f"/api/threads/{thread['id']}")).status_code == 204
        kept = await client.get(f"/api/knowledge/documents/{document['id']}")
        assert kept.status_code == 200  # 删除会话不删它加入知识库的文档
