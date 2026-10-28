"""会话索引的接口（设计 2026-10-23 6.1）：以前的对话能按词搜、能前后翻看、能读整轮。

每次运行一行："用户原文 + 主智能体的回答全文"。由后端在运行收尾时写入（智能体模块拥有这张表），
删会话时删、改标题时同步；"重试这一轮"替换掉的那一轮删掉。轮次（turn）是同一会话里按开始时间
的序号，从 1 起，查询时现算。
"""

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel


class NewConversationTurn(BaseModel):
    thread_id: UUID
    run_id: UUID
    title: str
    started_at: datetime
    user_text: str
    answer_text: str


class ConversationTurn(NewConversationTurn):
    turn: int  # 同一会话里按开始时间的序号，从 1 起


class ConversationHit(BaseModel):
    turn: ConversationTurn
    snippet: str  # 命中词前后的一小段原文
    # 命中用的词（查询原文与分词结果，去掉单字词）：界面据此加粗——服务端按分词命中，
    # 界面只按空格切查询词时，"上海天气"命中"上海的天气"一个字也加粗不了
    terms: list[str] = []


class ConversationIndex(Protocol):
    async def index(self, turn: NewConversationTurn, *, replaces: UUID | None = None) -> None:
        """写入一轮（同一运行再写会覆盖）；replaces 是被"重试这一轮"替换掉的运行，一并删掉。"""
        ...

    async def retitle(self, thread_id: UUID, title: str) -> None: ...

    async def delete_thread(self, thread_id: UUID) -> None: ...

    async def search(self, query: str, *, limit: int = 10) -> list[ConversationHit]:
        """按词查：分词后任一词命中即可，越相关越靠前；查询里没有可用的词时为空。"""
        ...

    async def around(self, thread_id: UUID, run_id: UUID, window: int) -> list[ConversationTurn]:
        """某一轮与它前后各 window 轮（按轮次）；这一轮不在时为空。"""
        ...

    async def turn(self, thread_id: UUID, run_id: UUID) -> ConversationTurn | None: ...

    async def recent(self, limit: int) -> list[ConversationTurn]:
        """最近的会话：每个会话取最近一轮，新的在前。"""
        ...

    async def missing(self, run_ids: Sequence[UUID]) -> set[UUID]:
        """这些运行里还没有索引的（升级后补建用）。"""
        ...


SNIPPET_WIDTH = 60  # 命中词前后各取多少字
_SPACES = re.compile(r"\s+")


def hit_terms(words: Sequence[str]) -> list[str]:
    """给界面加粗用的词：去重、去掉单字词（到处都是），长的在前。"""
    return sorted({word for word in words if len(word) > 1}, key=len, reverse=True)


def snippet(turn: NewConversationTurn, words: Sequence[str]) -> str:
    """命中词前后各一小段原文（中文没有分词，用不了 ts_headline，在 Python 里截）；
    先找用户原文、再找回答，都没找到时取回答开头。"""
    for text in (turn.user_text, turn.answer_text):
        flat = _SPACES.sub(" ", text)
        lowered = flat.lower()
        found = [i for i in (lowered.find(word) for word in words if word) if i >= 0]
        if found:
            at = min(found)
            start, end = max(0, at - SNIPPET_WIDTH), at + SNIPPET_WIDTH
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(flat) else ""
            return f"{prefix}{flat[start:end]}{suffix}"
    flat = _SPACES.sub(" ", turn.answer_text)
    return flat[: SNIPPET_WIDTH * 2] + ("…" if len(flat) > SNIPPET_WIDTH * 2 else "")
