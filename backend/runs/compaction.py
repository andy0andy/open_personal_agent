"""存入界面历史前合并同一段回答（或思考过程）的连续逐字片段，减少存储量。"""

from backend.runtime import EventEnvelope

_DELTAS = ("message.delta", "thinking.delta")

type _ContentKey = tuple[str, tuple[str, ...], str]  # (类型, agent_path, message_id)


def compact(events: list[EventEnvelope]) -> list[EventEnvelope]:
    """按智能体合并同一段内容的连续逐字片段。

    每个智能体（agent_path）单独看：并行的子智能体片段交错到达，也各自合并。
    合并后的事件带 full_text=True，text 是这段内容到此为止的全文——即使中间夹了同一智能体的
    其他事件（如用量）而分成几组，后一组也带着前面的文字；序号取该组最后一个：
    断线续传时，只要客户端还没收到这组的最后一个片段，就会收到全文并整体替换，既不丢字也不重复。
    结果按序号排列（与从数据库读回的顺序一致）。
    """
    result: list[EventEnvelope] = []
    texts: dict[_ContentKey, str] = {}
    open_groups: dict[tuple[str, ...], tuple[_ContentKey, int]] = {}  # 智能体 → 正在合并的组
    for event in events:
        path = tuple(event.agent_path)
        if event.type not in _DELTAS:
            open_groups.pop(path, None)  # 同一智能体的其他事件结束当前这组
            result.append(event)
            continue
        key: _ContentKey = (event.type, path, event.data["message_id"])
        texts[key] = texts.get(key, "") + event.data["text"]
        merged = event.model_copy(
            update={"data": {**event.data, "text": texts[key], "full_text": True}}
        )
        group = open_groups.get(path)
        if group is not None and group[0] == key:
            result[group[1]] = merged
        else:
            open_groups[path] = (key, len(result))
            result.append(merged)
    return sorted(result, key=lambda event: event.seq)
