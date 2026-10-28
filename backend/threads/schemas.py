"""会话的数据结构。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from agents.main_agent.runtime import PermissionMode

# 会话列表的状态点（设计 2026-10-22 第 5 节）：最近一次运行在排队或运行中、在等审批、失败了
# new：顺利结束、之后还没看过（设计 2026-10-23 6.5）
ThreadActivity = Literal["running", "waiting", "failed", "new"]


class Thread(BaseModel):
    id: UUID
    short_id: str
    title: str
    model: str
    permission_mode: PermissionMode  # 会话的审批权限（D23），新会话为 ask
    archived: bool = False  # 归档的会话不在主列表里，能打开、能被搜到（设计 2026-10-23 6.5）
    created_at: datetime
    updated_at: datetime
    activity: ThreadActivity | None = None  # 只有会话列表接口会算，其余接口为空


class ThreadCreate(BaseModel):
    """新建会话；带上第一条消息时一次完成：设好模型和权限、发起运行（设计 2026-10-23 6.4）。"""

    title: str = ""
    model: str | None = None
    permission_mode: PermissionMode | None = None
    # 同运行的 UserMessage（这里不能导入 backend.runs：它的包会反过来导入会话模块）
    message: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000)]
        | None
    ) = None


class ThreadUpdate(BaseModel):
    """改会话的标题、模型或审批权限（会话设置都在会话上，设计 2026-10-19 4.1、4.2）。"""

    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None
    model: Annotated[str, StringConstraints(min_length=1)] | None = None
    permission_mode: PermissionMode | None = None
    archived: bool | None = None  # 归档、取消归档（设计 2026-10-23 6.5）

    @model_validator(mode="after")
    def _something_to_change(self) -> "ThreadUpdate":
        if (
            self.title is None
            and self.model is None
            and self.permission_mode is None
            and self.archived is None
        ):
            raise ValueError("至少要改一项：title、model、permission_mode 或 archived")
        return self


class ThreadOrder(BaseModel):
    """左侧会话的自定义顺序：从上到下的会话 ID。"""

    thread_ids: Annotated[list[UUID], Field(min_length=1)]

    @field_validator("thread_ids")
    @classmethod
    def _no_repeats(cls, thread_ids: list[UUID]) -> list[UUID]:
        if len(set(thread_ids)) != len(thread_ids):
            raise ValueError("会话 ID 重复")
        return thread_ids


class ConversationHitView(BaseModel):
    """会话内容里提到：哪个会话的第几轮，命中词前后的一小段原文（设计 2026-10-23 6.1）。"""

    thread_id: UUID
    title: str
    run_id: UUID
    turn: int
    snippet: str
    terms: list[str]  # 命中用的词：界面据此加粗（积压小问题 B4）


class ThreadSearchResult(BaseModel):
    titles: list[Thread]  # 标题匹配（含已归档的）
    hits: list[ConversationHitView]  # 内容里提到
