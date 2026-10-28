"""推送信封：在 agents 事件外层加上序号、运行 ID 和时间。"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agents.main_agent.runtime import Event


class EventEnvelope(BaseModel):
    """推给浏览器、存入 run_events 表的统一格式。"""

    # 导出的类型定义里 ts 标为必有：推送与历史里的信封总带着时间
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    seq: int
    run_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    type: str
    agent_path: list[str]
    data: dict[str, Any]

    @classmethod
    def wrap(
        cls, event: Event, *, seq: int, run_id: str, ts: datetime | None = None
    ) -> "EventEnvelope":
        """ts 默认为现在；补发历史事件时可指定（前端用开始 / 结束事件的时间计算耗时）。"""
        body = event.model_dump(mode="json")
        return cls(
            seq=seq,
            run_id=run_id,
            ts=ts or datetime.now(UTC),
            type=body.pop("type"),
            agent_path=body.pop("agent_path"),
            data=body,
        )
