"""端到端测试用的后端（make e2e，设计文档 14 节：Playwright 驱动浏览器，后端接假模型）。

组装的是真实的 backend（接口、运行管理、推送、审批、设置、用量），只把外部依赖换成替身：
按关键词走剧本的假模型、临时目录里的工作区、假的知识库与 MCP 服务。数据库只能用测试库实例
（127.0.0.1:55432）里单独的 agent_e2e 库，每次启动清空，绝不碰正式数据，也不连模型网关、不花钱。

启动：uv run python -m backend.tests.e2e_server（http://127.0.0.1:8100，提供 frontend/dist）。
"""

import asyncio
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic_settings import SettingsConfigDict

from agents.main_agent.models import ModelInfo
from agents.main_agent.runtime import MainAgent, SkillCatalog
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import (
    FakeGateway,
    FakeKnowledgeStore,
    FakeMcpClient,
    FakeSandbox,
    KeywordChatModel,
    call,
    mcp_tool,
)
from backend.api.deps import build_services
from backend.main import create_app
from common.db import create_pool
from config import Settings
from config.settings import ROOT_DIR, AgentConfig, KnowledgeConfig

TEST_HOST = "127.0.0.1:55432"  # compose 里的 postgres-test（make test-up）
E2E_DATABASE_URL = f"postgresql://agent:agent@{TEST_HOST}/agent_e2e"
PORT = 8100
_BUSINESS_TABLES = (
    "threads, runs, run_events, llm_usage, tool_usage, workspace_files, knowledge_items, "
    "knowledge_documents, jobs, app_settings, conversation_turns, checkpoints, "
    "checkpoint_writes, checkpoint_blobs"
)
_WORK_DIR = re.compile(r"/workspace/c_[0-9a-f]+/")


@tool
def demo_add_note(text: str) -> str:
    """记一条笔记"""
    return f"已记下：{text}"


@tool
def demo_list_notes() -> str:
    """列出笔记"""
    return "（还没有笔记）"


@tool
async def demo_wait() -> str:
    """等一会儿再返回（端到端测试"运行中插话"：工具跑着的时候用户插话）"""
    await asyncio.sleep(2)  # 允许等待：替身工具模拟跑一会儿
    return "等完了"


def _work_dir(messages: list[BaseMessage]) -> str:
    """本会话的工作目录（WorkDirectoryMiddleware 写在系统提示词里）：文件工具只能访问它。"""
    system = next(str(m.content) for m in messages if isinstance(m, SystemMessage))
    match = _WORK_DIR.search(system)
    return match.group(0) if match else "/workspace/"


def _list_work_dir(messages: list[BaseMessage]) -> AIMessage:
    return call("ls", {"path": _work_dir(messages)})


def _write_report(messages: list[BaseMessage]) -> AIMessage:
    return call(
        "write_file",
        {
            "file_path": f"{_work_dir(messages)}outputs/report.md",
            "content": "# 周报\n本周完成端到端测试",
        },
    )


_FAILED_ONCE: set[str] = set()


def _fail_once(messages: list[BaseMessage]) -> AIMessage:
    """每个会话第一次回答时模拟网关出错；"重试这一轮"之后正常回答（D26）。"""
    work_dir = _work_dir(messages)  # 每个会话的工作目录不同
    if work_dir not in _FAILED_ONCE:
        _FAILED_ONCE.add(work_dir)
        raise RuntimeError("模拟的网关出错")
    return AIMessage("重试成功了")


# "写公式"剧本的回答：代码块、两种公式写法与金额（R13，D19）
MARKDOWN_SAMPLE = (
    "示例如下：\n\n"
    "```python\ndef area(r):\n    return 3.14 * r ** 2  # 圆面积\n```\n\n"
    "质能方程 \\(E = mc^2\\)，价格 $5 到 $10。\n\n"
    "\\[\\int_0^1 x\\,dx = \\frac{1}{2}\\]\n"
)


def scripted_model() -> KeywordChatModel:
    """各端到端测试用到的剧本（关键词写在用户消息里）。"""
    return KeywordChatModel(
        scripts=[
            ("打招呼", [AIMessage("你好，我是测试助手")]),
            ("看看目录", [_list_work_dir, AIMessage("目录看完了")]),
            ("记笔记", [call("demo_add_note", {"text": "买牛奶"}), AIMessage("记好了")]),
            ("写报告", [_write_report, AIMessage("报告写好了")]),
            ("慢慢说", [AIMessage("一二三四五六七八九十" * 5)]),
            # 运行中插话（设计 2026-10-23 6.3）：插的话送达后，下一次调用看到的最后一条用户消息是它
            ("等一会儿", [call("demo_wait", {}), AIMessage("等完了")]),
            ("改成英文", [AIMessage("OK, switching to English")]),
            ("写公式", [AIMessage(MARKDOWN_SAMPLE)]),
            ("模拟失败", [_fail_once]),
        ],
        default="好的",
        delays={"慢慢说": 0.2},
    )


