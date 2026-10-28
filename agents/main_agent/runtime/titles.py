"""会话标题生成：第一次顺利结束后，用会话所选的模型按对话内容起一个简短的标题。

在此之前会话标题是首条消息的前 30 个字（backend 在发起运行时填上）。
"""

import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agents.main_agent.runtime.content import text_of

TITLE_LENGTH = 30
_MESSAGE_LIMIT = 2000
_ANSWER_LIMIT = 1000

TITLE_PROMPT = (
    "根据下面这轮对话，给这个会话起一个简短的标题：不超过 15 个字，概括用户想做的事，"
    "用对话所用的语言；不加引号、标点和“标题：”这类前缀。只回复标题本身。"
)

# 模型常在标题外面加的引号、书名号、加粗记号与结尾标点
_WRAPPING = " \t\"'“”‘’《》「」『』*`#。.!！?？,，;；:："
_PREFIX = re.compile(r"^(标题|title)\s*[:：]\s*", re.IGNORECASE)


async def generate_title(
    model: BaseChatModel, *, message: str, answer: str, config: RunnableConfig | None = None
) -> str:
    """起一个标题；模型什么都没给时返回空字符串（由调用方保留原标题）。"""
    reply = await model.ainvoke(
        [
            SystemMessage(TITLE_PROMPT),
            HumanMessage(f"用户：{message[:_MESSAGE_LIMIT]}\n助手：{answer[:_ANSWER_LIMIT]}"),
        ],
        config=config,
    )
    return clean_title(text_of(reply.content))


def clean_title(text: str) -> str:
    """取第一行，去掉"标题："前缀、外面的引号与结尾标点，最长 30 个字。"""
    line = next((line for line in text.splitlines() if line.strip(_WRAPPING)), "")
    line = _PREFIX.sub("", line.strip(_WRAPPING)).strip(_WRAPPING)
    return line[:TITLE_LENGTH]
