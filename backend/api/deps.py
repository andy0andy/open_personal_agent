"""接口层依赖：服务对象在启动时装配到 app.state.services。"""

from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from agents.main_agent.runtime import MainAgent
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import WorkspaceFileRepo
from backend.knowledge import DocumentJobs
from backend.models import ModelAdmin
from backend.runs import RunFollowups, RunManager, RunRepo
from backend.runtime import EventBus, InMemoryEventBus, InProcessRunControl, JobQueue, TableJobQueue
from backend.settings import IntegrationSettings
from backend.settings.app_settings import AppSettingsRepo, AppSettingsService
from backend.threads import ThreadRepo
from common.db import Pool
from config import Settings


@dataclass(frozen=True)
class Services:
    settings: Settings
    agent: MainAgent
    threads: ThreadRepo
    runs: RunRepo
    usage: UsageRepo
    files: WorkspaceFileRepo
    manager: RunManager
    jobs: JobQueue
    followups: RunFollowups
    document_queue: JobQueue  # 文档处理单独一条队列
    document_jobs: DocumentJobs
    integrations: IntegrationSettings  # 可重新加载的 MCP 服务清单与审批规则
    models: ModelAdmin  # 模型页（D21）
    app_settings: AppSettingsService  # 设置页的设置（D22）


def build_services(
    settings: Settings,
    pool: Pool,
    agent: MainAgent,
    *,
    bus: EventBus | None = None,
    jobs: JobQueue | None = None,
    document_queue: JobQueue | None = None,
) -> Services:
    threads = ThreadRepo(pool)
    runs = RunRepo(pool)
    usage = UsageRepo(pool)
    files = WorkspaceFileRepo(pool)
    jobs = jobs or TableJobQueue(pool)
    document_queue = document_queue or TableJobQueue(pool)
    followups = RunFollowups(
        runs=runs,
        threads=threads,
        usage=usage,
        agent=agent,
        jobs=jobs,
        auto_extract=settings.knowledge.auto_extract,
    )
    manager = RunManager(
        runs=runs,
        threads=threads,
        usage=usage,
        files=files,
        agent=agent,
        bus=bus or InMemoryEventBus(),
        control=InProcessRunControl(),
        followups=followups,
    )
    app_settings = AppSettingsService(settings, AppSettingsRepo(pool))
    return Services(
        settings=settings,
        agent=agent,
        threads=threads,
        runs=runs,
        usage=usage,
        files=files,
        manager=manager,
        jobs=jobs,
        followups=followups,
        document_queue=document_queue,
        document_jobs=DocumentJobs(agent.documents, document_queue),
        models=ModelAdmin(settings, agent.models, threads, app_settings, runs),
        integrations=IntegrationSettings(settings, agent, runs),
        app_settings=app_settings,
    )


def get_services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


ServicesDep = Annotated[Services, Depends(get_services)]
