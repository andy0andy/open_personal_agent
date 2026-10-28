"""粗略估算 token 数：模型调用被中断时网关不返回用量，只能按发送的内容和已输出的文字估算。

统一用 LiteLLM 自带的通用分词器（与具体模型无关），各模型的实际差异由调用方用实际用量校准。
"""

from collections.abc import Sequence
from typing import Any

import litellm
from langchain_core.messages import BaseMessage, convert_to_openai_messages

_TOKENIZER_MODEL = "gpt-4o"


def estimate_input_tokens(
    messages: Sequence[BaseMessage], tools: Sequence[dict[str, Any]] | None = None
) -> int:
    """发给模型的内容（消息 + 工具定义）大约多少 token。"""
    return int(
        litellm.token_counter(
            model=_TOKENIZER_MODEL,
            messages=convert_to_openai_messages(list(messages)),
            tools=list(tools) if tools else None,
        )
    )


def estimate_text_tokens(text: str) -> int:
    """一段输出文字大约多少 token。"""
    if not text:
        return 0
    return int(litellm.token_counter(model=_TOKENIZER_MODEL, text=text))
