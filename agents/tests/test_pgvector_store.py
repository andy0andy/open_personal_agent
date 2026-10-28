"""知识存储 PostgreSQL 实现的并发情形。"""

from uuid import UUID

import pytest

from agents.main_agent.knowledge import KnowledgeItem, NewKnowledge, PgKnowledgeStore
from agents.tests.fakes import FakeEmbedder
from common.db import Pool

pytestmark = pytest.mark.integration


class _DeletedMidway(PgKnowledgeStore):
    """排好名之后、取出条目之前，有一条被删了（用户在知识库页删，或提取任务删）。"""

    victim: UUID | None = None

    async def _items(self, ids: list[UUID]) -> list[KnowledgeItem]:
        if self.victim is not None:
            await self.delete(self.victim)
            self.victim = None
        return await super()._items(ids)


async def test_search_skips_items_deleted_meanwhile(db: Pool) -> None:
    store = _DeletedMidway(db, FakeEmbedder(["咖啡", "茶"]))
    coffee = await store.add(NewKnowledge(content="用户喜欢咖啡", source="manual"))
    tea = await store.add(NewKnowledge(content="用户喜欢茶", source="manual"))
    store.victim = coffee.id
    hits = await store.search("咖啡和茶")
    assert [hit.item.id for hit in hits] == [tea.id]
