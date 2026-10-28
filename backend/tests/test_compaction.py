from agents.main_agent.runtime import (
    MessageDelta,
    RunFinished,
    ThinkingDelta,
    ToolStarted,
    UsageReported,
)
from backend.runs.compaction import compact
from backend.runtime import EventEnvelope


def _wrap(
    seq: int, event: MessageDelta | ThinkingDelta | ToolStarted | RunFinished | UsageReported
) -> EventEnvelope:
    return EventEnvelope.wrap(event, seq=seq, run_id="r1")


def test_adjacent_deltas_merge_into_full_text_with_last_seq() -> None:
    events = [
        _wrap(1, MessageDelta(message_id="m1", text="你")),
        _wrap(2, MessageDelta(message_id="m1", text="好")),
        _wrap(3, ToolStarted(call_id="c1", name="ls", args={})),
        _wrap(4, MessageDelta(message_id="m2", text="完")),
        _wrap(5, RunFinished(status="completed")),
    ]
    result = compact(events)
    # 合并后取该组最后一个序号：客户端只要没收到这组的最后一个片段，续传时就会拿到整条全文
    assert [(e.seq, e.type) for e in result] == [
        (2, "message.delta"),
        (3, "tool.started"),
        (4, "message.delta"),
        (5, "run.finished"),
    ]
    assert result[0].data == {"message_id": "m1", "text": "你好", "full_text": True}
    assert result[2].data == {"message_id": "m2", "text": "完", "full_text": True}


def test_thinking_merges_separately_and_subagent_text_is_not_mixed_in() -> None:
    events = [
        _wrap(1, ThinkingDelta(message_id="m1", text="想")),
        _wrap(2, ThinkingDelta(message_id="m1", text="想")),
        _wrap(3, MessageDelta(message_id="m1", text="答")),
        _wrap(4, MessageDelta(message_id="m1", text="案")),
        _wrap(5, MessageDelta(agent_path=["main", "c1"], message_id="m1", text="子")),
    ]
    result = compact(events)
    assert [(e.seq, e.type, e.data["text"]) for e in result] == [
        (2, "thinking.delta", "想想"),
        (4, "message.delta", "答案"),
        (5, "message.delta", "子"),
    ]


def test_parallel_subagents_each_keep_their_full_text() -> None:
    """两个子智能体同时输出时片段交错：各自合并成全文，不能被对方切成几段（否则重放时只剩最后一段）。"""
    a, b = ["main", "ca"], ["main", "cb"]
    events = [
        _wrap(1, MessageDelta(agent_path=a, message_id="ma", text="子")),
        _wrap(2, MessageDelta(agent_path=b, message_id="mb", text="孙")),
        _wrap(3, MessageDelta(agent_path=a, message_id="ma", text="一")),
        _wrap(4, MessageDelta(agent_path=b, message_id="mb", text="二")),
    ]
    result = compact(events)
    assert [(e.seq, e.agent_path, e.data["text"]) for e in result] == [
        (3, a, "子一"),
        (4, b, "孙二"),
    ]


def test_text_split_by_another_event_carries_everything_so_far() -> None:
    """同一段回答中间夹了别的事件（如用量）：后一组的 full_text 仍是到此为止的全文。"""
    usage = UsageReported(
        caller="main", requested_model="m", actual_model="m", input_tokens=1, output_tokens=1
    )
    events = [
        _wrap(1, MessageDelta(message_id="m1", text="你")),
        _wrap(2, usage),
        _wrap(3, MessageDelta(message_id="m1", text="好")),
    ]
    result = compact(events)
    assert [(e.seq, e.type, e.data.get("text")) for e in result] == [
        (1, "message.delta", "你"),
        (2, "usage", None),
        (3, "message.delta", "你好"),
    ]
