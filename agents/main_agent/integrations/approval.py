"""工具审批规则判定（设计文档 7.5）：每个工具"自动执行"还是"先问你"。

先看会话的审批权限（D23）："跳过所有审批"一律自动；"只问执行命令"只有执行命令先问。
"每次先问"（默认）按顺序：规则文件里第一条匹配的为准（支持 * 通配）→ 没写到的内置工具
自动执行 → 没写到的 MCP 工具，服务声明只读的自动执行，其余按 mcp_default。
"""

from collections.abc import Sequence
from fnmatch import fnmatchcase
from typing import Literal

from pydantic import BaseModel

from agents.main_agent.integrations.mcp import McpTool
from config import ApprovalRulesConfig
from config.integrations import ApprovalMode

EXECUTE_ALWAYS_ASKS = "执行命令每次先问（固定，D21）"

# 会话的审批权限（D23）：每次先问 / 只问执行命令 / 跳过所有审批
PermissionMode = Literal["ask", "ask_execute", "skip"]


class ToolApproval(BaseModel):
    """一个工具的审批方式与原因（设置页显示）。内置工具的 server 为 None。"""

    name: str
    server: str | None
    action: ApprovalMode
    reason: str
    read_only: bool | None = None  # 服务声明的"只读"（MCP 页标出来）；内置工具为 None


class ApprovalPolicy:
    def __init__(self, rules: ApprovalRulesConfig) -> None:
        self.rules = rules

    def decide(
        self,
        name: str,
        *,
        server: str | None,
        read_only: bool | None,
        mode: PermissionMode = "ask",
    ) -> ToolApproval:
        is_execute = name == "execute" and server is None
        if mode == "skip":
            return ToolApproval(
                name=name,
                server=server,
                action="auto",
                reason="本会话跳过所有审批",
                read_only=read_only,
            )
        if mode == "ask_execute":
            if is_execute:
                return ToolApproval(
                    name=name, server=None, action="ask", reason="本会话只问执行命令"
                )
            return ToolApproval(
                name=name,
                server=server,
                action="auto",
                reason="本会话只问执行命令，其余自动",
                read_only=read_only,
            )
        # 命令与后端在同一个环境里、能上网（D20），而用户的规则文件被同意的命令改得动（D21）：
        # 任何规则（含通配）都放宽不了执行命令
        if is_execute:
            return ToolApproval(name=name, server=None, action="ask", reason=EXECUTE_ALWAYS_ASKS)
        for pattern, action in self.rules.tools.items():
            if fnmatchcase(name, pattern):
                return ToolApproval(
                    name=name,
                    server=server,
                    action=action,
                    reason=f"规则 {pattern}",
                    read_only=read_only,
                )
        if server is None:
            return ToolApproval(
                name=name, server=None, action="auto", reason="内置工具默认自动执行"
            )
        if read_only is True:
            return ToolApproval(
                name=name, server=server, action="auto", reason="服务声明为只读", read_only=True
            )
        return ToolApproval(
            name=name,
            server=server,
            action=self.rules.mcp_default,
            reason="MCP 工具默认（mcp_default）",
            read_only=read_only,
        )

    def table(
        self,
        builtin: Sequence[str],
        mcp_tools: Sequence[McpTool],
        mode: PermissionMode = "ask",
    ) -> list[ToolApproval]:
        """全部工具的判定结果：先 MCP 工具，再内置工具。"""
        return [
            *(
                self.decide(t.name, server=t.server, read_only=t.read_only, mode=mode)
                for t in mcp_tools
            ),
            *(self.decide(name, server=None, read_only=None, mode=mode) for name in builtin),
        ]
