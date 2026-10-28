"""执行命令的真实结果交给界面（设计 2026-10-23 5.4）。

deepagents 的执行工具只把退出码写进工具结果的附加信息（artifact），错误输出、是否超时都传不出来。
这个中间件在执行命令前放好结果列表（COMMAND_RESULTS），工作区执行完往里追加；工具结果回来后把
退出码、错误输出、是否超时并进附加信息，翻译器据此写进工具结束事件。给模型的文字不变。
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agents.main_agent.workspace import COMMAND_RESULTS, CommandResult

EXECUTE_TOOL = "execute"


class ExecuteResultMiddleware(AgentMiddleware):
    """把这次执行命令的退出码、错误输出、是否超时并进工具结果的附加信息。"""

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call["name"] != EXECUTE_TOOL:
            return await handler(request)
        results: list[CommandResult] = []
        token = COMMAND_RESULTS.set(results)
        try:
            response = await handler(request)
        finally:
            COMMAND_RESULTS.reset(token)
        if not results or not isinstance(response, ToolMessage):
            return response
        last = results[-1]
        artifact = dict(response.artifact) if isinstance(response.artifact, dict) else {}
        artifact.update(exit_code=last.exit_code, stderr=last.stderr, timed_out=last.timed_out)
        return response.model_copy(update={"artifact": artifact})
