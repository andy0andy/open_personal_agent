from langchain_core.messages import AIMessage, HumanMessage

from agents.main_agent.models.cleanup import IMAGE_OMITTED, strip_foreign_thinking, strip_images

THINKING = {"reasoning_content": "想一想", "provider_specific_fields": {"signature": "s"}}


def _answer(model: str) -> AIMessage:
    return AIMessage(
        content=[{"type": "thinking", "thinking": "想"}, {"type": "text", "text": "好"}],
        additional_kwargs={**THINKING, "other": 1},
        response_metadata={"model_name": f"litellm_proxy/{model}"},
    )


def test_thinking_from_another_model_is_removed() -> None:
    cleaned = strip_foreign_thinking(_answer("claude-opus-4-6"), "gemini-3.5-flash")
    assert cleaned.additional_kwargs == {"other": 1}
    assert cleaned.content == [{"type": "text", "text": "好"}]


def test_same_model_and_other_messages_are_untouched() -> None:
    answer = _answer("claude-opus-4-6")
    assert strip_foreign_thinking(answer, "claude-opus-4-6") is answer
    question = HumanMessage(content="hi")
    assert strip_foreign_thinking(question, "gemini-3.5-flash") is question
    unknown = AIMessage(content="x", additional_kwargs=THINKING)  # 不知道来自哪个模型时不动
    assert strip_foreign_thinking(unknown, "gemini-3.5-flash") is unknown


def test_images_are_replaced_for_models_that_cannot_see() -> None:
    """换到不能看图的模型时，历史里的图片换成一句说明（原样发过去会被拒绝）；对话存档不变。"""
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    question = HumanMessage(content=[{"type": "text", "text": "看图"}, image])
    assert strip_images(question).content == [
        {"type": "text", "text": "看图"},
        {"type": "text", "text": IMAGE_OMITTED},
    ]
    assert question.content[1] == image
    plain = HumanMessage(content="hi")
    assert strip_images(plain) is plain
