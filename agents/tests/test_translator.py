from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import CustomStreamPart, MessagesStreamPart, UpdatesStreamPart

from agents.main_agent.runtime import (
    MessageDelta,
    SubagentFinished,
    SubagentStarted,
    ThinkingDelta,
    ThinkingFinished,
    ThinkingStarted,
    TodoItem,
    TodosUpdated,
    ToolFinished,
    ToolRunning,
    ToolStarted,
)
from agents.main_agent.runtime.tracker import RunTracker
from agents.main_agent.runtime.translator import TOOL_OUTPUT_LIMIT, Translator


def _messages(
    chunk: AIMessageChunk, ns: tuple[str, ...] = (), metadata: dict[str, Any] | None = None
) -> MessagesStreamPart:
    return {"type": "messages", "ns": ns, "data": (chunk, metadata or {})}


def _updates(data: dict[str, Any], ns: tuple[str, ...] = ()) -> UpdatesStreamPart:
    return {"type": "updates", "ns": ns, "data": data}


def _custom(data: Any, ns: tuple[str, ...] = ()) -> CustomStreamPart:
    return {"type": "custom", "ns": ns, "data": data}


def _translator() -> Translator:
    return Translator(RunTracker())


def test_message_chunk_becomes_delta() -> None:
    part = _messages(AIMessageChunk(content="你", id="m1"))
    assert list(_translator().translate(part)) == [MessageDelta(message_id="m1", text="你")]


def test_content_blocks_split_into_thinking_and_text() -> None:
    chunk = AIMessageChunk(
        content=[{"type": "thinking", "thinking": "想"}, {"type": "text", "text": "好"}], id="m1"
    )
    assert list(_translator().translate(_messages(chunk))) == [
        ThinkingStarted(message_id="m1"),
        ThinkingDelta(message_id="m1", text="想"),
        ThinkingFinished(message_id="m1"),
        MessageDelta(message_id="m1", text="好"),
    ]


def test_reasoning_content_from_gateway_becomes_thinking() -> None:
    chunk = AIMessageChunk(content="", id="m1", additional_kwargs={"reasoning_content": "先"})
    assert list(_translator().translate(_messages(chunk))) == [
        ThinkingStarted(message_id="m1"),
        ThinkingDelta(message_id="m1", text="先"),
    ]


def test_missing_chunk_id_falls_back_to_model_call_namespace() -> None:
    part = _messages(AIMessageChunk(content="x"), metadata={"langgraph_checkpoint_ns": "model:1"})
    assert list(_translator().translate(part)) == [MessageDelta(message_id="model:1", text="x")]


def test_compaction_summary_is_not_shown_as_answer() -> None:
    part = _messages(
        AIMessageChunk(content="摘要", id="s"), metadata={"lc_source": "summarization"}
    )
    assert list(_translator().translate(part)) == []


def test_empty_chunk_is_skipped() -> None:
    assert list(_translator().translate(_messages(AIMessageChunk(content="", id="m1")))) == []


def test_tool_call_and_result_from_updates() -> None:
    call = {"name": "ls", "args": {"path": "/"}, "id": "c1", "type": "tool_call"}
    started = _updates({"model": {"messages": [AIMessage(content="", tool_calls=[call])]}})
    result_message = ToolMessage(content="x" * 5000, tool_call_id="c1", name="ls")
    finished = _updates({"tools": {"messages": [result_message]}})
    translator = _translator()

    assert list(translator.translate(started)) == [
        ToolStarted(call_id="c1", name="ls", args={"path": "/"})
    ]
    [result] = list(translator.translate(finished))
    assert isinstance(result, ToolFinished)
    assert (result.call_id, result.status) == ("c1", "success")
    assert len(result.output) == TOOL_OUTPUT_LIMIT


def test_task_tool_becomes_subagent_events() -> None:
    args = {"description": "查一下天气", "subagent_type": "general-purpose"}
    call = {"name": "task", "args": args, "id": "c1", "type": "tool_call"}
    translator = _translator()

    [started] = translator.translate(
        _updates({"model": {"messages": [AIMessage(content="", tool_calls=[call])]}})
    )
    [finished] = translator.translate(
        _updates(
            {"tools": {"messages": [ToolMessage(content="晴", tool_call_id="c1", name="task")]}}
        )
    )

    assert started == SubagentStarted(
        call_id="c1", name="general-purpose", description="查一下天气"
    )
    assert finished == SubagentFinished(
        call_id="c1", name="general-purpose", status="success", output="晴"
    )


