"""接口路由：会话、运行（含推送）、文件、用量、模型、知识库、健康检查。"""

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote, unquote
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from agents.main_agent.knowledge import KnowledgeDocument
from agents.main_agent.models import ModelInfo
from agents.main_agent.usage import ThreadUsage, UsageRecord
from agents.main_agent.workspace import WorkspaceFile, media_type
from backend.api.deps import Services, ServicesDep
from backend.api.knowledge import knowledge_router
from backend.api.local_guard import COOKIE
from backend.api.models import models_router
from backend.api.settings import settings_router
from backend.api.usage import usage_router
from backend.files import MAX_PREVIEW_BYTES, TablePreview, table_preview
from backend.runs import (
    ResumeRequest,
    RunCreate,
    RunHistory,
    RunInterject,
    RunRecord,
    ThreadCreated,
)
from backend.threads import (
    ConversationHitView,
    Thread,
    ThreadCreate,
    ThreadOrder,
    ThreadSearchResult,
    ThreadUpdate,
)
from backend.threads.export import to_markdown
from common.errors import InvalidRequestError, NotFoundError, TooLargeError, UpstreamError

api_router = APIRouter()
api_router.include_router(knowledge_router)
api_router.include_router(models_router)
api_router.include_router(settings_router)
api_router.include_router(usage_router)


@api_router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class SessionView(BaseModel):
    token: str


@api_router.get("/session")
async def session(request: Request, response: Response) -> SessionView:
    """发本机令牌（D25）：守卫只校验了 Host；同时下发同值的 Cookie，推送、图片、下载用它。"""
    token: str = request.app.state.session_token
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
    return SessionView(token=token)


@api_router.get("/models")
async def list_models(services: ServicesDep) -> list[ModelInfo]:
    return await services.agent.models.list_models()


@api_router.get("/threads")
async def list_threads(services: ServicesDep, archived: bool = False) -> list[Thread]:
    """会话列表；archived=true 时是归档的会话（设计 2026-10-23 6.5）。"""
    if archived:
        return await services.threads.list_archived()
    return await services.threads.list_active()


# 搜索词只取前这么多字：贴进来一大段也照常搜，不报错（审查 Minor 3）
_SEARCH_CHARS = 200


@api_router.get("/threads/search")
async def search_threads(
    services: ServicesDep, q: Annotated[str, Query(max_length=10_000)] = ""
) -> ThreadSearchResult:
    """会话搜索（设计 2026-10-23 6.1）：标题匹配（含已归档的）与内容里提到（会话索引）。
    要写在 /threads/{thread_id} 之前，否则 search 会被当成会话 ID。"""
    query = q.strip()[:_SEARCH_CHARS].strip()
    if not query:
        return ThreadSearchResult(titles=[], hits=[])
    conversations = services.agent.conversations
    hits = await conversations.search(query, limit=20) if conversations is not None else []
    return ThreadSearchResult(
        titles=await services.threads.search_titles(query),
        hits=[
            ConversationHitView(
                thread_id=hit.turn.thread_id,
                title=hit.turn.title,
                run_id=hit.turn.run_id,
                turn=hit.turn.turn,
                snippet=hit.snippet,
                terms=hit.terms,
            )
            for hit in hits
        ],
    )


@api_router.post("/threads", status_code=status.HTTP_201_CREATED)
async def create_thread(body: ThreadCreate, services: ServicesDep) -> ThreadCreated:
    """新建会话。带上第一条消息时一次完成（设计 2026-10-23 6.4）：设好模型和权限、发起运行；
    中途失败就删掉刚建的会话并返回原因，落地页不会留下空会话。"""
    if body.message is not None and body.model is not None:
        await services.models.require_chat(body.model)  # 模型不对时连会话都不建
    model = body.model or services.settings.agent.default_model
    thread = await services.threads.create(model=model, title=body.title)
    try:
        if body.permission_mode is not None and body.permission_mode != thread.permission_mode:
            thread = await services.threads.update(thread.id, permission_mode=body.permission_mode)
        run = None
        if body.message is not None:
            run = await services.manager.start(thread.id, RunCreate(message=body.message))
    except Exception:
        with contextlib.suppress(Exception):  # 删不掉也要把原来的原因报出去
            await services.manager.delete_thread(thread.id)
        raise
    return ThreadCreated(**thread.model_dump(), run=run)


