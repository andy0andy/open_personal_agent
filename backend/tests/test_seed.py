"""首次启动写入默认内容（D22）：只补缺的、从不覆盖；用户删过的不重建；模型经网关接口导入。"""

import shutil
from datetime import datetime
from pathlib import Path

import pytest

from agents.main_agent.conversations import NewConversationTurn
from agents.main_agent.models import ModelInfo
from agents.tests.fakes import (
    FakeConversationIndex,
    FakeGateway,
    ScriptedChatModel,
    UnavailableGateway,
)
from backend.models import ModelAdmin
from backend.runs import RunRepo
from backend.settings.app_settings import AppSettingsRepo, AppSettingsService
from backend.settings.seed import (
    backfill_conversation_index_once,
    enable_prompt_caching_once,
    load_seed_models,
    migrate_config_files,
    seed_files_once,
    seed_models_once,
)
from backend.threads import ThreadRepo
from common.db import Pool
from config import CONFIG_VERSIONS, config_version, read_config_yaml
from config.settings import SEED_DIR, AgentConfig, Settings


def _marker(workdata: Path) -> list[str]:
    path = workdata / ".seeded"
    return path.read_text(encoding="utf-8").split() if path.exists() else []


def test_first_start_writes_seed_files(tmp_path: Path) -> None:
    written = seed_files_once(tmp_path, SEED_DIR)
    assert {"config/mcp_servers.yaml", "config/approval_rules.yaml", "skills/excel"} <= set(written)
    assert (tmp_path / "skills" / "excel" / "SKILL.md").is_file()
    assert "files:" in (tmp_path / "config" / "mcp_servers.yaml").read_text(encoding="utf-8")
    assert _marker(tmp_path) == ["files"]


def test_existing_files_are_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    mine = "servers: {}\n# 我自己的\n"
    (tmp_path / "config" / "mcp_servers.yaml").write_text(mine, encoding="utf-8")
    written = seed_files_once(tmp_path, SEED_DIR)
    assert "config/mcp_servers.yaml" not in written
    assert (tmp_path / "config" / "mcp_servers.yaml").read_text(encoding="utf-8") == mine
    assert (tmp_path / "config" / "approval_rules.yaml").is_file()


def test_deleted_items_are_not_recreated(tmp_path: Path) -> None:
    seed_files_once(tmp_path, SEED_DIR)
    shutil.rmtree(tmp_path / "skills" / "excel")
    assert seed_files_once(tmp_path, SEED_DIR) == []
    assert not (tmp_path / "skills" / "excel").exists()


def _config(tmp_path: Path, **files: str) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    for name, text in files.items():
        (config / f"{name}.yaml").write_text(text, encoding="utf-8")
    return config


def test_old_files_get_a_version_and_a_backup(tmp_path: Path) -> None:
    old = "# 我的服务\n# 第二行\n\nservers:\n  demo:\n    command: echo  # 行尾注释\n"
    config = _config(tmp_path, mcp_servers=old, skills="disabled:\n- excel\n")
    now = datetime(2026, 10, 24, 4, 5, 6)
    assert migrate_config_files(config, now=now) == ["mcp_servers.yaml", "skills.yaml"]
    # 注释、空行、行尾注释都还在，版本号插在开头的注释之后
    assert (config / "mcp_servers.yaml").read_text(encoding="utf-8") == (
        "# 我的服务\n# 第二行\n\nversion: 1\nservers:\n  demo:\n    command: echo  # 行尾注释\n"
    )
    backup = config / "history" / "mcp_servers.yaml.20261024-040506.bak"
    assert backup.read_text(encoding="utf-8") == old
    assert read_config_yaml(config / "skills.yaml") == {"version": 1, "disabled": ["excel"]}
    assert not (config / "approval_rules.yaml").exists()  # 没有的文件不新建


