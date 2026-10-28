"""导出 Markdown（设计 2026-10-23 6.2）：按界面历史生成；不导出思考过程与工具输出。"""

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from agents.main_agent.runtime import BUILTIN_TOOLS
from backend.runs import RunHistory
from backend.runs.schemas import RunAttachment
from backend.runtime import EventEnvelope
from backend.threads import Thread
from backend.threads.export import to_markdown
from backend.threads.tool_labels import tool_label

THREAD = Thread(
    id=uuid.uuid4(),
    short_id="c_00000001",
    title="云南旅行",
    model="m",
    permission_mode="ask",
    created_at=datetime(2026, 10, 1, 9, tzinfo=UTC),
    updated_at=datetime(2026, 10, 1, 9, tzinfo=UTC),
)


def _run(
    message: str,
    events: list[tuple[str, dict[str, Any]] | tuple[str, dict[str, Any], list[str]]],
    *,
    run_id: UUID | None = None,
    retry_of: UUID | None = None,
    status: str = "completed",
    attachments: list[str] = (),  # type: ignore[assignment]
) -> RunHistory:
    run = run_id or uuid.uuid4()
    envelopes = [
        EventEnvelope(
            seq=i + 1,
            run_id=str(run),
            type=item[0],
            agent_path=item[2] if len(item) > 2 else ["main"],
            data=item[1],
        )
        for i, item in enumerate(events)
    ]
    return RunHistory(
        id=run,
        thread_id=THREAD.id,
        status=status,
        model="m",
        message=message,
        attachments=[
            RunAttachment(id=uuid.uuid4(), path=f"uploads/{name}", media_type="text/csv", size=1)
            for name in attachments
        ],
        error=None,
        created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        retry_of=retry_of,
        events=envelopes,
    )


def test_markdown_has_turns_tools_approvals_files_errors() -> None:
    call = {"call_id": "c1", "name": "execute", "args": {"command": "python a.py"}}
    action = {**call, "server": None, "description": "", "allowed": ["approve", "reject"]}
    first = _run(
        "帮我分析 a.csv",
        [
            ("message.delta", {"message_id": "m1", "text": "我先看看"}),
            ("tool.started", call),
            (
                "approval.required",
                {"requests": [{"interrupt_id": "i1", "agent_path": ["main"], "actions": [action]}]},
            ),
            (
                "approval.resolved",
                {"answers": [{"interrupt_id": "i1", "decisions": [{"type": "approve"}]}]},
            ),
            ("tool.finished", {**call, "status": "success", "output": "合计 3"}),
            ("file.created", {"path": "outputs/chart.png", "file_id": "f", "size": 1}),
            ("message.delta", {"message_id": "m2", "text": "图表画好了"}),
            ("run.finished", {"status": "completed"}),
        ],
        attachments=["a.csv"],
    )
    second = _run(
        "再画一张",
        [("run.finished", {"status": "failed", "error": "RuntimeError: 网关不通"})],
        status="failed",
    )
    markdown = to_markdown(THREAD, [first, second])
    assert markdown.startswith("# 云南旅行")
    assert "## 第 1 轮" in markdown
    assert "## 第 2 轮" in markdown
    assert "帮我分析 a.csv" in markdown
    assert "附件：a.csv" in markdown
    assert markdown.index("我先看看") < markdown.index("执行命令") < markdown.index("图表画好了")
    assert "- 执行命令：python a.py" in markdown
    assert "已同意" in markdown
    assert "生成了文件：outputs/chart.png" in markdown
    assert "出错：RuntimeError: 网关不通" in markdown
    assert "合计 3" not in markdown  # 不导出工具输出


def test_thinking_and_subagent_internals_are_left_out() -> None:
    run = _run(
        "查一下",
        [
            ("thinking.delta", {"message_id": "m1", "text": "我在想……"}),
            (
                "subagent.started",
                {"call_id": "t1", "name": "general-purpose", "description": "查天气"},
            ),
            ("message.delta", {"message_id": "s1", "text": "子智能体的话"}, ["main", "t1"]),
            ("message.delta", {"message_id": "m1", "text": "晴"}),
        ],
    )
    markdown = to_markdown(THREAD, [run])
    assert "我在想" not in markdown
    assert "子智能体的话" not in markdown
    assert "派出子智能体：查天气" in markdown
    assert "晴" in markdown


def test_merged_answer_groups_are_not_duplicated() -> None:
    """收尾时合并过的回答：后一组带着前面的全文（full_text），只取最后那组。"""
    run = _run(
        "你好",
        [
            ("message.delta", {"message_id": "m1", "text": "你好，", "full_text": True}),
            ("message.delta", {"message_id": "m1", "text": "你好，我是助手", "full_text": True}),
        ],
    )
    markdown = to_markdown(THREAD, [run])
    assert markdown.count("你好，我是助手") == 1
    assert "你好，你好" not in markdown


def test_retried_turn_is_left_out() -> None:
    """ "重试这一轮"替换掉的那一轮不导出（界面上它收成一行）。"""
    failed = _run("整理发票", [("run.finished", {"status": "failed", "error": "超时"})])
    retried = _run(
        "整理发票",
        [("message.delta", {"message_id": "m1", "text": "整理好了"})],
        retry_of=failed.id,
    )
    markdown = to_markdown(THREAD, [failed, retried])
    assert "超时" not in markdown
    assert markdown.count("## 第") == 1
    assert "整理好了" in markdown


def test_every_builtin_tool_has_a_label() -> None:
    for name in BUILTIN_TOOLS:
        verb, _ = tool_label(name, {})
        assert verb not in (name, "外部工具"), name  # 带下划线的内置工具名不能被当成 MCP 工具
    assert tool_label("files_read_file", {"path": "/a"}) == ("外部工具", "files · read_file")
    assert tool_label("read_file", {"file_path": "/a.txt"}) == ("读取文件", "/a.txt")


def test_interjection_is_its_own_paragraph() -> None:
    """运行中插的话（设计 2026-10-23 6.3）：按送达的位置单独成段，标明是你插的话。"""
    run = _run(
        "写一段介绍",
        [
            ("message.delta", {"message_id": "m1", "text": "好的"}),
            ("user.interjected", {"id": "i1", "text": "改成英文"}),
            ("message.delta", {"message_id": "m2", "text": "OK"}),
        ],
    )
    markdown = to_markdown(THREAD, [run])
    assert "\n**你（插话）**：改成英文\n" in markdown
    assert markdown.index("好的") < markdown.index("改成英文") < markdown.index("OK")


def test_turn_times_are_in_the_given_timezone() -> None:
    """每轮的时间按浏览器所在时区写（8000 实测：原来按 UTC，北京时间 18:00 写成了 10:00）。"""
    run = _run("你好", [])
    assert "## 第 1 轮 · 2026-10-01 18:00" in to_markdown(THREAD, [run], ZoneInfo("Asia/Shanghai"))
    assert "## 第 1 轮 · 2026-10-01 10:00" in to_markdown(THREAD, [run])  # 没给时区时按 UTC
