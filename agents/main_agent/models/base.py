"""模型网关的可替换接口。"""

from typing import Any, Literal, Protocol

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

from common.errors import UpstreamError


def version_name(name: str) -> str:
    """去掉网关返回的模型名里的接入方式前缀（如 litellm_proxy/），得到版本名。"""
    return name.rsplit("/", 1)[-1]


class ModelStalledError(UpstreamError):
    """模型连续一段时间没有发来新内容（网络断了、上游卡住）：放弃这次调用，而不是一直等下去。

    started：卡住前有没有任何输出。没有时已经自动重发过一次（设计 2026-10-23 4.3），
    原因里不提"已生成的内容"。
    """

    def __init__(self, idle_seconds: float, *, started: bool = True) -> None:
        seconds = round(idle_seconds)
        if started:
            reason = (
                f"模型超过 {seconds} 秒没有发来新内容，可能是网络断了或模型服务卡住了。"
                "已生成的内容保留，可以说“继续”接着生成。"
            )
        else:
            reason = (
                f"模型超过 {seconds} 秒还没有开始输出（已自动重试过一次），"
                "可能是网络断了或模型服务卡住了。可以稍后重试这一轮，或换个模型。"
            )
        super().__init__(reason)
        self.idle_seconds = idle_seconds


class ModelInfo(BaseModel):
    """网关里登记的一个具体模型版本。"""

    # 导出的类型定义里，有默认值的字段也标为必有（接口返回时总带着它们）
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    mode: str = "chat"
    max_input_tokens: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None
    supports_reasoning: bool = False
    supports_vision: bool = False
    # 网关数据库里的部署编号（D22：模型全部在网关数据库里，凭它改、删）；
    # 写在 config/models.yaml 里的模型没有编号，页面上不能改
    id: str | None = None
    upstream: str | None = None  # 网关转给上游时用的模型名，如 litellm_proxy/claude-opus-4-6
    max_output_tokens: int | None = None
    supports_function_calling: bool = False
    # 网关按缓存断点给这个模型打提示缓存（设计 2026-10-23 4.1，只对 Claude）
    supports_prompt_caching: bool = False


class ModelSpec(BaseModel):
    """页面新增或修改的一个模型，交给网关保存（价格单位：美元 / token）。"""

    name: str
    upstream: str
    api_base: str
    api_key: str | None = None  # 只写环境变量引用（os.environ/…），页面不收密钥（D21）
    mode: Literal["chat", "embedding"] = "chat"
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_cost_per_token: float
    output_cost_per_token: float
    supports_reasoning: bool = False
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_prompt_caching: bool = False
    extra_params: dict[str, Any] = {}  # 原样放进调用参数，如 Claude 的 thinking


class ModelTestResult(BaseModel):
    """模型页的"测试"：真的调一次（几个 token），记下用了多久或失败原因。"""

    ok: bool
    latency_ms: int
    error: str | None = None


class ModelGateway(Protocol):
    """按版本名提供聊天模型对象，并列出可用模型信息。"""

    async def list_models(self) -> list[ModelInfo]:
        """从网关拉取最新模型清单；网关不可用时抛出 UpstreamError。"""
        ...

    def chat_model(self, name: str) -> BaseChatModel:
        """返回指定版本的聊天模型对象（不发起网络请求）。"""
        ...

    def model_info(self, name: str) -> ModelInfo | None:
        """最近一次 list_models 得到的该版本信息（不发起网络请求）；没有时返回 None。"""
        ...

    async def add_model(self, spec: ModelSpec) -> ModelInfo:
        """在网关里新增一个模型（立即生效，不用重启网关）；网关拒绝时抛 UpstreamError。"""
        ...

    async def update_model(self, model_id: str, spec: ModelSpec) -> ModelInfo:
        """修改网关数据库里的模型（写在 config/models.yaml 里的没有部署编号，网关不让改）。"""
        ...

    async def delete_model(self, model_id: str) -> None:
        """删除网关数据库里的模型（写在 config/models.yaml 里的网关不让删）。"""
        ...

    async def test_model(self, name: str) -> ModelTestResult:
        """真的调用一次：对话模型生成 1 个 token，向量模型算一次向量。"""
        ...
