"""换模型清理（设计文档 7.1）：会话中途换了模型时，请求里去掉新模型用不了的内容。

- 旧模型产生的思考内容（含签名）只对产生它的模型有效，交给别家模型可能被拒绝；
- 换到不能看图的模型时，历史里用户上传的图片换成一句说明（原样发过去会被拒绝）。

只在发给模型的请求里处理，对话存档保持原样，换回原模型时仍然完整。
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from agents.main_agent.models.base import version_name

_THINKING_KWARGS = frozenset({"reasoning_content", "thinking_blocks", "provider_specific_fields"})
_THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking", "reasoning"})
IMAGE_OMITTED = "[图片已省略：当前模型不能看图，可以用代码处理图片文件]"


def strip_foreign_thinking(message: AnyMessage, model: str) -> AnyMessage:
    """message 由其他模型版本产生时，去掉其中的思考内容；否则原样返回。"""
    if not isinstance(message, AIMessage):
        return message
    produced_by = message.response_metadata.get("model_name")
    if not produced_by or version_name(produced_by) == model:
        return message
    kwargs = {k: v for k, v in message.additional_kwargs.items() if k not in _THINKING_KWARGS}
    content: Any = message.content
    if isinstance(content, list):
        content = [
            block
            for block in content
            if not (isinstance(block, dict) and block.get("type") in _THINKING_BLOCKS)
        ]
    return message.model_copy(update={"additional_kwargs": kwargs, "content": content})


def strip_images(message: AnyMessage) -> AnyMessage:
    """用户消息里的图片换成一句说明；没有图片时原样返回。"""
    content = message.content
    if not isinstance(message, HumanMessage) or not isinstance(content, list):
        return message
    if not any(isinstance(b, dict) and b.get("type") == "image_url" for b in content):
        return message
    replaced = [
        {"type": "text", "text": IMAGE_OMITTED}
        if isinstance(block, dict) and block.get("type") == "image_url"
        else block
        for block in content
    ]
    return message.model_copy(update={"content": replaced})


class ModelSwitchCleanupMiddleware(AgentMiddleware):
    """每次调用模型前清理请求里的消息；model 为当前使用的模型版本名。

    vision 每次调用时才问"它能否看图"：模型信息来自网关，启动时网关可能还没就绪，
    而这个中间件随组装好的智能体一直缓存到重启。
    """

    def __init__(self, model: str, *, vision: Callable[[], bool]) -> None:
        super().__init__()
        self._model = model
        self._vision = vision

    def _clean(self, request: ModelRequest) -> ModelRequest:
        messages = [strip_foreign_thinking(m, self._model) for m in request.messages]
        if not self._vision():
            messages = [strip_images(m) for m in messages]
        return request.override(messages=messages)

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return handler(self._clean(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._clean(request))
