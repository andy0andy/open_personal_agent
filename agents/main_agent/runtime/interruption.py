"""中断标记：被停止、服务停止或崩溃打断的那一轮，没有最终回答存进对话存档。

模型下一轮看到"用户请求后面没有回答"，会把被打断的请求当成尚未完成而重做（例如停止一篇长文后
随便问一句，它会把整篇文章重写一遍）。每次运行开始前，在这类位置补一条"已中断"的回答。
被打断的工具调用由 deepagents 的 PatchToolCallsMiddleware 补上结果，两者配合后消息顺序始终合法。
"""

from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

from agents.main_agent.runtime.interjection import is_interjection

# 中断的原因（D23）：写进说明，下一轮模型知道为什么停在这里
STOPPED = "用户停止或服务中断"
STALLED = "模型长时间没有响应"
QUOTA = "模型额度用完"
_REASON_LIMIT = 100

# 额度用完时这次运行的结束原因（给用户看）
QUOTA_EXHAUSTED = (
    "模型额度用完了（模型服务返回余额或配额不足）。已输出的部分已保存，充值后说“继续”接着做。"
)


def interrupted_note(reason: str) -> str:
    """写在被打断的那一轮后面的说明；reason 是上面几种原因之一，或 failed_reason 的结果。"""
    return (
        f"（上一轮任务在此处被中断（{reason}），尚未完成；上文是中断前已完成的部分。"
        "如果用户接下来的话表示要继续，就从中断处接着把这个任务做完：沿用已完成的内容和步骤，"
        "不要从头重做已经写出的内容或已经执行过的操作。如果用户提出了别的要求，就按新要求处理，"
        "不要主动继续被中断的任务。）"
    )


def failed_reason(error: BaseException) -> str:
    """调用出错时的原因：异常文字的第一行（太长截断，没有文字时用异常类名）。"""
    first_line = (str(error).strip().splitlines() or [type(error).__name__])[0]
    return f"调用出错：{first_line[:_REASON_LIMIT]}"


INTERRUPTED_NOTE = interrupted_note(STOPPED)  # 原因未知时（如服务崩溃后的下一轮）用它


def mark_interruptions(messages: list[AnyMessage]) -> list[AnyMessage] | None:
    """在每条用户消息前检查上一轮是否有最终回答，没有就补一条中断说明；没有改动时返回 None。"""
    patched: list[AnyMessage] = []
    changed = False
    for message in messages:
        # 插话接在工具结果后面、是同一轮里的话（设计 2026-10-23 6.3），不是被打断后的新一轮
        if (
            isinstance(message, HumanMessage)
            and not is_interjection(message)
            and patched
            and _unfinished(patched[-1])
        ):
            patched.append(AIMessage(content=INTERRUPTED_NOTE))
            changed = True
        patched.append(message)
    return patched if changed else None


def _unfinished(previous: AnyMessage) -> bool:
    """上一条消息说明那一轮没有最终回答：用户消息、工具结果，或带工具调用的回答。"""
    if isinstance(previous, HumanMessage):
        # 上下文压缩后的摘要以用户消息的形式出现，后面紧跟用户消息是正常的
        return previous.additional_kwargs.get("lc_source") != "summarization"
    if isinstance(previous, ToolMessage):
        return True
    return isinstance(previous, AIMessage) and bool(previous.tool_calls)


class InterruptionMarkerMiddleware(AgentMiddleware):
    """每次运行开始前补上中断说明（写回对话存档，之后每一轮都能看到）。"""

    def before_agent(self, state: AgentState, runtime: Runtime[Any]) -> dict[str, Any] | None:
        patched = mark_interruptions(state["messages"])
        if patched is None:
            return None
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *patched]}
