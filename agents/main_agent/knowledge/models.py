"""知识条目（设计文档 8.1、11.1）：记忆、文档片段等都是带标记的知识条目。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

type KnowledgeKind = Literal["memory", "document_chunk"]
type KnowledgeSource = Literal["conversation", "document", "manual"]

KnowledgeText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]


def clean_tags(tags: list[str]) -> list[str]:
    """去掉首尾空白与空标签，去重并保持顺序。"""
    seen: dict[str, None] = {}
    for tag in tags:
        if tag.strip():
            seen[tag.strip()] = None
    return list(seen)


class NewKnowledge(BaseModel):
    kind: KnowledgeKind = "memory"
    content: KnowledgeText
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False  # 常驻：每次都拼进系统提示词（个人画像）
    source: KnowledgeSource
    source_thread_id: UUID | None = None
    source_run_id: UUID | None = None

    @field_validator("tags")
    @classmethod
    def _clean(cls, tags: list[str]) -> list[str]:
        return clean_tags(tags)


class KnowledgeItem(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: UUID
    kind: KnowledgeKind
    tags: list[str]
    pinned: bool
    content: str
    source: KnowledgeSource
    source_thread_id: UUID | None
    source_run_id: UUID | None
    document_id: UUID | None  # 文档片段所属文档
    seq: int | None  # 文档片段在文档里的顺序
    section_path: str | None  # 文档片段所在章节，如"第一章 考勤 › 1.1 请假"
    page: int | None  # 文档片段所在页（PDF 的页、PPT 的幻灯片）
    document_title: str | None  # 文档片段所属文档的标题（出处里显示）
    token_count: int
    embedding_model: str
    created_at: datetime
    updated_at: datetime
    # 可疑检查（设计 2026-10-23 6.6）：命中的那一类；trusted 为你确认过无害
    suspicious: str | None = None
    trusted: bool = False

    @property
    def flagged(self) -> bool:
        """可疑且还没确认无害：不进提示词，也不出现在检索结果里。"""
        return self.suspicious is not None and not self.trusted


class KnowledgeHit(BaseModel):
    """检索结果：条目与得分（混合检索为融合得分，召回为相似度）。"""

    item: KnowledgeItem
    score: float