E2E_WORKDATA = Path(tempfile.gettempdir()) / "opa-e2e-workdata"


def _fresh_workdata(path: Path = E2E_WORKDATA) -> Path:
    """端到端用的 .workdata：固定位置，每次启动先清空再建（和每次清空 agent_e2e 库一样）。

    不每次新建临时目录：Playwright 停服务时直接强杀，收尾删不掉，会越积越多；端口固定 8100，
    不会有两个同时跑。"""
    if path.exists():
        shutil.rmtree(path)  # 删不掉时报出真正的原因，不吞掉
    path.mkdir(parents=True)
    return path


class _IsolatedSettings(Settings):
    """不读 .env：端到端测试不受本机正式配置影响（数据库里的设置也不读，按代码默认值）。"""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def build_e2e_app(database_url: str = E2E_DATABASE_URL) -> FastAPI:
    netloc = urlsplit(database_url).netloc.rsplit("@", 1)[-1]
    if netloc != TEST_HOST:
        raise RuntimeError(f"端到端测试只能用测试库（{TEST_HOST}），拒绝连接 {netloc}")
    # 临时的 .workdata（D22）：配置文件在 config/ 下，技能在 skills/ 下
    workdata = _fresh_workdata()
    (workdata / "config").mkdir()
    (workdata / "config" / "mcp_servers.yaml").write_text(
        "servers:\n  demo:\n    description: 测试用 MCP 服务\n    command: echo\n",
        encoding="utf-8",
    )
    (workdata / "config" / "approval_rules.yaml").write_text("mcp_default: ask\n", encoding="utf-8")
    (workdata / "skills" / "excel").mkdir(parents=True)
    (workdata / "skills" / "excel" / "SKILL.md").write_text(
        "---\nname: excel\ndescription: 处理 Excel / CSV 表格\n---\n\n# 处理表格\n\n先看清表头。\n",
        encoding="utf-8",
    )
    settings = _IsolatedSettings(
        database_url=database_url,
        litellm_master_key="sk-e2e",
        workdata_dir=workdata,
        agent=AgentConfig(default_model="fake-model"),
        knowledge=KnowledgeConfig(auto_extract=False, embedding_model="embed-fake"),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await _prepare_database(database_url)
        pool = create_pool(database_url)
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        async with pool.connection() as conn:
            await conn.execute(f"TRUNCATE {_BUSINESS_TABLES} CASCADE")
        agent = MainAgent(
            gateway=FakeGateway(
                scripted_model(),
                models=[
                    # 都带部署编号：模型全部在网关数据库里，都能改（D22）
                    ModelInfo(name="fake-model", id="e2e-1", upstream="litellm_proxy/fake-model"),
                    # 第二个对话模型：端到端测试"换的模型存在会话上"用
                    ModelInfo(
                        name="fake-model-2", id="e2e-2", upstream="litellm_proxy/fake-model-2"
                    ),
                    ModelInfo(
                        name="embed-fake", id="e2e-3", mode="embedding", upstream="ollama/embed"
                    ),
                ],
            ),
            checkpointer=checkpointer,
            system_prompt="你是端到端测试用的助手。",
            workspace=LocalWorkspace(workdata, FakeSandbox()),
            knowledge=FakeKnowledgeStore(),
            mcp=FakeMcpClient(
                [
                    mcp_tool(demo_add_note),
                    mcp_tool(demo_list_notes, read_only=True),
                    mcp_tool(demo_wait, read_only=True),
                ]
            ),
            skills=SkillCatalog(settings.skills_dir, settings.skills_state_file),
        )
        services = build_services(settings, pool, agent)
        await services.integrations.load()
        await services.jobs.start(services.followups.handlers())
        app.state.services = services
        try:
            yield
        finally:
            await services.manager.shutdown()
            await services.jobs.stop()
            await pool.close()

    return create_app(lifespan_handler=lifespan, frontend_dist=ROOT_DIR / "frontend" / "dist")


async def _prepare_database(database_url: str) -> None:
    """测试库实例上没有 agent_e2e 库就建一个，并迁移到最新。"""
    parts = urlsplit(database_url)
    name = parts.path.lstrip("/")
    admin = parts._replace(path="/agent_test").geturl()
    async with await psycopg.AsyncConnection.connect(admin, autocommit=True) as conn:
        cur = await conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if await cur.fetchone() is None:
            await conn.execute(f'CREATE DATABASE "{name}"')
    config = Config(toml_file=str(ROOT_DIR / "pyproject.toml"))
    config.attributes["database_url"] = database_url
    await asyncio.to_thread(command.upgrade, config, "head")


if __name__ == "__main__":
    uvicorn.run(build_e2e_app(), host="127.0.0.1", port=PORT)
