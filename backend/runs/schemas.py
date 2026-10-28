"""运行的数据结构。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

from agents.main_agent.runtime import ApprovalAnswer, PermissionMode
from backend.runtime import EventEnvelope
from backend.threads.schemas import Thread

UserMessage = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000)
]


# 与 runs 表的 CHECK 约束一致（0001 迁移）
type RunStatus = Literal["queued", "running", "interrupted", "completed", "failed", "cancelled"]


class RunCreate(BaseModel):
    message: UserMessage
    # 这条消息附带的文件：已上传到本会话的文件 ID（POST /threads/{id}/files 的返回）
    attachments: list[UUID] = Field(default=[], max_length=10)

    @field_validator("attachments")
    @classmethod
    def _once_each(cls, value: list[UUID]) -> list[UUID]:
        """同一个附件只算一次、顺序不变（积压小问题 D7：原来路径列两遍、图片附两份）。"""
        return list(dict.fromkeys(value))


class RunInterject(BaseModel):
    """运行中插话（POST /runs/{id}/interject，设计 2026-10-23 6.3）。"""

    message: UserMessage


class ResumeRequest(BaseModel):
    """审批决定（POST /runs/{id}/resume）：每处暂停一个答复。"""

    answers: list[ApprovalAnswer] = Field(min_length=1, max_length=10)


class RunAttachment(BaseModel):
    """随消息附带的文件。运行记录里存一份，界面历史据此在用户消息下显示。"""

    id: UUID
    path: str  # 相对会话目录，如 uploads/a.xlsx
    media_type: str
    size: int


class RunRecord(BaseModel):
    id: UUID
    thread_id: UUID
    status: RunStatus
    model: str
    # 运行开始时定下的审批权限，整次运行（含审批后继续）都用它（D23）；旧运行没有记，按 ask
    permission: PermissionMode = "ask"
    message: str
    attachments: list[RunAttachment]
    error: str | None
    created_at: datetime
    # "重试这一轮"发起的运行：重试的是哪一次（D26）；界面据此把那一轮收成一行
    retry_of: UUID | None = None


class RunHistory(RunRecord):
    events: list[EventEnvelope]


class ThreadCreated(Thread):
    """新建的会话；带了第一条消息时还有发起的那次运行（设计 2026-10-23 6.4）。"""

    run: RunRecord | None = None
