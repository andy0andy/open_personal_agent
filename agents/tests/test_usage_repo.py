import uuid
from datetime import UTC, date, datetime
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from agents.main_agent.runtime import UsageReported, UsageTotals
from agents.main_agent.usage import ModelUsage, UsageRepo
from common.db import Pool
from common.errors import InvalidRequestError

pytestmark = pytest.mark.integration


def _usage(model: str, tokens: int, caller: str = "main") -> UsageReported:
    return UsageReported(
        caller=caller,
        requested_model=model,
        actual_model=model,
        input_tokens=tokens,
        output_tokens=tokens // 10,
        cache_read_tokens=tokens // 2,
        duration_ms=5,
    )


async def test_run_details_in_call_order(db: Pool) -> None:
    repo = UsageRepo(db)
    thread_id, run_id = uuid.uuid4(), uuid.uuid4()
    await repo.add(thread_id=thread_id, run_id=run_id, usage=_usage("a", 100))
    await repo.add(thread_id=thread_id, run_id=run_id, usage=_usage("a", 10, "子助手"))

    records = await repo.for_run(run_id)
    # 每次调用的明细仍记缓存读写（汇总不单列）
    assert [(r.caller, r.input_tokens, r.cache_read_tokens) for r in records] == [
        ("main", 100, 50),
        ("子助手", 10, 5),
    ]


async def test_thread_usage_is_split_by_model(db: Pool) -> None:
    repo = UsageRepo(db)
    thread_id = uuid.uuid4()
    await repo.add(thread_id=thread_id, run_id=uuid.uuid4(), usage=_usage("a", 100))
    await repo.add(thread_id=thread_id, run_id=uuid.uuid4(), usage=_usage("a", 100))
    await repo.add(thread_id=thread_id, run_id=uuid.uuid4(), usage=_usage("b", 10))
    await repo.add(thread_id=uuid.uuid4(), run_id=uuid.uuid4(), usage=_usage("a", 999))

    usage = await repo.for_thread(thread_id)
    assert usage.by_model == [
        ModelUsage(model="a", calls=2, input_tokens=200, output_tokens=20),
        ModelUsage(model="b", calls=1, input_tokens=10, output_tokens=1),
    ]
    assert usage.total == UsageTotals(calls=3, input_tokens=210, output_tokens=21)


async def test_empty_thread_has_zero_usage(db: Pool) -> None:
    usage = await UsageRepo(db).for_thread(uuid.uuid4())
    assert usage.total == UsageTotals()
    assert usage.by_model == []


async def test_usage_without_thread_or_run_is_recorded(db: Pool) -> None:
    """文档入库时的向量化不属于任何会话：照样记下，不影响会话的用量。"""
    repo = UsageRepo(db)
    thread = uuid.uuid4()
    await repo.add(thread_id=None, run_id=None, usage=_usage("embed", 4, caller="embedding"))
    await repo.add(thread_id=thread, run_id=uuid.uuid4(), usage=_usage("m", 10))
    assert (await repo.for_thread(thread)).total.calls == 1
    async with db.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM llm_usage WHERE caller = 'embedding'")
        row = await cur.fetchone()
    assert row is not None
    assert row["n"] == 1


SHANGHAI = ZoneInfo("Asia/Shanghai")
TODAY = date(2026, 10, 16)


