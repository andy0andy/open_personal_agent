"""设置接口的请求与返回结构（MCP 服务、技能上传、审批规则）。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from agents.main_agent.integrations import McpServerStatus
from config.integrations import ApprovalMode


class McpServerInput(BaseModel):
    """页面上填的一个服务（未替换 ${变量} 的原文）；名字同时是工具名前缀。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    transport: Literal["stdio", "streamable_http", "sse"] = "stdio"
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    headers: dict[str, str] = {}

    def entry(self) -> dict[str, Any]:
        """写进用户文件的那一条（不含名字；名字是键）。"""
        return self.model_dump(exclude={"name"}, exclude_none=True)

    @classmethod
    def from_raw(cls, name: str, raw: dict[str, Any]) -> "McpServerInput":
        fields = {key: raw[key] for key in cls.model_fields if key in raw and key != "name"}
        return cls.model_validate({**fields, "name": name})


class McpServersInput(BaseModel):
    servers: list[McpServerInput]


class McpServerView(McpServerStatus):
    missing_env: list[str]
    config: McpServerInput  # 编辑用的原文：密钥写成 ${变量名}，页面上看不到真实的值


class McpServersView(BaseModel):
    servers: list[McpServerView]
    config_error: str | None  # 配置文件写错的原因


class SkillUploadFile(BaseModel):
    path: str  # 相对路径；选择文件夹时带着文件夹名，如 周报写作/SKILL.md
    content: str  # base64


class SkillUpload(BaseModel):
    """上传技能（D21）：文件内容用 base64 放进 JSON，不依赖表单上传的库。"""

    files: list[SkillUploadFile]


class EnabledInput(BaseModel):
    enabled: bool


class ToolActionInput(BaseModel):
    action: ApprovalMode
