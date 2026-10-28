"""应用设置（D22）：代码默认值 → 数据库里存的 → 同名环境变量（含 .env），后者覆盖前者。"""

from typing import Any

import pytest
import yaml
from pydantic_settings import SettingsConfigDict

from config.settings import (
    CONFIG_DIR,
    SETTING_SPECS,
    Settings,
    env_name,
    load_settings,
    read_setting,
)


class _Isolated(Settings):
    """不读 .env：测试不受本机配置影响。"""

    model_config = SettingsConfigDict(env_file=None, env_nested_delimiter="__", extra="ignore")


def _load(monkeypatch: pytest.MonkeyPatch, stored: dict[str, Any] | None = None) -> Settings:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test")
    return load_settings(stored or {}, settings_cls=_Isolated)


def test_defaults_match_the_old_app_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有存储值时等于原 config/app.yaml 的值（上传上限改为 50，设计 4.5；预算已去掉，D23）。"""
    settings = _load(monkeypatch)
    assert (settings.workspace.command_timeout, settings.workspace.max_command_timeout) == (
        120,
        600,
    )
    assert settings.max_upload_mb == 50
    assert (settings.agent.default_model, settings.agent.stream_idle_timeout) == (
        "claude-opus-4-6",
        120,
    )
    knowledge = settings.knowledge
    assert knowledge.embedding_model == "embed-qwen3-0.6b"
    assert (knowledge.recall_top_k, knowledge.recall_min_similarity) == (5, 0.3)
    assert (knowledge.recall_timeout, knowledge.pinned_token_limit) == (5, 2000)
    assert knowledge.auto_extract is True
    assert (knowledge.chunk_tokens, knowledge.chunk_overlap_tokens) == (600, 80)
    assert knowledge.ingest_batch_size == 2
    adapters = settings.adapters
    assert (adapters.model_gateway, adapters.workspace, adapters.embedder) == (
        "litellm_proxy",
        "local",
        "litellm_proxy",
    )
    assert (adapters.knowledge_index, adapters.doc_parser) == ("pgvector", "markitdown")
    assert (adapters.blob_storage, adapters.mcp_client) == ("local_disk", "mcp_adapters")
    assert "budget" not in type(settings).model_fields
    assert "max_upload_mb" not in type(settings.workspace).model_fields
    assert "max_document_mb" not in type(settings.knowledge).model_fields


def test_stored_value_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _load(monkeypatch, {"knowledge.recall_top_k": 3}).knowledge.recall_top_k == 3
    settings = _load(monkeypatch, {"knowledge.recall_top_k": 3, "agent.default_model": "m2"})
    # 同一节里没存的照旧用默认值
    assert (settings.knowledge.chunk_tokens, settings.agent.default_model) == (600, "m2")


def test_env_overrides_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE__RECALL_TOP_K", "7")
    monkeypatch.setenv("AGENT__DEFAULT_MODEL", "from-env")
    settings = _load(monkeypatch, {"knowledge.recall_top_k": 3, "agent.default_model": "from-db"})
    assert (settings.knowledge.recall_top_k, settings.agent.default_model) == (7, "from-env")


def test_invalid_stored_value_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """库里存的值手改坏了：后端照常启动，这一项按默认值（其余存的值照用）。"""
    settings = _load(
        monkeypatch, {"knowledge.recall_top_k": "很多", "workspace.command_timeout": 90}
    )
    assert (settings.knowledge.recall_top_k, settings.workspace.command_timeout) == (5, 90)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("knowledge.recall_top_k", -1),  # 每条消息都失败：LIMIT must not be negative
        ("knowledge.recall_min_similarity", 7),
        ("knowledge.recall_timeout", 0),
        ("knowledge.pinned_token_limit", 0),
        ("knowledge.chunk_tokens", 0),
        ("knowledge.chunk_overlap_tokens", -1),
        ("knowledge.ingest_batch_size", 0),  # 每个文档都处理出错
        ("knowledge.ingest_batch_size", -2),  # 显示"完成"，实际一段都没入库
    ],
)
def test_out_of_range_stored_value_is_ignored(
    monkeypatch: pytest.MonkeyPatch, key: str, value: Any
) -> None:
    """超出范围的值会让对话或文档整体失效（终审 I3）：库里存了也按默认值。"""
    default = read_setting(_load(monkeypatch), key)
    assert read_setting(_load(monkeypatch, {key: value}), key) == default


@pytest.mark.parametrize(
    "stored",
    [
        {"workspace.command_timeout": 900},  # 超过最长时限 600：没写时限的命令全被拒
        {"workspace.command_timeout": 500, "workspace.max_command_timeout": 400},
        {"knowledge.chunk_overlap_tokens": 600},  # 不小于每块的大小
    ],
)
def test_inconsistent_stored_values_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, stored: dict[str, Any]
) -> None:
    """跨项不一致（终审 I3）：这一节里存的都按默认值，后端照常启动，别的节不受影响。"""
    settings = _load(monkeypatch, {**stored, "max_upload_mb": 20})
    workspace = (settings.workspace.command_timeout, settings.workspace.max_command_timeout)
    assert workspace == (120, 600)
    assert (settings.knowledge.chunk_tokens, settings.knowledge.chunk_overlap_tokens) == (600, 80)
    assert settings.max_upload_mb == 20


def test_env_name_uses_double_underscore() -> None:
    assert env_name("agent.default_model") == "AGENT__DEFAULT_MODEL"
    assert env_name("max_upload_mb") == "MAX_UPLOAD_MB"


def test_every_spec_key_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _load(monkeypatch)
    keys = [spec.key for spec in SETTING_SPECS]
    assert len(keys) == len(set(keys))
    for key in keys:
        read_setting(settings, key)  # 每个键都能取到值
    # 连数据库之前就要知道的只在环境变量里，不进设置表（设计 4.7）
    assert not {"database_url", "litellm_base_url", "litellm_master_key", "workdata_dir"} & set(
        keys
    )
    assert {spec.key for spec in SETTING_SPECS if spec.apply == "now"} == {"agent.default_model"}
    read_only = {spec.key for spec in SETTING_SPECS if not spec.editable}
    assert {"knowledge.embedding_model", "models.sources", "adapters.workspace"} <= read_only


def test_settings_read_no_yaml() -> None:
    assert Settings.model_config.get("yaml_file") is None
    assert not (CONFIG_DIR / "app.yaml").exists()


def test_project_approval_rules_leave_execute_to_code() -> None:
    """执行命令每次先问写在代码里（D21），默认的规则文件里不写它。"""
    from config.settings import SEED_DIR

    path = SEED_DIR / "files" / "config" / "approval_rules.yaml"
    rules = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "execute" not in (rules.get("tools") or {})


def test_default_workdata_dir_is_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """数据目录改名为 .workdata（D22）：项目根目录下，隐藏起来。"""
    from config.settings import ROOT_DIR

    assert _load(monkeypatch).workdata_dir == ROOT_DIR / ".workdata"
