"""应用配置（D22）：代码里的默认值 → 数据库里存的设置 → 同名环境变量（含 .env），后者覆盖前者。

连数据库之前就要知道的（数据库地址、网关地址与密钥）只在环境变量里；其余设置在设置页上改、
存进数据库的 app_settings 表（backend/settings/app_settings.py），启动时读出来交给 load_settings。
"""

import logging
from collections.abc import Mapping
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, SecretStr, ValidationError, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import to_jsonable_python
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent
ROOT_DIR = CONFIG_DIR.parent
SEED_DIR = CONFIG_DIR / "seed"  # 首次启动写入 .workdata 与网关的默认内容（D22）

logger = logging.getLogger(__name__)


class AdaptersConfig(BaseModel):
    """各可替换接口选用的具体实现名。"""

    model_gateway: str = "litellm_proxy"
    workspace: str = "local"
    embedder: str = "litellm_proxy"
    knowledge_index: str = "pgvector"
    doc_parser: str = "markitdown"
    blob_storage: str = "local_disk"
    mcp_client: str = "mcp_adapters"


class WorkspaceConfig(BaseModel):
    """工作区（设计文档 9；D20：命令在智能体所在环境里执行，会话目录在 <数据目录>/workspace/）。"""

    command_timeout: int = Field(default=120, gt=0)  # 命令默认时限（秒）；超时杀掉整个进程组
    max_command_timeout: int = Field(default=600, gt=0)  # 智能体能要求的最长时限

    @model_validator(mode="after")
    def _timeout_within_max(self) -> Self:
        # 默认时限超过最长时限时，没写时限的命令全被拒（终审 I3）
        if self.command_timeout > self.max_command_timeout:
            raise ValueError("命令默认时限不能超过最长时限")
        return self


class KnowledgeConfig(BaseModel):
    """统一知识库与记忆（设计文档 8）。"""

    embedding_model: str = (
        "embed-qwen3-0.6b"  # 网关里的向量模型名（默认清单 config/seed/models.yaml，在模型页管理）
    )
    # 设置页上能改（D22）：取值范围挡住会让对话或文档整体失效的值（终审 I3）
    recall_top_k: int = Field(default=5, ge=0)  # 每次带上的相关记忆最多几条；0 表示不带
    # 相关记忆的相似度下限：qwen3 0.6B 上真正相关的记忆只有 0.34～0.64，
    # 设计文档的 0.75 会什么都召回不到（M3a 计划的先行探测）
    recall_min_similarity: float = Field(default=0.3, ge=0, le=1)
    # 召回最多等几秒（向量模型卡住或冷启动时），超时就不带相关记忆
    recall_timeout: float = Field(default=5.0, gt=0)
    # 常驻条目总量的建议上限，超出时知识库页提示精简
    pinned_token_limit: int = Field(default=2000, gt=0)
    auto_extract: bool = True  # 每次运行结束后自动从对话里提取记忆
    chunk_tokens: int = Field(default=600, gt=0)  # 文档每块约多少 token（设计文档 8.2）
    chunk_overlap_tokens: int = Field(default=80, ge=0)  # 相邻两块重叠多少 token
    # 每次向量化几段：本机向量模型一次只处理一个请求，对话里的查询要排在后面（M3b 先行探测）
    ingest_batch_size: int = Field(default=2, gt=0)

    @model_validator(mode="after")
    def _overlap_below_chunk(self) -> Self:
        if self.chunk_overlap_tokens >= self.chunk_tokens:
            raise ValueError("相邻两块的重叠要小于每块的大小")
        return self


class ModelSource(BaseModel):
    """模型页"新增模型"的来源：模型经它转发。

    密钥只写 .env 里已有变量的引用（页面不收密钥，D21）。
    """

    id: str
    label: str
    mode: Literal["chat", "embedding"]
    prefix: str  # 网关转给上游时模型名前面加的，如 litellm_proxy/
    api_base: str  # 可以是 os.environ/变量名
    api_key: str | None = None  # 只能是 os.environ/变量名


