"""知识库接口（设计文档 8.4、11.2）：条目的筛选与检索、手动添加、修改、删除；常驻条目汇总；
文档的上传、列表、原文、重新处理、删除；片段的前后文（回答里的出处点开时用）。"""

from typing import Annotated
from urllib.parse import quote, unquote
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from agents.main_agent.knowledge import (
    DocumentLibrary,
    KnowledgeDocument,
    KnowledgeItem,
    KnowledgeKind,
    KnowledgeStore,
    KnowledgeText,
    NewKnowledge,
    pinned_room,
)
from agents.main_agent.workspace import media_type
from backend.api.deps import Services, ServicesDep
from common.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    TooLargeError,
    UpstreamError,
)

knowledge_router = APIRouter(prefix="/knowledge")


class KnowledgeCreate(BaseModel):
    """手动添加一条记忆。"""

    content: KnowledgeText
    tags: list[str] = []
    pinned: bool = False


class KnowledgeUpdate(BaseModel):
    """修改条目：只改给出的字段。trusted：可疑的记忆确认无害（设计 2026-10-23 6.6）。"""

    content: KnowledgeText | None = None
    tags: list[str] | None = None
    pinned: bool | None = None
    trusted: bool | None = None


class PinnedSummary(BaseModel):
    """常驻条目（个人画像）：每次对话都会带上；总量有上限（硬限制，设计 2026-10-23 6.6）。"""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[KnowledgeItem]
    total_tokens: int
    token_limit: int


class ItemContext(BaseModel):
    """一个条目及其前后的片段（文档片段）；记忆条目只有它自己。"""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    target_id: UUID
    items: list[KnowledgeItem]
    document: KnowledgeDocument | None


def _library(services: Services) -> DocumentLibrary:
    if services.agent.documents is None:
        raise UpstreamError("知识库文档未启用：请检查设置页只读项里的 adapters.doc_parser")
    return services.agent.documents


def _store(services: Services) -> KnowledgeStore:
    if services.agent.knowledge is None:
        raise UpstreamError("知识库未启用：请检查设置页只读项里的 adapters.knowledge_index")
    return services.agent.knowledge


@knowledge_router.get("/items")
async def list_items(
    services: ServicesDep,
    kind: KnowledgeKind | None = None,
    tags: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI 的查询参数默认值，不会被修改
    pinned: bool | None = None,
    suspicious: bool | None = None,
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeItem]:
    """不带 q 时按时间倒序列出；带 q 时按相关程度检索（向量 + 关键词，忽略 offset）。
    可疑的记忆在页面上照常列出、检索得到（显示警告，设计 2026-10-23 6.6）；
    suspicious 为真只给可疑且没确认的（"可疑"视图）。"""
    store = _store(services)
    if not q.strip():
        return await store.list_items(
            kind=kind, tags=tags, pinned=pinned, flagged=suspicious, limit=limit, offset=offset
        )
    hits = await store.search(
        q, kinds=[kind] if kind else None, tags=tags, top_k=limit, include_suspicious=True
    )
    return [
        hit.item
        for hit in hits
        if (pinned is None or hit.item.pinned == pinned)
        and (suspicious is None or hit.item.flagged == suspicious)
    ]


@knowledge_router.post("/items", status_code=status.HTTP_201_CREATED)
async def add_item(body: KnowledgeCreate, services: ServicesDep) -> KnowledgeItem:
    store = _store(services)
    new = NewKnowledge(content=body.content, tags=body.tags, pinned=body.pinned, source="manual")
    if new.pinned:
        await _check_pinned_room(services, store, new.content)
    return await store.add(new)


@knowledge_router.patch("/items/{item_id}")
async def update_item(item_id: UUID, body: KnowledgeUpdate, services: ServicesDep) -> KnowledgeItem:
    """改成常驻、或改了常驻条目的内容时，放不下就 409；文档片段不能设为常驻、
    也不能单独改（422）。"""
    store = _store(services)
    current = await store.get(item_id)
    if current.kind == "document_chunk":
        if body.pinned:
            raise InvalidRequestError("文档片段不能设为常驻：常驻只放关于你的信息")
        # 片段跟着原文件走，重新处理时整份重切（积压小问题 C8）
        raise InvalidRequestError("文档片段不能单独修改：改原文件后重新上传")
    pinned = current.pinned if body.pinned is None else body.pinned
    content = current.content if body.content is None else body.content
    if pinned and (not current.pinned or content != current.content):
        await _check_pinned_room(services, store, content, exclude=item_id)
    return await store.update(
        item_id, content=body.content, tags=body.tags, pinned=body.pinned, trusted=body.trusted
    )