@api_router.put("/threads/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_threads(body: ThreadOrder, services: ServicesDep) -> None:
    """保存左侧会话的自定义顺序（拖拽排序）。"""
    await services.threads.reorder(body.thread_ids)


@api_router.patch("/threads/{thread_id}")
async def update_thread(thread_id: UUID, body: ThreadUpdate, services: ServicesDep) -> Thread:
    """改会话的标题、模型或审批权限；模型必须是网关里的对话模型。"""
    if body.model is not None:
        await services.models.require_chat(body.model)
    thread = await services.threads.update(
        thread_id,
        title=body.title,
        model=body.model,
        permission_mode=body.permission_mode,
        archived=body.archived,
    )
    if body.title is not None and (conversations := services.agent.conversations) is not None:
        await conversations.retitle(thread_id, thread.title)  # 会话搜索里显示新标题
    return thread


@api_router.post("/threads/{thread_id}/viewed", status_code=status.HTTP_204_NO_CONTENT)
async def mark_viewed(thread_id: UUID, services: ServicesDep) -> None:
    """看过了这个会话：清掉"有新回答"（打开会话、运行结束时正看着它时调用，设计 6.5）。"""
    await services.threads.mark_viewed(thread_id)


@api_router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(thread_id: UUID, services: ServicesDep) -> None:
    """删除会话及其全部对话内容（用量记录保留）；正在运行时返回 409。"""
    await services.manager.delete_thread(thread_id)


@api_router.get("/threads/{thread_id}")
async def get_thread(thread_id: UUID, services: ServicesDep) -> Thread:
    return await services.threads.get(thread_id)


@api_router.get("/threads/{thread_id}/history")
async def thread_history(thread_id: UUID, services: ServicesDep) -> list[RunHistory]:
    await services.threads.get(thread_id)
    return await services.runs.history(thread_id)


@api_router.get("/threads/{thread_id}/export")
async def export_thread(
    thread_id: UUID,
    services: ServicesDep,
    tz: Annotated[str, Query(max_length=64)] = "UTC",
) -> Response:
    """导出 Markdown（设计 2026-10-23 6.2）：按界面历史生成，作为附件下载，文件名是会话标题。
    每轮的时间按 tz（浏览器所在时区）写。"""
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidRequestError(f"时区不认识：{tz}") from exc
    thread = await services.threads.get(thread_id)
    markdown = to_markdown(thread, await services.runs.history(thread_id), zone)
    # 标题里的斜杠一类在文件名里不能用
    name = quote(re.sub(r'[\\/:*?"<>|]', "_", thread.title or "新会话") + ".md")
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
    )


@api_router.get("/threads/{thread_id}/usage")
async def thread_usage(thread_id: UUID, services: ServicesDep) -> ThreadUsage:
    await services.threads.get(thread_id)
    return await services.usage.for_thread(thread_id)


@api_router.get("/threads/{thread_id}/files")
async def list_files(thread_id: UUID, services: ServicesDep) -> list[WorkspaceFile]:
    """会话里登记过的文件：上传与产物，按路径排序。"""
    await services.threads.get(thread_id)
    return await services.files.for_thread(thread_id)


@api_router.post(
    "/threads/{thread_id}/files",
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"requestBody": {"content": {"application/octet-stream": {}}, "required": True}},
)
async def upload_file(
    thread_id: UUID,
    request: Request,
    services: ServicesDep,
    x_file_name: Annotated[str, Header(description="文件名，按 UTF-8 百分号编码")],
) -> WorkspaceFile:
    """上传文件到会话的 uploads/：请求体就是文件内容，文件名放在 X-File-Name 请求头。"""
    thread = await services.threads.get(thread_id)
    limit_mb = services.settings.max_upload_mb
    declared = request.headers.get("content-length")
    if declared is not None and int(declared) > limit_mb * 1024 * 1024:
        raise TooLargeError(f"文件超过 {limit_mb}MB 上限")  # 不必等传完再拒绝
    saved = await services.agent.workspace.save_upload(
        thread.short_id, unquote(x_file_name), request.stream(), max_bytes=limit_mb * 1024 * 1024
    )
    return await services.files.record(
        thread.id, saved.path, source="upload", size=saved.size, media_type=media_type(saved.path)
    )


