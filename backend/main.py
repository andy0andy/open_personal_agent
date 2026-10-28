"""FastAPI 入口：启动时创建连接池、组装智能体与服务对象。"""

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI

from agents.main_agent.bootstrap import build_agent
from backend.api import api_router
from backend.api.deps import Services, build_services
from backend.api.errors import install_error_handlers
from backend.api.local_guard import LocalGuard
from backend.frontend import FRONTEND_DIST, mount_frontend
from backend.logging_setup import configure_logging
from backend.settings.app_settings import AppSettingsRepo
from backend.settings.seed import (
    backfill_conversation_index_once,
    enable_prompt_caching_once,
    load_seed_models,
    migrate_config_files,
    seed_files_once,
    seed_models_once,
)
from common.db import create_pool
from config import get_settings
from config.settings import SEED_DIR, load_settings

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    env_settings = get_settings()
    # 最先配置日志：之后的日志都带时间、级别并且打码（设计 2026-10-23 5.12）
    configure_logging(env_settings.workdata_dir)
    # 两步：先按环境变量连上数据库，再读数据库里存的设置（D22）
    pool = create_pool(env_settings.database_url)
    await pool.open()
    try:
        settings = load_settings(await AppSettingsRepo(pool).all())
        # 先把旧格式的配置文件迁移到当前版本（设计 2026-10-23 7.3），再补写缺的默认文件（D22）：
        # 都在组装智能体之前，它要读这些文件
        migrate_config_files(settings.config_dir, now=datetime.now())
        seed_files_once(settings.workdata_dir, SEED_DIR)
        agent = await build_agent(settings, pool)
        services = build_services(settings, pool, agent)
        for run_id in await services.runs.fail_unfinished():
            # 中途退出的那一轮也写进会话索引：已分批写下的部分回答要搜得到（积压小问题 B7）
            await services.followups.index_later(run_id)
        # MCP 服务在后台连接，不挡启动（首次 npx 下载服务包可能要几十秒）
        connecting = asyncio.create_task(services.integrations.load())
        # 让它先走到"开始重连"（同步完成），之后到达的恢复审批请求会等连接完成
        await asyncio.sleep(0)
        # 网关里缺的默认模型也在后台导入（D22），与 MCP 连接互不等待；升级后补建会话索引
        seeding = asyncio.create_task(_seed_models(services))
        await services.jobs.start(services.followups.handlers())
        await services.document_queue.start(services.document_jobs.handlers())
        app.state.services = services
        try:
            yield
        finally:
            await services.manager.shutdown()  # 关闭连接池之前，让进行中的运行写完结果
            await services.jobs.stop()  # 正在做的后台任务下次启动时重做
            await services.document_queue.stop()
            for task in (connecting, seeding):
                task.cancel()
            await asyncio.gather(connecting, seeding, return_exceptions=True)
            await agent.close()  # 关掉 MCP 服务的子进程
    finally:
        await pool.close()


async def _seed_models(services: Services) -> None:
    """后台：把网关里缺的默认模型导入（D22），再给现有的 Claude 模型打开一次提示缓存
    （设计 2026-10-23 4.1）；补建会话索引、补算文档内容哈希。出意外只记日志，下次启动再试。"""
    workdata = services.settings.workdata_dir
    try:
        await seed_models_once(
            workdata, services.models, load_seed_models(SEED_DIR / "models.yaml")
        )
        await enable_prompt_caching_once(workdata, services.models)
    except Exception:  # 后台任务边界：导入出意外也不能影响服务本身
        logger.exception("导入默认模型或打开提示缓存失败")
    if (conversations := services.agent.conversations) is not None:
        try:
            await backfill_conversation_index_once(
                workdata, services.runs, services.jobs, conversations
            )
        except Exception:  # 后台任务边界：只是旧会话暂时搜不到，下次启动再补
            logger.exception("补建会话索引失败")
    if (documents := services.agent.documents) is not None:
        try:
            # 每次启动都补还没有内容哈希的文档（没有就只是一次查询）：从升级前的备份恢复的旧文档
            # 也补得上（审查 Minor 3：只做一次时，恢复回来的就再也补不上）
            if filled := await documents.backfill_hashes():
                logger.info("补算文档内容哈希：%d 份", filled)
        except Exception:  # 后台任务边界：只是旧文档暂时挡不住重复加入，下次启动再补
            logger.exception("补算文档内容哈希失败")


def create_app(
    lifespan_handler: Lifespan | None = lifespan, frontend_dist: Path = FRONTEND_DIST
) -> FastAPI:
    app = FastAPI(title="open-personal-agent", lifespan=lifespan_handler)
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api")
    mount_frontend(app, frontend_dist)  # 必须在接口路由之后挂载，否则会遮住 /api
    # 本机令牌（D25）：每次启动换一个，只在内存里；守卫最后加，在最外层先于一切处理
    app.state.session_token = secrets.token_urlsafe(32)
    app.add_middleware(LocalGuard, token=app.state.session_token)
    return app


app = create_app()
