import uuid

import pytest

from agents.main_agent.workspace import WorkspaceFileRepo, workspace_file_id
from common.db import Pool
from common.errors import NotFoundError


def test_file_id_is_fixed_by_thread_and_path() -> None:
    """同一会话同一路径的文件始终是同一个 ID：推送产物事件时不必先查数据库就有下载地址。"""
    thread = uuid.uuid4()
    assert workspace_file_id(thread, "outputs/a.png") == workspace_file_id(thread, "outputs/a.png")
    assert workspace_file_id(thread, "outputs/a.png") != workspace_file_id(thread, "outputs/b.png")
    assert workspace_file_id(thread, "outputs/a.png") != workspace_file_id(
        uuid.uuid4(), "outputs/a.png"
    )


@pytest.mark.integration
async def test_records_updates_lists_and_deletes(db: Pool) -> None:
    repo = WorkspaceFileRepo(db)
    thread = uuid.uuid4()
    first = await repo.record(
        thread, "outputs/a.png", source="output", size=3, media_type="image/png"
    )
    again = await repo.record(
        thread, "outputs/a.png", source="output", size=5, media_type="image/png"
    )
    await repo.record(thread, "outputs/b.csv", source="output", size=1, media_type="text/csv")

    assert first.id == again.id == workspace_file_id(thread, "outputs/a.png")
    stored = await repo.get(first.id)
    assert (stored.thread_id, stored.size, stored.source) == (thread, 5, "output")
    assert stored.updated_at >= stored.created_at
    assert [f.path for f in await repo.for_thread(thread)] == ["outputs/a.png", "outputs/b.csv"]

    await repo.delete_for_thread(thread)
    assert await repo.for_thread(thread) == []
    with pytest.raises(NotFoundError):
        await repo.get(first.id)
