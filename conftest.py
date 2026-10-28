"""全局测试夹具。集成测试连接 compose test 配置组里的 postgres-test（make test-up 启动）。"""

import os
import re
import tempfile
from collections.abc import AsyncIterator, Iterator

import dotenv
import pytest
from alembic import command
from alembic.config import Config

from common.db import Pool, create_pool
from config import Settings

_CREDENTIAL_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://agent:agent@127.0.0.1:55432/agent_test"
)

# 测试不读 .env（设计 2026-10-23 7.6）：litellm、magika 一导入就把 .env 读进环境变量，比
# pytest_configure 还早，连正式库的地址也带进来了。先让它什么都不做（这里比任何测试模块都先
# 导入），冒烟测试在 pytest_configure 里恢复后再读一次
_skip_dotenv = pytest.MonkeyPatch()
_skip_dotenv.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)


def pytest_configure(config: pytest.Config) -> None:
    # LiteLLM 导入时会去 GitHub 拉价格表，网络不通会卡十几秒；测试一律使用内置副本
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    # 与正式运行一致：对话存档只反序列化登记过的类型（须在导入 langgraph 之前设置）
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    # 测试不碰真实密钥（设计 2026-10-23 7.6）：清掉带凭据的环境变量，构造设置时不读 .env。
    # 冒烟测试（-m live）要连真实网关，除外：照常把 .env 读进来
    if re.search(r"(?<!not )\blive\b", config.getoption("markexpr") or ""):
        _skip_dotenv.undo()
        dotenv.load_dotenv()
        return
    for name in [n for n in os.environ if n.upper().endswith(_CREDENTIAL_SUFFIXES)]:
        del os.environ[name]
    Settings.model_config["env_file"] = None


@pytest.fixture(scope="session", autouse=True)
def _temp_dirs_under_pytest(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """测试与被测代码里 tempfile 建的临时目录都放到 pytest 的临时目录下（R45）：pytest 只留最近
    3 次，不会像原来那样在系统临时目录里越积越多（api-workdata-*、tmp* 上万个）。"""
    original = tempfile.tempdir
    tempfile.tempdir = str(tmp_path_factory.mktemp("tempfile", numbered=False))
    yield
    tempfile.tempdir = original


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """指向测试库的迁移配置；迁移测试用它退回到旧版本、写入旧数据再升级。"""
    config = Config(toml_file="pyproject.toml")
    config.attributes["database_url"] = TEST_DATABASE_URL
    return config


@pytest.fixture(scope="session")
async def pg_pool(alembic_config: Config) -> AsyncIterator[Pool]:
    command.upgrade(alembic_config, "head")
    pool = create_pool(TEST_DATABASE_URL)
    await pool.open()
    yield pool
    await pool.close()


@pytest.fixture
async def db(pg_pool: Pool) -> Pool:
    """每个测试前清空业务表。"""
    async with pg_pool.connection() as conn:
        await conn.execute(
            "TRUNCATE threads, runs, run_events, llm_usage, tool_usage, workspace_files, "
            "knowledge_items, knowledge_documents, app_settings, conversation_turns, "
            "jobs CASCADE"
        )
    return pg_pool
