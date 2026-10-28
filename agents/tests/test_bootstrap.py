import uuid
from pathlib import Path

import pytest

from agents.main_agent.bootstrap import _WORKSPACES, _embedding_usage, build_agent
from agents.main_agent.knowledge import DocumentLibrary, PgKnowledgeStore
from agents.main_agent.models import EmbeddingUsage, LiteLLMProxyGateway, call_context
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import LocalWorkspace
from common.db import Pool
from config import Settings
from config.settings import AdaptersConfig, AgentConfig

pytestmark = pytest.mark.integration


async def test_build_agent_survives_unreachable_gateway(pg_pool: Pool, tmp_path: Path) -> None:
    prompt = tmp_path / "system.md"
    prompt.write_text("测试助手", encoding="utf-8")
    settings = Settings(
        database_url="postgresql://unused",
        litellm_base_url="http://127.0.0.1:9",  # 无服务监听，模拟网关未就绪
        litellm_master_key="sk-test",
        agent=AgentConfig(default_model="m", system_prompt_file=prompt),
        workdata_dir=tmp_path,
    )

    agent = await build_agent(settings, pg_pool)

    assert isinstance(agent.models, LiteLLMProxyGateway)
    assert isinstance(agent.workspace, LocalWorkspace)  # 配置 adapters.workspace: local
    assert isinstance(agent.knowledge, PgKnowledgeStore)  # 配置 adapters.knowledge_index: pgvector
    assert isinstance(agent.documents, DocumentLibrary)
    # 知识库文档与附件、技能包共用上传上限（设计 2026-10-19 4.5）
    assert agent.documents._max_bytes == settings.max_upload_mb * 1024 * 1024 == 50 * 1024 * 1024
    async with pg_pool.connection() as conn:
        cur = await conn.execute("SELECT to_regclass('public.checkpoints')::text AS name")
        row = await cur.fetchone()
    assert row is not None
    assert row["name"] == "checkpoints"


def test_default_workspace_adapter_is_registered() -> None:
    """配置里不写 adapters.workspace 时用的默认实现名，组装根里必须登记了（D20 改名为 local）。"""
    assert AdaptersConfig().workspace in _WORKSPACES


async def test_embedding_usage_is_recorded_under_the_current_call(db: Pool) -> None:
    """向量化的用量记在当前这次运行名下（积压小问题 I5）；不在运行里（文档入库）时会话与运行
    为空；编号不是 UUID 时也记空，不报错。"""
    record = _embedding_usage(db)
    usage = UsageRepo(db)
    thread_id, run_id = uuid.uuid4(), uuid.uuid4()
    with call_context(str(thread_id), str(run_id)):
        await record(EmbeddingUsage(model="bge-m3", input_tokens=7, duration_ms=12))
    await record(EmbeddingUsage(model="bge-m3", input_tokens=3, duration_ms=5))
    with call_context("不是编号", "也不是"):
        await record(EmbeddingUsage(model="bge-m3", input_tokens=2, duration_ms=1))

    [mine] = await usage.for_run(run_id)
    assert (mine.caller, mine.actual_model, mine.input_tokens) == ("embedding", "bge-m3", 7)
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT thread_id, run_id, input_tokens FROM llm_usage WHERE run_id IS NULL "
            "ORDER BY input_tokens"
        )
        rows = await cur.fetchall()
    assert [(r["thread_id"], r["run_id"], r["input_tokens"]) for r in rows] == [
        (None, None, 2),
        (None, None, 3),
    ]