def test_explicit_version_0_is_migrated(tmp_path: Path) -> None:
    """已经写了 version: 0 的按行改成 1，行尾注释留着；不再插第二个 version（积压小问题 G9）。"""
    old = "# 注释\nversion: 0  # 旧\nservers: {}\n"
    config = _config(tmp_path, mcp_servers=old)
    assert migrate_config_files(config, now=datetime(2026, 10, 26, 1, 2, 3)) == ["mcp_servers.yaml"]
    assert (config / "mcp_servers.yaml").read_text(encoding="utf-8") == (
        "# 注释\nversion: 1  # 旧\nservers: {}\n"
    )
    backup = config / "history" / "mcp_servers.yaml.20261026-010203.bak"
    assert backup.read_text(encoding="utf-8") == old


def test_current_files_are_left_alone(tmp_path: Path) -> None:
    files = {
        "approval_rules": "version: 1\ntools: {}\n",
        "mcp_servers": "version: 2\nservers: {}\n",  # 更新的程序写的：不往回改
        "skills": "# 只有注释\n",  # 空文件：没有可迁移的
    }
    config = _config(tmp_path, **files)
    assert migrate_config_files(config, now=datetime(2026, 10, 24)) == []
    for name, text in files.items():
        assert (config / f"{name}.yaml").read_text(encoding="utf-8") == text
    assert not (config / "history").exists()


