"""backend 接口测试夹具：真实数据库（postgres-test）+ 按剧本回复的假模型。"""

import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.conversations import ConversationIndex
from agents.main_agent.integrations import McpClient
from agents.main_agent.knowledge import DocumentLibrary, KnowledgeStore
from agents.main_agent.models import ModelGateway
from agents.main_agent.runtime import MainAgent, SkillCatalog
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox
from backend.api.deps import build_services
from backend.main import create_app
from backend.runtime import InMemoryEventBus, JobQueue
from common.db import Pool
from config import Settings
from config.settings import AgentConfig, KnowledgeConfig

type ClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def make_client(db: Pool) -> ClientFactory:
    """按给定的假模型（及可选的假网关）构造接口客户端；不走 lifespan，直接装配服务对象。"""

    @asynccontextmanager
    async def factory(
        model: BaseChatModel,
        gateway: ModelGateway | None = None,
        bus_retain_seconds: float = 60.0,
        bus: InMemoryEventBus | None = None,
        workspace: LocalWorkspace | None = None,
        upload_limit_mb: int = 50,
        knowledge: KnowledgeStore | None = None,
        documents: DocumentLibrary | None = None,
        document_queue: JobQueue | None = None,
        mcp: McpClient | None = None,
        skills_dir: Path | None = None,
        workdata: Path | None = None,
        skills: SkillCatalog | None = None,
        conversations: ConversationIndex | None = None,
        knowledge_config: KnowledgeConfig | None = None,
    ) -> AsyncIterator[AsyncClient]:
        settings = Settings(
            database_url="postgresql://unused",
            litellm_master_key="sk-test",
            # MCP 服务清单、审批规则、技能都在 .workdata 里（D22）：测试用临时目录，绝不碰本机的
            workdata_dir=workdata or Path(tempfile.mkdtemp(prefix="api-workdata-")),
            agent=AgentConfig(default_model="fake-model"),
            max_upload_mb=upload_limit_mb,
            knowledge=knowledge_config or KnowledgeConfig(),
        )
        agent = MainAgent(
            gateway=gateway or FakeGateway(model),
            checkpointer=InMemorySaver(),
            system_prompt="测试助手",
            workspace=workspace or LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
            knowledge=knowledge,
            knowledge_options=settings.knowledge,
            documents=documents,
            mcp=mcp,
            skills_dir=skills_dir,
            skills=skills,
            conversations=conversations,
        )
        app = create_app(lifespan_handler=None)
        bus = bus or InMemoryEventBus(retain_seconds=bus_retain_seconds)
        services = build_services(settings, db, agent, bus=bus, document_queue=document_queue)
        await services.integrations.load()  # 同 lifespan：读配置文件、连接 MCP 服务
        app.state.services = services
        # 界面每个请求都带本机令牌（D25）；测试默认也带上，要测没带的情况时自己去掉
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://localhost",
            headers={"X-Session-Token": app.state.session_token},
        ) as client:
            yield client

    return factory
