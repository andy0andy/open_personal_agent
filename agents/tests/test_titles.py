"""会话标题生成：第一次顺利结束后，用会话所选的模型起一个简短的标题。"""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.runtime import MainAgent, clean_title
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox, ScriptedChatModel


@pytest.mark.parametrize(
    ("reply", "title"),
    [
        ("周报模板", "周报模板"),
        ("《周报模板》", "周报模板"),
        ('"写周报模板"。\n', "写周报模板"),
        ("标题：Python 数据清洗\n（概括了用户的需求）", "Python 数据清洗"),
        ("**整理会议纪要**", "整理会议纪要"),
        ("一" * 40, "一" * 30),  # 太长时截断
        ("\n\n", ""),
    ],
)
def test_clean_title(reply: str, title: str) -> None:
    assert clean_title(reply) == title


async def test_main_agent_generates_a_title_and_reports_usage(tmp_path: object) -> None:
    reply = AIMessage(
        "《周报模板》",
        usage_metadata={"input_tokens": 120, "output_tokens": 6, "total_tokens": 126},
    )
    model = ScriptedChatModel(responses=[reply])
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),  # type: ignore[arg-type]
    )
    title, usage = await agent.generate_title(
        thread_id="t1",
        run_id="r1",
        model="m",
        message="帮我写个周报模板",
        answer="好的，下面是周报模板……",
    )
    assert title == "周报模板"
    assert [(u.caller, u.input_tokens) for u in usage] == [("title", 120)]
    prompt = "\n".join(str(message.content) for message in model.received[0])
    assert "帮我写个周报模板" in prompt
    assert "好的，下面是周报模板" in prompt