async def _at(
    db: Pool,
    when: str,
    *,
    model: str = "m",
    tokens: int = 100,
    caller: str = "main",
    thread_id: uuid.UUID | None = None,
) -> None:
    """直接写一条带时间的用量（汇总按时间分组）。"""
    async with db.connection() as conn:
        await conn.execute(
            "INSERT INTO llm_usage (id, thread_id, run_id, caller, requested_model, actual_model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, created_at) "
            "VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, 7, 3, %s)",
            (uuid.uuid4(), thread_id, caller, model, model, tokens, tokens // 10, when),
        )


async def test_summary_groups_days_in_the_given_timezone(db: Pool) -> None:
    """北京时间 10-16 00:30（UTC 10-15 16:30）算在北京时间的 10-16。"""
    await _at(db, "2026-10-15T16:30:00Z")
    await _at(db, "2026-10-16T03:00:00Z")
    summary = await UsageRepo(db).summary(days=7, tz=SHANGHAI, today=TODAY)
    assert [(d.day, d.calls) for d in summary.by_day] == [(TODAY, 2)]
    assert (summary.since, summary.until) == (date(2026, 10, 10), TODAY)
    assert (summary.total.calls, summary.total.input_tokens) == (2, 200)


async def test_summary_splits_by_model_caller_and_thread(db: Pool) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    await _at(db, "2026-10-16T01:00:00Z", model="big", tokens=300, thread_id=a)
    await _at(db, "2026-10-16T01:01:00Z", model="small", tokens=200, caller="title", thread_id=b)
    await _at(db, "2026-10-16T01:02:00Z", model="embed", tokens=100, caller="embedding")
    summary = await UsageRepo(db).summary(days=1, tz=SHANGHAI, today=TODAY)
    assert [m.model for m in summary.by_model] == ["big", "small", "embed"]
    assert [c.caller for c in summary.by_caller] == ["main", "title", "embedding"]
    assert [t.thread_id for t in summary.by_thread] == [a, b]  # 向量化不属于会话


async def test_summary_orders_by_tokens(db: Pool) -> None:
    """只算 token（设计 2026-10-19 4.11）：按输入加输出从多到少排。"""
    a, b = uuid.uuid4(), uuid.uuid4()
    await _at(db, "2026-10-16T01:00:00Z", model="pricey", tokens=10, thread_id=a)
    await _at(db, "2026-10-16T01:01:00Z", model="free", tokens=1000, thread_id=b)
    summary = await UsageRepo(db).summary(days=1, tz=SHANGHAI, today=TODAY)
    assert [m.model for m in summary.by_model] == ["free", "pricey"]
    assert [t.thread_id for t in summary.by_thread] == [b, a]


async def test_summary_ignores_calls_outside_the_range(db: Pool) -> None:
    await _at(db, "2026-10-08T03:00:00Z")  # 北京时间 10-08，超出最近 7 天
    await _at(db, "2026-10-10T03:00:00Z")
    summary = await UsageRepo(db).summary(days=7, tz=SHANGHAI, today=TODAY)
    assert summary.total.calls == 1


async def test_day_and_range_edges_follow_the_timezone(db: Pool) -> None:
    """跨天与范围的边界按所给时区算（积压小问题 I6）：差一秒落在不同的天，范围起点也一样。"""
    for when in (
        "2026-10-09T15:59:59Z",  # 北京时间 10-09 23:59:59：不在最近 7 天里
        "2026-10-09T16:00:00Z",  # 北京时间 10-10 00:00：范围的第一秒
        "2026-10-15T15:59:59Z",  # 北京时间 10-15 的最后一秒
        "2026-10-15T16:00:00Z",  # 北京时间 10-16 的第一秒
    ):
        await _at(db, when)
    summary = await UsageRepo(db).summary(days=7, tz=SHANGHAI, today=TODAY)
    assert [(d.day, d.calls) for d in summary.by_day] == [
        (date(2026, 10, 10), 1),
        (date(2026, 10, 15), 1),
        (TODAY, 1),
    ]
    assert summary.total.calls == 3


class _ZoneOnlyPythonKnows:
    """Python 认识、PostgreSQL 不认识的时区（两边的时区库版本不保证一致）。"""

    key = "Mars/Base"


async def test_timezone_postgres_does_not_know_is_refused(db: Pool) -> None:
    """PostgreSQL 不认识的时区：说"时区不认识"（422），不是 500（积压小问题 G1）。"""
    zone = cast(ZoneInfo, _ZoneOnlyPythonKnows())
    with pytest.raises(InvalidRequestError, match="时区不认识：Mars/Base"):
        await UsageRepo(db).summary(days=1, tz=zone, today=TODAY)


# 工具与技能用量（设计 2026-10-23 6.8）
async def _tool_at(db: Pool, when: str, tool: str, skill: str | None = None) -> None:
    async with db.connection() as conn:
        await conn.execute(
            "INSERT INTO tool_usage (thread_id, run_id, tool, skill, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (uuid.uuid4(), uuid.uuid4(), tool, skill, when),
        )


async def test_tool_uses_are_recorded_and_summed_by_name(db: Pool) -> None:
    repo = UsageRepo(db)
    thread_id, run_id = uuid.uuid4(), uuid.uuid4()
    await repo.add_tool_use(thread_id=thread_id, run_id=run_id, tool="read_file", skill="excel")
    await repo.add_tool_use(thread_id=thread_id, run_id=run_id, tool="execute", skill=None)
    await repo.add_tool_use(thread_id=thread_id, run_id=run_id, tool="read_file", skill=None)
    summary = await repo.summary(days=1, tz=SHANGHAI)
    assert [(t.name, t.count) for t in summary.by_tool] == [("read_file", 2), ("execute", 1)]
    assert [(s.name, s.count) for s in summary.by_skill] == [("excel", 1)]


async def test_tool_summary_follows_the_range(db: Pool) -> None:
    await _tool_at(db, "2026-10-08T03:00:00Z", "ls")  # 北京时间 10-08，超出最近 7 天
    await _tool_at(db, "2026-10-15T16:30:00Z", "grep", "excel")  # 北京时间 10-16
    summary = await UsageRepo(db).summary(days=7, tz=SHANGHAI, today=TODAY)
    assert [(t.name, t.count) for t in summary.by_tool] == [("grep", 1)]
    assert [(s.name, s.count) for s in summary.by_skill] == [("excel", 1)]


async def test_skill_last_used(db: Pool) -> None:
    """技能页的最近使用时间（设计 2026-10-23 7.7）：每个技能取最近一次读说明的时间。"""
    await _tool_at(db, "2026-10-15T16:30:00Z", "read_file", "excel")
    await _tool_at(db, "2026-10-20T01:00:00Z", "read_file", "excel")
    await _tool_at(db, "2026-10-18T08:00:00Z", "read_file", "周报写作")
    await _tool_at(db, "2026-10-21T08:00:00Z", "execute")
    assert await UsageRepo(db).skill_last_used() == {
        "excel": datetime(2026, 10, 20, 1, 0, tzinfo=UTC),
        "周报写作": datetime(2026, 10, 18, 8, 0, tzinfo=UTC),
    }
