"""工具真正开始执行的时间（设计 2026-10-23 5.7）。

tool.started 在模型给出工具调用时就推了；要审批的工具之后还要等你决定，用那个时间算用时会把等你的
时间也算进去。这个中间件包住工具调用：轮到工具真正执行时，经 LangGraph 的自定义流推一个
tool.running（流模式里要有 custom），翻译器把它翻成事件。被拒绝的调用不经过这里，也就没有；
它排在 MCP 调用中间件之后，暂停挡下的调用同样没有。

后端按这个事件记工具用量（设计 2026-10-23 6.8）：带上工具名，读技能说明时再带上技能名。
"""

import posixpath
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

TOOL_RUNNING = "tool.running"
# 派出子智能体的调用：界面上显示成子智能体卡片、不显示用时；恢复审批时它还会重新执行一遍
_SUBAGENT_TOOL = "task"
_SKILL_FILE = re.compile(r"^/skills/([^/]+)/SKILL\.md$")


def skill_of(name: str, args: Mapping[str, Any]) -> str | None:
    """读技能说明（/skills/<技能>/SKILL.md）时返回技能名；分页往下读的不再算一次。"""
    path = args.get("file_path")
    if name != "read_file" or not isinstance(path, str) or args.get("offset") not in (None, 0):
        return None
    match = _SKILL_FILE.match(posixpath.normpath(path))
    return match[1] if match else None


class ToolRunningMiddleware(AgentMiddleware):
    """工具开始执行前推 {"type": "tool.running", "call_id", "name", "skill"}。"""

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        call_id, name = call.get("id"), call["name"]
        if call_id and name != _SUBAGENT_TOOL:
            skill = skill_of(name, call.get("args") or {})
            request.runtime.stream_writer(
                {"type": TOOL_RUNNING, "call_id": call_id, "name": name, "skill": skill}
            )
        return await handler(request)
