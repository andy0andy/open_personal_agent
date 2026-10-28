"""组装根：按配置选择各接口的具体实现，产出主智能体总入口。"用哪个实现"的决定只出现在这里。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.main_agent.conversations import PgConversationIndex
from agents.main_agent.integrations import McpAdaptersClient, McpClient
from agents.main_agent.knowledge import (
    BlobStore,
    DocumentLibrary,
    DocumentParser,
    DocumentRepo,
    KnowledgeStore,
    LocalDiskBlobStore,
    MarkItDownParser,
    PgKnowledgeStore,
)
from agents.main_agent.knowledge.tokens import warm_up
from agents.main_agent.models import (
    Embedder,
    EmbeddingUsage,
    LiteLLMProxyEmbedder,
    LiteLLMProxyGateway,
    ModelGateway,
    current_call,
)
from agents.main_agent.runtime import MainAgent, SkillCatalog, UsageReported
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import LocalSandbox, LocalWorkspace, Workspace
from common.db import Pool
from common.errors import UpstreamError
from config import Settings

logger = logging.getLogger(__name__)

_MODEL_GATEWAYS: dict[str, Callable[[Settings], ModelGateway]] = {
    "litellm_proxy": lambda s: LiteLLMProxyGateway(
        s.litellm_base_url,
        s.litellm_master_key.get_secret_value(),
        stream_idle_timeout=s.agent.stream_idle_timeout,
    ),
}

_WORKSPACES: dict[str, Callable[[Settings], Workspace]] = {
    "local": lambda s: LocalWorkspace(
        s.workdata_dir,
        LocalSandbox(
            s.workdata_dir / "workspace",
            default_timeout=s.workspace.command_timeout,
            max_timeout=s.workspace.max_command_timeout,
        ),
    ),
}


type UsageRecorder = Callable[[EmbeddingUsage], Awaitable[None]]

_EMBEDDERS: dict[str, Callable[[Settings, UsageRecorder], Embedder]] = {
    "litellm_proxy": lambda s, on_usage: LiteLLMProxyEmbedder(
        s.litellm_base_url,
        s.litellm_master_key.get_secret_value(),
        s.knowledge.embedding_model,
        on_usage=on_usage,
    ),
}

EMBEDDING = "embedding"  # 用量表里向量化调用的调用方


def _embedding_usage(pool: Pool) -> UsageRecorder:
    """向量化的用量写进用量表（设计文档 7.7）；对话中找相关记忆时记在那次运行名下。"""
    usage = UsageRepo(pool)

    async def record(item: EmbeddingUsage) -> None:
        call = current_call()
        await usage.add(
            thread_id=_uuid(call.thread_id) if call else None,
            run_id=_uuid(call.run_id) if call and call.run_id else None,
            usage=UsageReported(
                caller=EMBEDDING,
                requested_model=item.model,
                actual_model=item.model,
                input_tokens=item.input_tokens,
                output_tokens=0,
                duration_ms=item.duration_ms,
            ),
        )

    return record


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


_KNOWLEDGE_STORES: dict[str, Callable[[Pool, Embedder], KnowledgeStore]] = {
    "pgvector": PgKnowledgeStore,
}


_DOC_PARSERS: dict[str, Callable[[Settings], DocumentParser]] = {
    "markitdown": lambda s: MarkItDownParser(),
}

_BLOB_STORES: dict[str, Callable[[Settings], BlobStore]] = {
    "local_disk": lambda s: LocalDiskBlobStore(s.workdata_dir / "knowledge"),
}


_MCP_CLIENTS: dict[str, Callable[[Settings], McpClient]] = {
    "mcp_adapters": lambda s: McpAdaptersClient(),
}


async def build_agent(settings: Settings, pool: Pool) -> MainAgent:
    gateway = _MODEL_GATEWAYS[settings.adapters.model_gateway](settings)
    try:
        await gateway.list_models()  # 预取上下文长度等模型信息
    except UpstreamError:
        logger.warning("启动时模型网关不可用，稍后访问 /api/models 时会重试")
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    await asyncio.to_thread(warm_up)  # 预先加载分词词典，免得第一次检索时卡住服务约 1 秒
    options = settings.knowledge
    knowledge = _KNOWLEDGE_STORES[settings.adapters.knowledge_index](
        pool, _EMBEDDERS[settings.adapters.embedder](settings, _embedding_usage(pool))
    )
    documents = DocumentLibrary(
        DocumentRepo(pool),
        knowledge,
        _DOC_PARSERS[settings.adapters.doc_parser](settings),
        _BLOB_STORES[settings.adapters.blob_storage](settings),
        chunk_tokens=options.chunk_tokens,
        overlap_tokens=options.chunk_overlap_tokens,
        batch_size=options.ingest_batch_size,
        max_bytes=settings.max_upload_mb * 1024 * 1024,  # 与附件、技能包共用上限
    )
    return MainAgent(
        gateway=gateway,
        checkpointer=checkpointer,
        system_prompt=settings.agent.system_prompt_file.read_text(encoding="utf-8"),
        workspace=_WORKSPACES[settings.adapters.workspace](settings),
        skills=SkillCatalog(
            settings.skills_dir,
            settings.skills_state_file,
        ),
        subagents_dir=settings.agent.subagents_dir,
        knowledge=knowledge,
        knowledge_options=options,
        documents=documents,
        mcp=_MCP_CLIENTS[settings.adapters.mcp_client](settings),
        conversations=PgConversationIndex(pool),
    )
