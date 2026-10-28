from langchain_core.messages import HumanMessage, SystemMessage

from agents.main_agent.models import estimate_input_tokens, estimate_text_tokens

TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取工作区中的文件内容",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
}


def test_input_estimate_includes_tool_definitions() -> None:
    messages = [SystemMessage("你是助手。"), HumanMessage("写一篇长文")]
    without_tools = estimate_input_tokens(messages)
    assert without_tools > 0
    assert estimate_input_tokens(messages, [TOOL]) > without_tools


def test_text_estimate() -> None:
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("西游记读后感") > 0
