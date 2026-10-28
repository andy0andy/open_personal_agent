"""常驻条目的上限（设计 2026-10-23 6.6）：常驻信息每次对话都带上，总量是硬限制。"""

from uuid import UUID

from agents.main_agent.knowledge.base import KnowledgeStore
from agents.main_agent.models import estimate_text_tokens


async def pinned_room(
    store: KnowledgeStore, limit: int, content: str, *, exclude: UUID | None = None
) -> str | None:
    """再放一条内容为 content 的常驻会超出上限时，返回拒绝的原因；放得下时返回 None。

    exclude：正在修改的那条常驻（它原来的大小不算）。
    """
    used = sum(item.token_count for item in await store.pinned() if item.id != exclude)
    tokens = estimate_text_tokens(content)
    if used + tokens <= limit:
        return None
    return (
        f"常驻信息已用 {used} / {limit} token，放不下这条（约 {tokens} token）："
        "先精简或取消别的常驻条目"
    )
