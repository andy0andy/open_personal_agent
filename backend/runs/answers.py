"""从界面历史里取这一轮的文字（标题生成、记忆提取、会话索引共用）。"""

from collections.abc import Sequence

from backend.runtime import EventEnvelope


def answer_text(events: Sequence[EventEnvelope]) -> str:
    """主智能体这次的回答全文：界面历史里的回答片段按出现顺序拼接（子智能体内部的不算）。"""
    texts: dict[str, str] = {}
    for event in events:
        if event.type != "message.delta" or len(event.agent_path) != 1:
            continue
        key, text = event.data["message_id"], event.data["text"]
        # 合并过的片段（full_text）带着这段回答到此为止的全文
        texts[key] = text if event.data.get("full_text") else texts.get(key, "") + text
    return "\n\n".join(texts.values())


def user_text(message: str, events: Sequence[EventEnvelope]) -> str:
    """这一轮用户说的话：原文加上送达了的插话（设计 2026-10-23 6.3）。"""
    interjections = [str(e.data["text"]) for e in events if e.type == "user.interjected"]
    return "\n\n".join([message, *interjections])
