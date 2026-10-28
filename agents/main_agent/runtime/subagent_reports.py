"""子智能体交回的报告太长时存进会话目录（设计 2026-10-23 5.10）。

子智能体交回的内容会整段进入主智能体的上下文。超过 4000 字时把全文写进本会话的
reports/子智能体-<名字>-<时间>.md，交回的只留开头，再说一句完整报告在哪：主智能体要细节时自己读。
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agents.main_agent.context import AgentContext
from agents.main_agent.runtime.content import text_of

logger = logging.getLogger(__name__)

REPORT_LIMIT = 4000
_SUBAGENT_TOOL = "task"
_UNSAFE = re.compile(r"[^\w-]")  # 子智能体名进文件名：只留字母、数字、汉字、下划线和连字符


class SubagentReportMiddleware(AgentMiddleware):
    """主智能体的 task 调用：交回的报告超过 limit 字时全文存进 reports/，只交回开头。"""

    def __init__(self, backend: BackendProtocol, *, limit: int = REPORT_LIMIT) -> None:
        super().__init__()
        self._backend = backend
        self._limit = limit

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        if request.tool_call["name"] != _SUBAGENT_TOOL:
            return result
        if isinstance(result, ToolMessage):
            return await self._shorten(result, request)
        # deepagents 的 task 工具交回 Command：报告在它的消息更新里，其余的状态更新原样保留
        if isinstance(result, Command) and isinstance(result.update, dict):
            messages = result.update.get("messages")
            if isinstance(messages, list):
                shortened = [
                    await self._shorten(message, request)
                    if isinstance(message, ToolMessage)
                    and message.tool_call_id == request.tool_call["id"]
                    else message
                    for message in messages
                ]
                return replace(result, update={**result.update, "messages": shortened})
        return result

    async def _shorten(self, message: ToolMessage, request: ToolCallRequest) -> ToolMessage:
        text = text_of(message.content)
        if len(text) <= self._limit:
            return message
        name = _UNSAFE.sub("_", str(request.tool_call["args"].get("subagent_type") or "通用"))
        # 文件名带上这次调用的标识：并行派出的子智能体同一秒交回时各存一份（审查 I5）
        tag = _UNSAFE.sub("", request.tool_call.get("id") or "")[-8:] or uuid4().hex[:8]
        short_id = cast(AgentContext, request.runtime.context).thread_short_id
        path = await self._save(f"/workspace/{short_id}/reports/子智能体-{name}", tag, text)
        if path is None:  # 存不下来就整段交回，不丢内容
            return message
        head = text[: self._limit]
        return message.model_copy(update={"content": f"{head}\n\n（完整报告见 {path}）"})

    async def _save(self, prefix: str, tag: str, text: str) -> str | None:
        path = f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}-{tag}.md"
        written = await self._backend.awrite(path, text)
        if written.error is not None:
            logger.warning("子智能体的完整报告没能存进 %s：%s", path, written.error)
            return None
        return path
