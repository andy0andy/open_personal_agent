"""插话送达（设计 2026-10-23 6.3）：主智能体每次调用模型前，把这次运行里排着的插话追加进对话存档。

- 作为用户消息追加，正文开头注明是插话（附加字段不会发给模型）；同时推 user.interjected，
  界面在这一轮里显示成一条用户消息。
- 只给主智能体：子智能体在跑时，插话要等主智能体下一次调用模型才送达。
- 找"本轮第一条用户消息"的地方（中断说明、审批改参数的说明、上下文分段）要跳过插话：
  插话总接在工具结果后面，不是新的一轮。
"""

from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.runtime import Runtime

INTERJECTION_MARK = "（用户在你工作时插话）"
USER_INTERJECTED = "user.interjected"
_FLAG = "interjection"


def is_interjection(message: AnyMessage) -> bool:
    return isinstance(message, HumanMessage) and bool(message.additional_kwargs.get(_FLAG))


def turn_start(messages: list[AnyMessage]) -> int:
    """本轮第一条（不是插话的）用户消息的位置；没有时为 -1。"""
    return max(
        (
            i
            for i, message in enumerate(messages)
            if isinstance(message, HumanMessage) and not is_interjection(message)
        ),
        default=-1,
    )


class InterjectionMiddleware(AgentMiddleware):
    async def abefore_model(
        self, state: AgentState, runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        queue = getattr(runtime.context, "interjections", None)
        texts = queue.take() if queue is not None else []
        if not texts:
            return None
        messages: list[HumanMessage] = []
        for text in texts:
            message_id = str(uuid4())
            runtime.stream_writer({"type": USER_INTERJECTED, "id": message_id, "text": text})
            messages.append(
                HumanMessage(
                    content=INTERJECTION_MARK + text, id=message_id, additional_kwargs={_FLAG: True}
                )
            )
        return {"messages": messages}