async def test_subagent_events_carry_agent_path_of_their_task_call() -> None:
    tracker = RunTracker()
    await tracker.on_tool_start(
        {},
        "",
        run_id=uuid4(),
        metadata={"langgraph_checkpoint_ns": "tools:ns-a"},
        tool_call_id="c1",
    )
    translator = Translator(tracker)
    part = _messages(AIMessageChunk(content="子", id="m2"), ns=("tools:ns-a",))
    assert list(translator.translate(part)) == [
        MessageDelta(agent_path=["main", "c1"], message_id="m2", text="子")
    ]


def test_todos_update_becomes_full_list() -> None:
    todos = [
        {"content": "查资料", "status": "in_progress"},
        {"content": "写总结", "status": "pending"},
    ]
    part = _updates({"tools": {"todos": todos, "messages": []}})
    assert list(_translator().translate(part)) == [
        TodosUpdated(
            todos=[
                TodoItem(content="查资料", status="in_progress"),
                TodoItem(content="写总结", status="pending"),
            ]
        )
    ]


def test_write_todos_tool_is_shown_only_as_todo_list() -> None:
    todos = [{"content": "查资料", "status": "pending"}]
    call = {"name": "write_todos", "args": {"todos": todos}, "id": "t1", "type": "tool_call"}
    translator = _translator()
    started = _updates({"model": {"messages": [AIMessage(content="", tool_calls=[call])]}})
    result = ToolMessage(content="Updated todo list", tool_call_id="t1", name="write_todos")
    finished = _updates({"tools": {"todos": todos, "messages": [result]}})

    assert list(translator.translate(started)) == []
    assert [type(e) for e in translator.translate(finished)] == [TodosUpdated]


def test_other_nodes_are_ignored() -> None:
    part = _updates({"PatchToolCallsMiddleware.before_agent": None})
    assert list(_translator().translate(part)) == []


def test_rejected_call_from_approval_node_finishes_the_tool() -> None:
    """被拒绝的调用由审批中间件直接写入结果（不经过 tools 节点）：也要结束那张工具卡片。"""
    translator = _translator()
    call = {"name": "demo_add_note", "args": {"text": "x"}, "id": "c1", "type": "tool_call"}
    ai = AIMessage(content="", tool_calls=[call])
    rejected = ToolMessage(
        content="User rejected the tool call",
        tool_call_id="c1",
        name="demo_add_note",
        status="error",
    )
    events = list(
        translator.translate(
            _updates({"HumanInTheLoopMiddleware.after_model": {"messages": [ai, rejected]}})
        )
    )
    assert events == [
        ToolFinished(
            call_id="c1", name="demo_add_note", status="error", output="User rejected the tool call"
        )
    ]


def test_other_nodes_do_not_replay_tool_results() -> None:
    """中断标记中间件会把整段历史写回存档：其中的工具结果不能再当作新事件输出。"""
    old = ToolMessage(content="旧结果", tool_call_id="c0", name="ls")
    data = {"InterruptionMarkerMiddleware.before_agent": {"messages": [old]}}
    assert list(_translator().translate(_updates(data))) == []


def test_long_command_output_keeps_exit_status_line() -> None:
    """长输出截断时留下末尾的退出码那一行（及截断说明）：界面靠它显示命令成没成功。"""
    call = {
        "name": "execute",
        "args": {"command": "pip install x"},
        "id": "c1",
        "type": "tool_call",
    }
    started = _updates({"model": {"messages": [AIMessage(content="", tool_calls=[call])]}})
    tail = "\n[Command failed with exit code 1]\n[Output was truncated due to size limits]"
    result_message = ToolMessage(content="x" * 5000 + tail, tool_call_id="c1", name="execute")
    finished = _updates({"tools": {"messages": [result_message]}})
    translator = _translator()
    list(translator.translate(started))

    [result] = list(translator.translate(finished))
    assert isinstance(result, ToolFinished)
    assert len(result.output) <= TOOL_OUTPUT_LIMIT
    assert result.output.startswith("x" * 100)
    assert result.output.endswith(tail)


# ---- 思考的真实起止（设计 2026-10-23 4.8） ----


def _thinking(text: str, message_id: str = "m1") -> MessagesStreamPart:
    return _messages(
        AIMessageChunk(content="", id=message_id, additional_kwargs={"reasoning_content": text})
    )