class ModelsConfig(BaseModel):
    sources: list[ModelSource] = [
        ModelSource(
            id="upstream",
            label="公司 LiteLLM 网关",
            mode="chat",
            prefix="litellm_proxy/",
            api_base="os.environ/UPSTREAM_GATEWAY_URL",
            api_key="os.environ/UPSTREAM_GATEWAY_KEY",
        ),
        # 与默认模型清单 config/seed/models.yaml 里的向量模型（source: ollama）一致
        ModelSource(
            id="ollama",
            label="本机 Ollama",
            mode="embedding",
            prefix="ollama/",
            api_base="http://ollama:11434",
        ),
    ]


class AgentConfig(BaseModel):
    """主智能体配置。"""

    default_model: str = "claude-opus-4-6"
    system_prompt_file: Path = ROOT_DIR / "agents" / "prompts" / "system.md"
    subagents_dir: Path = ROOT_DIR / "agents" / "subagents"  # 子智能体定义文件
    # 模型连续多少秒没发来新内容就放弃这次调用（网络断了、上游卡住时不一直挂着）
    stream_idle_timeout: float = Field(default=120, gt=0)


class Settings(BaseSettings):
    """全局配置。

    字段名即环境变量名（不区分大小写）；嵌套字段用双下划线，如 AGENT__DEFAULT_MODEL。
    """

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_nested_delimiter="__", extra="ignore"
    )

    database_url: str
    litellm_base_url: str = "http://127.0.0.1:4000"
    litellm_master_key: SecretStr
    workdata_dir: Path = ROOT_DIR / ".workdata"
    adapters: AdaptersConfig = AdaptersConfig()
    agent: AgentConfig = AgentConfig()
    # 上传上限（MB）：对话附件、知识库文档、技能包共用一个（设计 2026-10-19 4.5）
    max_upload_mb: int = Field(default=50, gt=0)
    workspace: WorkspaceConfig = WorkspaceConfig()
    knowledge: KnowledgeConfig = KnowledgeConfig()
    models: ModelsConfig = ModelsConfig()

    # .workdata 是唯一的数据目录（D22）：配置文件、技能都在这里，不再叠加 config/ 里的

    @property
    def config_dir(self) -> Path:
        return self.workdata_dir / "config"

    @property
    def mcp_servers_file(self) -> Path:
        return self.config_dir / "mcp_servers.yaml"

    @property
    def approval_rules_file(self) -> Path:
        return self.config_dir / "approval_rules.yaml"

    @property
    def skills_state_file(self) -> Path:
        """停用了哪些技能。"""
        return self.config_dir / "skills.yaml"

    @property
    def skills_dir(self) -> Path:
        """全部技能（首次启动写入的 excel 与上传的），都能停用、删除。"""
        return self.workdata_dir / "skills"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 优先级从高到低：构造参数 > 环境变量 > .env > 数据库里存的设置（D22）> 代码默认值；
        # 各来源逐项合并：数据库里只存改过的设置项
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _StoredSettings(settings_cls),
            file_secret_settings,
        )


class SettingSpec(BaseModel):
    """设置页上的一项设置（D22）：键是点分的字段路径，环境变量名由它推出（env_name）。"""

    key: str
    label: str
    apply: Literal["now", "restart"]  # 改了是立即生效，还是重启后端后生效
    editable: bool = True
    note: str | None = None


_ADAPTERS_NOTE = "目前每项只有一种实现"

