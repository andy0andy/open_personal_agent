from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from agents.main_agent.runtime.interruption import INTERRUPTED_NOTE, mark_interruptions

CALL = {"name": "ls", "args": {}, "id": "c1", "type": "tool_call"}


def _shape(messages: list[AnyMessage] | None) -> list[tuple[str, str]] | None:
    if messages is None:
        return None
    return [(m.type, m.content if isinstance(m.content, str) else "") for m in messages]


def test_unanswered_request_gets_interruption_note() -> None:
    messages: list[AnyMessage] = [HumanMessage("写长文"), HumanMessage("一句话")]
    assert _shape(mark_interruptions(messages)) == [
        ("human", "写长文"),
        ("ai", INTERRUPTED_NOTE),
        ("human", "一句话"),
    ]


def test_turn_ending_in_tool_call_or_tool_result_gets_note() -> None:
    dangling: list[AnyMessage] = [
        HumanMessage("一"),
        AIMessage("", tool_calls=[CALL]),
        HumanMessage("二"),
    ]
    assert _shape(mark_interruptions(dangling)) == [
        ("human", "一"),
        ("ai", ""),
        ("ai", INTERRUPTED_NOTE),
        ("human", "二"),
    ]
    after_tool: list[AnyMessage] = [
        HumanMessage("一"),
        AIMessage("", tool_calls=[CALL]),
        ToolMessage("结果", tool_call_id="c1"),
        HumanMessage("二"),
    ]
    shape = _shape(mark_interruptions(after_tool))
    assert shape is not None
    assert shape[-2:] == [("ai", INTERRUPTED_NOTE), ("human", "二")]


def test_finished_turns_and_compaction_summary_are_left_alone() -> None:
    finished: list[AnyMessage] = [HumanMessage("一"), AIMessage("答"), HumanMessage("二")]
    assert mark_interruptions(finished) is None
    summary = HumanMessage("此前对话的摘要", additional_kwargs={"lc_source": "summarization"})
    compacted: list[AnyMessage] = [summary, HumanMessage("接着问")]
    assert mark_interruptions(compacted) is None
