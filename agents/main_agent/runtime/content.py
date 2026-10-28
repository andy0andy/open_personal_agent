"""消息内容的小工具：翻译器、标题生成、上下文分段、压缩都要从消息里取纯文本。"""

from typing import Any


def text_of(content: str | list[Any]) -> str:
    """取出消息内容中的纯文本；内容块形式（如 Anthropic）只拼接 text 块。"""
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