@api_router.get(
    "/threads/{thread_id}/files/{file_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def file_content(
    thread_id: UUID, file_id: UUID, services: ServicesDep, download: bool = False
) -> Response:
    """读取会话里的一个文件：默认在页面里直接显示，download=1 时作为附件下载。边读边传。"""
    thread, record = await _thread_file(services, thread_id, file_id)
    try:
        opened = await services.agent.workspace.open_file(thread.short_id, record.path)
    except (FileNotFoundError, PermissionError):
        # 登记之后被删掉、换成目录或换成指向会话目录外的链接
        raise NotFoundError("文件已不存在") from None
    name = quote(PurePosixPath(record.path).name)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        opened.chunks,
        media_type=record.media_type,
        headers={
            "Content-Length": str(opened.size),
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{name}",
            # 产物可能是智能体生成的 HTML / SVG：直接打开时禁止脚本执行，也不让浏览器按内容猜类型
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@api_router.post(
    "/threads/{thread_id}/files/{file_id}/knowledge", status_code=status.HTTP_201_CREATED
)
async def add_file_to_knowledge(
    thread_id: UUID, file_id: UUID, services: ServicesDep
) -> KnowledgeDocument:
    """把会话里的一个文件（上传的或智能体生成的）加入知识库，登记后台处理任务。"""
    if services.agent.documents is None:
        raise UpstreamError("知识库文档未启用：请检查设置页只读项里的 adapters.doc_parser")
    thread, record = await _thread_file(services, thread_id, file_id)
    try:
        opened = await services.agent.workspace.open_file(thread.short_id, record.path)
    except (FileNotFoundError, PermissionError):
        raise NotFoundError("文件已不存在") from None
    document = await services.agent.documents.add(
        PurePosixPath(record.path).name,
        opened.chunks,
        media_type=record.media_type,
        source_thread_id=thread.id,
    )
    await services.document_jobs.submit(document.id)
    return document


@api_router.get("/threads/{thread_id}/files/{file_id}/table")
async def file_table(
    thread_id: UUID, file_id: UUID, services: ServicesDep, sheet: str | None = None
) -> TablePreview:
    """CSV / Excel 文件的前若干行（表格预览）；sheet 为 Excel 的工作表名，缺省为第一个。"""
    thread, record = await _thread_file(services, thread_id, file_id)
    if record.size > MAX_PREVIEW_BYTES:
        raise TooLargeError("文件太大，无法预览，请下载查看")
    try:
        data = await services.agent.workspace.read_file(thread.short_id, record.path)
    except (FileNotFoundError, PermissionError):
        raise NotFoundError("文件已不存在") from None
    # 不能预览的原因（PreviewError）走统一的错误映射，回 422
    return await asyncio.to_thread(table_preview, record.path, data, sheet=sheet)


async def _thread_file(
    services: Services, thread_id: UUID, file_id: UUID
) -> tuple[Thread, WorkspaceFile]:
    """会话与其中登记过的一个文件；文件不属于该会话时同样是"不存在"。"""
    thread = await services.threads.get(thread_id)
    record = await services.files.get(file_id)
    if record.thread_id != thread.id:
        raise NotFoundError("文件不存在")
    return thread, record


@api_router.post("/threads/{thread_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(thread_id: UUID, body: RunCreate, services: ServicesDep) -> RunRecord:
    return await services.manager.start(thread_id, body)


async def existing_run(run_id: UUID, services: ServicesDep) -> RunRecord:
    """推送开始后就无法再返回 404，所以存在性检查必须放在依赖里，在响应开始前完成。"""
    return await services.runs.get(run_id)


@api_router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run: Annotated[RunRecord, Depends(existing_run)], services: ServicesDep
) -> RunRecord:
    """停止运行；已结束的运行返回 409。"""
    return await services.manager.cancel(run.id)


@api_router.post("/runs/{run_id}/interject", status_code=status.HTTP_202_ACCEPTED)
async def interject(run_id: UUID, body: RunInterject, services: ServicesDep) -> None:
    """运行中插话（设计 2026-10-23 6.3）：主智能体下一次调用模型前送达，送达时推 user.interjected。
    等审批时、运行已结束时 409。"""
    await services.manager.interject(run_id, body.message)


@api_router.post("/runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_run(
    run: Annotated[RunRecord, Depends(existing_run)], body: ResumeRequest, services: ServicesDep
) -> RunRecord:
    """提交审批决定，运行接着跑；没有在等待审批（或已提交过）返回 409，决定对不上返回 422。"""
    return await services.manager.resume(run.id, body)


@api_router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_run(
    run: Annotated[RunRecord, Depends(existing_run)], services: ServicesDep
) -> RunRecord:
    """ "重试这一轮"（D26）：从这次运行之前的存档分叉重跑，返回新运行；不能重试时返回 409。"""
    return await services.manager.retry(run.id)


@api_router.get("/runs/{run_id}/usage")
async def run_usage(
    run: Annotated[RunRecord, Depends(existing_run)], services: ServicesDep
) -> list[UsageRecord]:
    """一次运行里每次模型调用的明细。"""
    return await services.usage.for_run(run.id)


@api_router.get("/runs/{run_id}/events", response_class=EventSourceResponse)
async def run_events(
    run: Annotated[RunRecord, Depends(existing_run)],
    services: ServicesDep,
    last_event_id: Annotated[int | None, Header()] = None,
    after: Annotated[int, Query(ge=0)] = 0,
) -> AsyncIterator[ServerSentEvent]:
    """推送运行事件，从 after 之后开始（页面已从界面历史显示了前面的部分）。
    浏览器断线重连时会带上 Last-Event-ID（总在 after 之后），从该序号之后继续推送。"""
    after_seq = max(after, last_event_id or 0)
    async for event in services.manager.stream(run.id, after_seq=after_seq):
        yield ServerSentEvent(data=event.model_dump(mode="json"), id=str(event.seq))