def test_broken_file_is_not_touched(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    files = {
        "mcp_servers": "servers:\n  demo: [\n",  # 写坏的 YAML
        "approval_rules": "version: 新\ntools: {}\n",  # 版本号不是整数
        "skills": "{disabled: [excel]}\n",  # 插一行会改坏：不自动改
    }
    config = _config(tmp_path, **files)
    assert migrate_config_files(config, now=datetime(2026, 10, 24)) == []
    for name, text in files.items():
        assert (config / f"{name}.yaml").read_text(encoding="utf-8") == text
    assert not (config / "history").exists()
    assert "不是合法的 YAML" in caplog.text
    assert "version 应是整数" in caplog.text
    assert "请手动把 version 改成 1（没有这一项就加上 version: 1）" in caplog.text


def test_unreadable_files_do_not_stop_startup(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = _config(tmp_path, mcp_servers="servers: {}\n")
    gbk = "disabled:\n- 表格\n".encode("gbk")
    (config / "skills.yaml").write_bytes(gbk)
    (config / "history").write_text("不是文件夹", encoding="utf-8")  # 备份不了
    assert migrate_config_files(config, now=datetime(2026, 10, 24)) == []
    assert (config / "skills.yaml").read_bytes() == gbk
    assert (config / "mcp_servers.yaml").read_text(encoding="utf-8") == "servers: {}\n"
    assert "不是 UTF-8" in caplog.text
    assert "mcp_servers.yaml 没能迁移" in caplog.text


def test_seed_files_have_a_version() -> None:
    seeded = sorted((SEED_DIR / "files" / "config").iterdir())
    assert [path.name for path in seeded] == ["approval_rules.yaml", "mcp_servers.yaml"]
    for path in seeded:
        assert config_version(read_config_yaml(path)) == CONFIG_VERSIONS[path.name]


def test_seed_models_file_matches_the_table() -> None:
    """4 个模型逐项核对（gemini、gpt 的值取自网关自带的价格表，2026-10-19）。"""
    items = {item.name: item for item in load_seed_models(SEED_DIR / "models.yaml")}
    assert list(items) == ["claude-opus-4-6", "gemini-3.5-flash", "gpt-5.5-pro", "embed-qwen3-0.6b"]
    claude, gemini, gpt, embed = items.values()
    assert (claude.source, claude.upstream_id, claude.mode) == (
        "upstream",
        "claude-opus-4-6",
        "chat",
    )
    assert (claude.max_input_tokens, claude.max_output_tokens) == (1_000_000, 128_000)
    assert (claude.price_input, claude.price_output) == (5, 25)
    assert (gemini.source, gemini.upstream_id) == ("upstream", "gemini-3.5-flash")
    assert (gemini.max_input_tokens, gemini.max_output_tokens) == (1_048_576, 65_535)
    assert (gemini.price_input, gemini.price_output) == (1.5, 9)
    assert (gpt.source, gpt.upstream_id) == ("upstream", "gpt-5.5-pro")
    assert (gpt.max_input_tokens, gpt.max_output_tokens) == (1_050_000, 128_000)
    assert (gpt.price_input, gpt.price_output) == (30, 180)
    # 提示缓存只对 Claude（设计 2026-10-23 4.1）
    assert (claude.supports_prompt_caching, gemini.supports_prompt_caching) == (True, False)
    assert gpt.supports_prompt_caching is False
    for chat in (claude, gemini, gpt):
        assert chat.mode == "chat"
        assert (chat.supports_reasoning, chat.supports_vision, chat.supports_function_calling) == (
            True,
            True,
            True,
        )
    assert (embed.source, embed.upstream_id, embed.mode) == (
        "ollama",
        "qwen3-embedding:0.6b",
        "embedding",
    )
    assert (embed.price_input, embed.price_output) == (0, 0)


def _admin(db: Pool, gateway: FakeGateway) -> ModelAdmin:
    settings = Settings(
        database_url="postgresql://unused",
        litellm_master_key="sk-test",
        agent=AgentConfig(default_model="claude-opus-4-6"),
    )
    return ModelAdmin(
        settings,
        gateway,
        ThreadRepo(db),
        AppSettingsService(settings, AppSettingsRepo(db)),
        RunRepo(db),
    )


@pytest.mark.integration
async def test_seed_models_adds_missing_only(tmp_path: Path, db: Pool) -> None:
    gateway = FakeGateway(
        ScriptedChatModel(responses=[]), models=[ModelInfo(name="claude-opus-4-6")]
    )
    items = load_seed_models(SEED_DIR / "models.yaml")
    added = await seed_models_once(tmp_path, _admin(db, gateway), items)
    assert added == ["gemini-3.5-flash", "gpt-5.5-pro", "embed-qwen3-0.6b"]
    assert [m.name for m in await gateway.list_models()] == [
        "claude-opus-4-6",
        "gemini-3.5-flash",
        "gpt-5.5-pro",
        "embed-qwen3-0.6b",
    ]
    assert "models" in _marker(tmp_path)
    # 记过就不再导入：之后在模型页删掉的不会回来
    assert await seed_models_once(tmp_path, _admin(db, gateway), items) == []


@pytest.mark.integration
async def test_seed_models_retries_when_gateway_is_down(tmp_path: Path, db: Pool) -> None:
    gateway = FakeGateway(ScriptedChatModel(responses=[]), models=[])
    gateway.fail_next_add = True
    items = load_seed_models(SEED_DIR / "models.yaml")
    first = await seed_models_once(tmp_path, _admin(db, gateway), items)
    assert "models" not in _marker(tmp_path)
    second = await seed_models_once(tmp_path, _admin(db, gateway), items)
    assert sorted(first + second) == sorted(item.name for item in items)
    assert "models" in _marker(tmp_path)


def _db_model(name: str, upstream: str) -> ModelInfo:
    """网关数据库里的模型（有部署编号，页面上能改）。"""
    return ModelInfo(
        name=name,
        id=f"id-{name}",
        upstream=upstream,
        mode="chat",
        max_input_tokens=1_000_000,
        max_output_tokens=128_000,
        input_cost_per_token=5e-06,
        output_cost_per_token=2.5e-05,
        supports_reasoning=True,
        supports_vision=True,
        supports_function_calling=True,
    )


@pytest.mark.integration
async def test_prompt_caching_enabled_once_for_existing_claude_models(
    tmp_path: Path, db: Pool
) -> None:
    """升级时给现有的 Claude 模型打开一次缓存；之后手动关掉的不会再被打开（设计 4.1）。"""
    gateway = FakeGateway(
        ScriptedChatModel(responses=[]),
        models=[
            _db_model("claude-opus-4-6", "litellm_proxy/claude-opus-4-6"),
            _db_model("gemini-3.5-flash", "litellm_proxy/gemini-3.5-flash"),
            ModelInfo(name="claude-in-yaml", upstream="litellm_proxy/claude-x"),  # 改不了
        ],
    )
    admin = _admin(db, gateway)
    assert await enable_prompt_caching_once(tmp_path, admin) == ["claude-opus-4-6"]
    by_name = {m.name: m for m in await gateway.list_models()}
    claude = by_name["claude-opus-4-6"]
    assert claude.supports_prompt_caching
    assert not by_name["gemini-3.5-flash"].supports_prompt_caching
    assert not by_name["claude-in-yaml"].supports_prompt_caching
    # 其余设置原样保留
    assert (claude.supports_reasoning, claude.max_input_tokens, claude.max_output_tokens) == (
        True,
        1_000_000,
        128_000,
    )
    assert claude.input_cost_per_token == pytest.approx(5e-06)
    assert "prompt_caching" in _marker(tmp_path)
    gateway.models = [
        m.model_copy(update={"supports_prompt_caching": False}) for m in gateway.models
    ]
    assert await enable_prompt_caching_once(tmp_path, admin) == []
    assert not {m.name: m for m in await gateway.list_models()}[
        "claude-opus-4-6"
    ].supports_prompt_caching


@pytest.mark.integration
async def test_prompt_caching_marker_not_written_when_gateway_fails(
    tmp_path: Path, db: Pool
) -> None:
    gateway = UnavailableGateway(ScriptedChatModel(responses=[]))
    assert await enable_prompt_caching_once(tmp_path, _admin(db, gateway)) == []
    assert "prompt_caching" not in _marker(tmp_path)


@pytest.mark.integration
async def test_prompt_caching_waits_until_the_gateway_has_loaded_its_models(
    tmp_path: Path, db: Pool
) -> None:
    """网关刚启动、数据库里的模型还没载入时清单里一个也没有：不记标记，下次启动再打开（审查建议）。"""
    gateway = FakeGateway(
        ScriptedChatModel(responses=[]),
        models=[ModelInfo(name="claude-in-yaml", upstream="litellm_proxy/claude-x")],
    )
    assert await enable_prompt_caching_once(tmp_path, _admin(db, gateway)) == []
    assert "prompt_caching" not in _marker(tmp_path)


class _Jobs:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict[str, object]]] = []

    async def enqueue(self, kind: str, payload: dict[str, object]) -> None:
        self.enqueued.append((kind, payload))


