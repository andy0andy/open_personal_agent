"""上下文占用分段（设计 2026-10-23 4.7）：最终请求里系统提示词、常驻记忆、工具定义、相关记忆、
对话历史各占多少 token。

常驻记忆是系统提示词里从资料说明到 `</user_profile>` 的那一段（它后面可能还接着技能清单，
技能清单算系统提示词）；相关记忆取本轮用户消息开头系统附加的那段（D24）；工具定义单独数；
历史 = 整体 − 其余四项。整体用跟踪器已经算好的估算，不重复分词。各项乘以该模型的
校准比例（实际 / 估算），与用量明细的口径接近。
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agents.main_agent.models import estimate_input_tokens, estimate_text_tokens
from agents.main_agent.runtime.content import text_of
from agents.main_agent.runtime.events import ContextUsage
from agents.main_agent.runtime.interjection import is_interjection
from agents.main_agent.runtime.knowledge import MATERIAL_NOTE, split_related

_PROFILE_END = "</user_profile>"


def context_usage(
    messages: Sequence[BaseMessage],
    tools: Sequence[dict[str, Any]] | None,
    *,
    whole: int,
    ratio: float,
    limit: int | None,
) -> ContextUsage:
    """一次模型调用的上下文分段。whole 是整个请求（消息 + 工具定义）的估算；ratio 是该模型的
    校准比例，limit 是模型的上下文上限。"""
    tools_part = estimate_input_tokens([], tools) if tools else 0
    first = messages[0] if messages else None
    system_text = text_of(first.content) if isinstance(first, SystemMessage) else ""
    profile_text = _profile_block(system_text)
    profile = estimate_text_tokens(profile_text) if profile_text else 0
    rest = system_text.replace(profile_text, "", 1) if profile_text else system_text
    system = estimate_text_tokens(rest) if rest else 0
    related = estimate_text_tokens(_related(messages))
    history = max(0, whole - tools_part - system - profile - related)
    parts = [round(part * ratio) for part in (system, profile, tools_part, related, history)]
    return ContextUsage(
        system=parts[0],
        profile=parts[1],
        tools=parts[2],
        related=parts[3],
        history=parts[4],
        total=sum(parts),
        max_input_tokens=limit,
    )


def _profile_block(system_text: str) -> str:
    """系统提示词里的常驻记忆：从资料说明到 </user_profile> 为止（没有结束标记时到末尾）。"""
    start = system_text.find(MATERIAL_NOTE)
    if start < 0:
        return ""
    end = system_text.find(_PROFILE_END, start)
    return system_text[start:] if end < 0 else system_text[start : end + len(_PROFILE_END)]


def _related(messages: Sequence[BaseMessage]) -> str:
    """本轮用户消息（最后一条不是摘要的用户消息）开头系统附加的相关记忆。"""
    for message in reversed(messages):
        if (
            isinstance(message, HumanMessage)
            and message.additional_kwargs.get("lc_source") != "summarization"
            and not is_interjection(message)  # 插话不带相关记忆（设计 2026-10-23 6.3）
        ):
            return split_related(text_of(message.content))[0]
    return ""