def test_thinking_start_and_finish_wrap_the_thinking() -> None:
    translator = _translator()
    events = [
        e
        for part in (
            _thinking("先"),
            _thinking("想"),
            _messages(AIMessageChunk(content="好", id="m1")),
        )
        for e in translator.translate(part)
    ]
    assert events == [
        ThinkingStarted(message_id="m1"),
        ThinkingDelta(message_id="m1", text="先"),
        ThinkingDelta(message_id="m1", text="想"),
        ThinkingFinished(message_id="m1"),
        MessageDelta(message_id="m1", text="好"),
    ]


def test_tool_call_finishes_thinking() -> None:
    translator = _translator()
    list(translator.translate(_thinking("先")))
    call = AIMessageChunk(
        content="",
        id="m1",
        tool_call_chunks=[{"name": "ls", "args": "", "id": "c1", "index": 0}],
    )
    assert list(translator.translate(_messages(call))) == [ThinkingFinished(message_id="m1")]


def test_model_update_finishes_thinking_without_text() -> None:
    """只想了、没说话（直接调工具或空回答）：这次调用结束时推结束。"""
    translator = _translator()
    list(translator.translate(_thinking("先")))
    events = list(translator.translate(_updates({"model": {"messages": [AIMessage("")]}})))
    assert events == [ThinkingFinished(message_id="m1")]
    assert list(translator.translate(_messages(AIMessageChunk(content="好", id="m1")))) == [
        MessageDelta(message_id="m1", text="好")
    ]


def test_no_thinking_events_without_thinking() -> None:
    translator = _translator()
    events = [
        *translator.translate(_messages(AIMessageChunk(content="好", id="m1"))),
        *translator.translate(_updates({"model": {"messages": [AIMessage("好")]}})),
    ]
    assert events == [MessageDelta(message_id="m1", text="好")]


def test_execute_result_carries_exit_code_and_stderr() -> None:
    """执行命令的真实退出码与错误输出交给界面（设计 2026-10-23 5.4），在工具结果的附加信息里。"""
    message = ToolMessage(
        content="x\n[Command failed with exit code 2]",
        name="execute",
        tool_call_id="c1",
        artifact={"exit_code": 2, "stderr": "boom", "timed_out": False},
    )
    [finished] = list(_translator().translate(_updates({"tools": {"messages": [message]}})))
    assert isinstance(finished, ToolFinished)
    assert (finished.exit_code, finished.stderr) == (2, "boom")


def test_long_stderr_keeps_its_end() -> None:
    """错误输出太长时留结尾：报错栈最后一行才是真正的错误（审查 Minor 1）。"""
    stderr = "Traceback\n" + "  frame\n" * 1000 + "ValueError: 真正的错误"
    message = ToolMessage(
        content="[Command failed with exit code 1]",
        name="execute",
        tool_call_id="c1",
        artifact={"exit_code": 1, "stderr": stderr, "timed_out": False},
    )
    [finished] = list(_translator().translate(_updates({"tools": {"messages": [message]}})))
    assert isinstance(finished, ToolFinished)
    assert finished.stderr.endswith("ValueError: 真正的错误")
    assert len(finished.stderr) <= TOOL_OUTPUT_LIMIT


def test_other_tools_have_no_exit_code() -> None:
    message = ToolMessage(content="ok", name="read_file", tool_call_id="c1")
    [finished] = list(_translator().translate(_updates({"tools": {"messages": [message]}})))
    assert isinstance(finished, ToolFinished)
    assert (finished.exit_code, finished.stderr) == (None, "")


def test_custom_tool_running_becomes_event() -> None:
    translator = _translator()
    part = _custom({"type": "tool.running", "call_id": "c1", "name": "read_file", "skill": "excel"})
    assert list(translator.translate(part)) == [
        ToolRunning(call_id="c1", name="read_file", skill="excel")
    ]
    # 别的自定义片段不认
    assert list(translator.translate(_custom({"type": "其他", "call_id": "c1"}))) == []
    assert list(translator.translate(_custom("随便写的"))) == []


async def test_tool_running_inside_subagent_has_its_path() -> None:
    tracker = RunTracker()
    await tracker.on_tool_start(
        {},
        "",
        run_id=uuid4(),
        metadata={"langgraph_checkpoint_ns": "tools:ns-a"},
        tool_call_id="c1",
    )
    part = _custom({"type": "tool.running", "call_id": "c2", "name": "ls"}, ns=("tools:ns-a",))
    assert list(Translator(tracker).translate(part)) == [
        ToolRunning(agent_path=["main", "c1"], call_id="c2", name="ls")
    ]
