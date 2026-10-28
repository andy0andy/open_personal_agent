"""知识存储接口（设计文档 4.1"知识检索"）：知识条目的增删改查与检索。

v1 实现是 PostgreSQL（pgvector 存向量 + jieba 分词做中文关键词检索）；以后可换 Qdrant 等。
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from agents.main_agent.knowledge.chunking import Chunk
from agents.main_agent.knowledge.models import (
    KnowledgeHit,
    KnowledgeItem,
    KnowledgeKind,
    NewKnowledge,
)


class KnowledgeStore(Protocol):
    async def add(self, new: NewKnowledge) -> KnowledgeItem:
        """写入一条；记忆过一遍可疑检查（设计 2026-10-23 6.6）。"""
        ...

    async def add_chunks(
        self, document_id: UUID, title: str, chunks: Sequence[Chunk]
    ) -> list[KnowledgeItem]:
        """写入一份文档的若干片段（一次向量化请求）；文档不存在（已被删）抛 NotFoundError。"""
        ...

    async def delete_chunks(self, document_id: UUID) -> int:
        """删除一份文档的全部片段，返回删除条数。"""
        ...

    async def around(self, item_id: UUID, window: int) -> list[KnowledgeItem]:
        """文档片段及其前后各 window 段（按顺序）；记忆只返回它自己；不存在抛 NotFoundError。"""
        ...

    async def get(self, item_id: UUID) -> KnowledgeItem:
        """不存在时抛 NotFoundError。"""
        ...

    async def update(
        self,
        item_id: UUID,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
        trusted: bool | None = None,
    ) -> KnowledgeItem:
        """只改给出的字段；改内容时重新向量化。不存在时抛 NotFoundError。

        记忆改了内容时重新做可疑检查，之前的"确认无害"作废（设计 2026-10-23 6.6）。
        """
        ...

    async def delete(self, item_id: UUID) -> None:
        """不存在时抛 NotFoundError。"""
        ...

    async def list_items(
        self,
        *,
        kind: KnowledgeKind | None = None,
        tags: Sequence[str] = (),
        pinned: bool | None = None,
        flagged: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        """按创建时间从新到旧；tags 表示必须带有这些标签；flagged 为真只列可疑且没确认的
        （知识库页的"可疑"视图），为假只列其余的。"""
        ...

    async def pinned(self) -> list[KnowledgeItem]:
        """全部常驻条目（按创建时间先后）。"""
        ...

    async def find_memories(self, fragment: str, *, limit: int = 6) -> list[KnowledgeItem]:
        """内容里含有这段原文的记忆（不分大小写，不含文档片段），按创建时间先后，最多 limit 条。
        更正、忘掉记忆时按它定位（设计 2026-10-23 6.6）。"""
        ...

    async def search(
        self,
        query: str,
        *,
        kinds: Sequence[KnowledgeKind] | None = None,
        tags: Sequence[str] = (),
        top_k: int = 5,
        include_suspicious: bool = False,
    ) -> list[KnowledgeHit]:
        """混合检索：按意思（向量）与按精确词（关键词）两路结果合并排序。

        可疑且未确认的记忆不在结果里；include_suspicious 为真时也找（知识库页的检索）。
        """
        ...

    async def recall(self, query: str, *, top_k: int, min_similarity: float) -> list[KnowledgeHit]:
        """相关记忆召回：只看非常驻的记忆（常驻条目每次都会带上），按意思相似度从高到低，
        低于 min_similarity 的不要；可疑且未确认的不要。"""
        ...