# 设置页按这个顺序列出；只有默认对话模型立即生效（设计 2026-10-19 4.7）
SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(key="agent.default_model", label="默认对话模型", apply="now"),
    SettingSpec(
        key="agent.stream_idle_timeout",
        label="模型多少秒没有新内容就放弃这次调用",
        apply="restart",
    ),
    SettingSpec(key="workspace.command_timeout", label="命令默认时限（秒）", apply="restart"),
    SettingSpec(key="workspace.max_command_timeout", label="命令最长时限（秒）", apply="restart"),
    SettingSpec(
        key="max_upload_mb",
        label="上传上限（MB，附件、知识库文档、技能包共用）",
        apply="restart",
    ),
    SettingSpec(
        key="knowledge.embedding_model",
        label="向量模型",
        apply="restart",
        editable=False,
        note="换向量模型要把知识库全部重新向量化（R31）",
    ),
    SettingSpec(key="knowledge.recall_top_k", label="每次带上的相关记忆最多几条", apply="restart"),
    SettingSpec(
        key="knowledge.recall_min_similarity",
        label="相关记忆的相似度下限（0～1）",
        apply="restart",
    ),
    SettingSpec(key="knowledge.recall_timeout", label="找相关记忆最多等几秒", apply="restart"),
    SettingSpec(
        key="knowledge.pinned_token_limit", label="常驻条目的上限（token）", apply="restart"
    ),
    SettingSpec(key="knowledge.auto_extract", label="每次对话后自动整理记忆", apply="restart"),
    SettingSpec(key="knowledge.chunk_tokens", label="文档每块约多少 token", apply="restart"),
    SettingSpec(
        key="knowledge.chunk_overlap_tokens", label="相邻两块重叠多少 token", apply="restart"
    ),
    SettingSpec(
        key="knowledge.ingest_batch_size", label="文档入库时每次向量化几段", apply="restart"
    ),
    *(
        SettingSpec(
            key=f"adapters.{name}",
            label=f"{label}的实现",
            apply="restart",
            editable=False,
            note=_ADAPTERS_NOTE,
        )
        for name, label in (
            ("model_gateway", "模型网关"),
            ("workspace", "工作区"),
            ("embedder", "向量化"),
            ("knowledge_index", "知识库索引"),
            ("doc_parser", "文档解析"),
            ("blob_storage", "原文件存储"),
            ("mcp_client", "MCP 客户端"),
        )
    ),
    SettingSpec(
        key="models.sources",
        label="模型来源（模型页新增模型时选）",
        apply="restart",
        editable=False,
        note="来源里有网关地址，页面上不能改",
    ),
)


def env_name(key: str) -> str:
    """设置键对应的环境变量名：嵌套用双下划线，如 agent.default_model → AGENT__DEFAULT_MODEL。"""
    return key.replace(".", "__").upper()


def read_setting(settings: BaseModel, key: str) -> Any:
    """按点分的键取一项设置的值（转成 JSON 能表示的形式，接口与设置表都用它）。"""
    value: Any = settings
    for part in key.split("."):
        value = getattr(value, part)
    return to_jsonable_python(value)


# load_settings 把数据库里存的设置交给 _StoredSettings；用上下文变量传，测试的 Settings 子类照样适用
_stored: ContextVar[Mapping[str, Any] | None] = ContextVar("stored_settings", default=None)


def load_settings(
    stored: Mapping[str, Any] | None = None, *, settings_cls: type[Settings] | None = None
) -> Settings:
    """按"默认值 → stored → 环境变量"读取设置；stored 的键是点分的设置键（数据库里存的）。

    存的某一项不合规（手改坏了）时去掉这一项再读，并记日志：不能因此让后端起不来。
    """
    cls = settings_cls or Settings
    values = dict(stored or {})
    for _ in range(len(values) + 1):
        token = _stored.set(values)
        try:
            return cls()
        except ValidationError as exc:
            bad = {key for key in values if any(_matches(key, err["loc"]) for err in exc.errors())}
            if not bad:
                raise
            logger.warning("数据库里存的设置不合规，先按默认值：%s", "、".join(sorted(bad)))
            values = {key: value for key, value in values.items() if key not in bad}
        finally:
            _stored.reset(token)
    return cls()


def _matches(key: str, loc: tuple[int | str, ...]) -> bool:
    """这条错误出在这一项上；跨项的错误（如 workspace 里两项不一致）算在这一节存的每一项上。"""
    parts = key.split(".")
    path = [str(item) for item in loc]
    shorter = min(len(parts), len(path))
    return parts[:shorter] == path[:shorter]


def _nested(values: Mapping[str, Any]) -> dict[str, Any]:
    """{"agent.default_model": "m"} → {"agent": {"default_model": "m"}}。"""
    result: dict[str, Any] = {}
    for key, value in values.items():
        *sections, field = key.split(".")
        node = result
        for section in sections:
            node = node.setdefault(section, {})
        node[field] = value
    return result


class _StoredSettings(PydanticBaseSettingsSource):
    """数据库里存的设置这一层来源（D22）：内容由 load_settings 给出。"""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return _nested(_stored.get() or {})


@lru_cache
def get_settings() -> Settings:
    """只读环境变量与 .env（启动时先用它连数据库，再用 load_settings 读数据库里的设置）。"""
    return Settings()