@pytest.mark.integration  # 要连测试库（积压小问题第 8 节：原来没标，make check 时会去连）
async def test_backfill_indexes_old_runs_once(tmp_path: Path, db: Pool) -> None:
    """升级后把已有的历史补进会话索引（设计 2026-10-23 6.1）：只补结束了、还没索引的，只做一次。"""
    threads, runs = ThreadRepo(db), RunRepo(db)
    thread = await threads.create(model="m")
    old = await runs.create(thread_id=thread.id, model="m", message="以前的问题")
    await runs.finish(old.id, status="completed", error=None)
    indexed = await runs.create(thread_id=thread.id, model="m", message="已有索引")
    await runs.finish(indexed.id, status="failed", error="x")
    other = await threads.create(model="m")
    await runs.create(thread_id=other.id, model="m", message="还在跑")
    index = FakeConversationIndex()
    await index.index(
        NewConversationTurn(
            thread_id=thread.id,
            run_id=indexed.id,
            title="",
            started_at=indexed.created_at,
            user_text="已有索引",
            answer_text="",
        )
    )
    jobs = _Jobs()
    assert await backfill_conversation_index_once(tmp_path, runs, jobs, index) == 1
    assert jobs.enqueued == [("conversation_index", {"run_id": str(old.id)})]
    assert "conversation_index" in _marker(tmp_path)
    assert await backfill_conversation_index_once(tmp_path, runs, jobs, index) == 0
    assert len(jobs.enqueued) == 1
