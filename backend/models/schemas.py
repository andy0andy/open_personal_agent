"""模型页接口的请求与返回结构。"""

from typing import Literal

from pydantic import BaseModel, Field

from agents.main_agent.models import ModelInfo
from config.settings import ModelSource

# 网关里的模型名也出现在接口地址里：字母、数字开头，只用字母、数字和 . _ : -
_MODEL_NAME = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"


class ModelInput(BaseModel):
    """页面上新增 / 修改的一个模型。价格是"美元 / 每百万 token"，免费填 0（任何统计都不用价格）。"""

    name: str = Field(pattern=_MODEL_NAME)
    source: str  # ModelsConfig.sources 里的 id
    upstream_id: str = Field(min_length=1)  # 厂商的模型 ID，网关转发时前面加上来源的前缀
    mode: Literal["chat", "embedding"] = "chat"
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    price_input: float = Field(ge=0, allow_inf_nan=False)
    price_output: float = Field(ge=0, allow_inf_nan=False)
    supports_reasoning: bool = False
    supports_vision: bool = False
    supports_function_calling: bool = False
    # 提示缓存（设计 2026-10-23 4.1）：只对 Claude 生效，别的模型勾了也不写进网关
    supports_prompt_caching: bool = False


class ModelView(ModelInfo):
    source_label: str  # 来源，如"公司 LiteLLM 网关"
    sessions: int  # 正在用它的会话数（删除前提示）
    is_default_chat: bool
    is_default_embedding: bool


class ModelsView(BaseModel):
    models: list[ModelView]
    default_chat: str
    default_embedding: str  # 只读：换向量模型要重新向量化整个知识库（R31）
    sources: list[ModelSource]


class DefaultInput(BaseModel):
    name: str


class DeleteResult(BaseModel):
    reassigned: int  # 改用默认模型的会话数
