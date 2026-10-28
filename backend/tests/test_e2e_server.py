"""端到端测试用的后端：只能用测试库；假模型按关键词走剧本。"""

import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agents.tests.fakes import KeywordChatModel, call


def test_e2e_server_refuses_a_non_test_database() -> None:
    from backend.tests.e2e_server import build_e2e_app

    with pytest.raises(RuntimeError, match="端到端测试只能用测试库"):
        build_e2e_app("postgresql://agent:agent@127.0.0.1:5432/agent")


def test_e2e_workdata_is_reused_and_cleared(tmp_path: Path) -> None:
    """端到端的 .workdata 放在固定位置、每次启动先清空（积压小问题 I7）：
    Playwright 停服务时直接强杀，收尾删不掉，原来每次新建的临时目录越积越多。"""
    from backend.tests.e2e_server import E2E_WORKDATA, _fresh_workdata

    assert E2E_WORKDATA.parent == Path(tempfile.gettempdir())
    target = tmp_path / E2E_WORKDATA.name  # 不碰真正的位置：可能正有端到端测试在用
    first = _fresh_workdata(target)
    (first / "config").mkdir()
    (first / "config" / "left.yaml").write_text("上次留下的", encoding="utf-8")
    assert _fresh_workdata(target) == first
    assert list(first.iterdir()) == []


def test_e2e_workdata_that_cannot_be_cleared_says_why(tmp_path: Path) -> None:
    """清不掉时报出真正的原因（删不掉的文件），而不是紧接着建目录时的"已存在"（审查 Minor 8）。"""
    from backend.tests.e2e_server import _fresh_workdata

    target = _fresh_workdata(tmp_path / "opa-e2e-workdata")
    locked = target / "locked"
    locked.mkdir()
    (locked / "a.txt").write_text("删不掉", encoding="utf-8")
    locked.chmod(0o500)  # 里面的文件删不掉
    try:
        with pytest.raises(PermissionError):
            _fresh_workdata(target)
    finally:
        locked.chmod(0o700)


async def test_keyword_model_follows_scripts() -> None:
    model = KeywordChatModel(
        scripts=[("看看目录", [call("ls", {"path": "/"}, "c1"), AIMessage("目录看完了")])],
        default="好的",
    )
    first = await model.ainvoke([HumanMessage("帮我看看目录")])
    assert first.tool_calls[0]["name"] == "ls"
    second = await model.ainvoke(
        [
            HumanMessage("帮我看看目录"),
            first,
            ToolMessage("a.txt", tool_call_id="c1"),
        ]
    )
    assert second.content == "目录看完了"
    other = await model.ainvoke([SystemMessage("生成标题"), HumanMessage("随便聊聊")])
    assert other.content == "好的"
    assert first.usage_metadata is not None
    assert first.usage_metadata["input_tokens"] == 100
    assert first.response_metadata["response_cost"] == pytest.approx(0.001)


async def test_keyword_scripts_can_read_the_conversation() -> None:
    """剧本的一步可以按对话内容生成（如从系统提示词里取工作目录）。"""

    def write(messages: list[object]) -> AIMessage:
        return AIMessage(f"共 {len(messages)} 条")

    model = KeywordChatModel(scripts=[("写报告", [write])], default="好的")
    reply = await model.ainvoke([SystemMessage("工作目录 /workspace/c_1/"), HumanMessage("写报告")])
    assert reply.content == "共 2 条"