async def _check_pinned_room(
    services: Services, store: KnowledgeStore, content: str, *, exclude: UUID | None = None
) -> None:
    limit = services.settings.knowledge.pinned_token_limit
    refused = await pinned_room(store, limit, content, exclude=exclude)
    if refused:
        raise ConflictError(refused)


@knowledge_router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: UUID, services: ServicesDep) -> None:
    store = _store(services)
    if (await store.get(item_id)).kind == "document_chunk":
        raise InvalidRequestError("文档片段不能单独删除：请删除整份文档")  # 积压小问题 C8
    await store.delete(item_id)


@knowledge_router.get("/pinned")
async def pinned_summary(services: ServicesDep) -> PinnedSummary:
    items = await _store(services).pinned()
    return PinnedSummary(
        items=items,
        total_tokens=sum(item.token_count for item in items),
        token_limit=services.settings.knowledge.pinned_token_limit,
    )


@knowledge_router.get("/items/{item_id}/context")
async def item_context(
    item_id: UUID, services: ServicesDep, window: Annotated[int, Query(ge=0, le=5)] = 1
) -> ItemContext:
    """一个条目及其前后各 window 段（回答里的出处点开时显示）。"""
    items = await _store(services).around(item_id, window)
    target = next((item for item in items if item.id == item_id), None)
    if target is None:  # 两次查询之间被删或重新处理（片段换了 ID，积压小问题 C7）
        raise NotFoundError("这段内容已不在知识库里")
    document = None
    if target.document_id is not None and services.agent.documents is not None:
        try:
            document = await services.agent.documents.get(target.document_id)
        except NotFoundError:
            document = None
    return ItemContext(target_id=item_id, items=items, document=document)


@knowledge_router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"requestBody": {"content": {"application/octet-stream": {}}, "required": True}},
)
async def upload_document(
    request: Request,
    services: ServicesDep,
    x_file_name: Annotated[str, Header(description="文件名，按 UTF-8 百分号编码")],
) -> KnowledgeDocument:
    """上传文档到知识库：请求体就是文件内容，文件名放在 X-File-Name 请求头；登记后台处理任务。"""
    limit_mb = services.settings.max_upload_mb
    declared = request.headers.get("content-length")
    if declared is not None and int(declared) > limit_mb * 1024 * 1024:
        raise TooLargeError(f"文件超过 {limit_mb}MB 上限")  # 不必等传完再拒绝（积压小问题 C5）
    name = unquote(x_file_name)
    document = await _library(services).add(name, request.stream(), media_type=media_type(name))
    await services.document_jobs.submit(document.id)
    return document


@knowledge_router.get("/documents")
async def list_documents(services: ServicesDep) -> list[KnowledgeDocument]:
    return await _library(services).list_documents()


@knowledge_router.get("/documents/{document_id}")
async def get_document(document_id: UUID, services: ServicesDep) -> KnowledgeDocument:
    return await _library(services).get(document_id)


@knowledge_router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, services: ServicesDep) -> None:
    """删除文档：它的片段随之删除，回答里指向它的出处点开时显示"已不在知识库里"。"""
    await _library(services).delete(document_id)


@knowledge_router.post("/documents/{document_id}/reprocess")
async def reprocess_document(document_id: UUID, services: ServicesDep) -> KnowledgeDocument:
    """重新处理（如向量模型恢复后）；正在处理时返回 409。"""
    document = await _library(services).reprocess(document_id)
    await services.document_jobs.submit(document.id)
    return document


@knowledge_router.get(
    "/documents/{document_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def document_content(document_id: UUID, services: ServicesDep) -> Response:
    """文档原文件（在页面里打开，PDF 可在地址后加 #page=N 跳到某页）。边读边传。"""
    library = _library(services)
    document = await library.get(document_id)
    opened = await library.open(document_id)
    return StreamingResponse(
        opened.chunks,
        media_type=document.media_type,
        headers={
            "Content-Length": str(opened.size),
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(document.filename)}",
            # 上传的网页等直接打开时禁止脚本执行，也不让浏览器按内容猜类型
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )
