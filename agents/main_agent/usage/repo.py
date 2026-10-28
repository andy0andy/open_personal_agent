"""llm_usage（模型用量）与 tool_usage（工具与技能用量，设计 2026-10-23 6.8）的数据访问。"""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg

from agents.main_agent.runtime import UsageReported, UsageTotals
from agents.main_agent.usage.schemas import (
    CallerUsage,
    DayUsage,
    ModelUsage,
    ModelUsageSummary,
    NamedCount,
    ThreadUsage,
    ThreadUsageSummary,
    UsageBucket,
    UsageRecord,
    UsageSummary,
)
from common.db import Pool
from common.errors import InvalidRequestError
from common.ids import new_id

_RECORD_COLUMNS = (
    "caller, requested_model, actual_model, input_tokens, output_tokens, cache_read_tokens, "
    "cache_write_tokens, reasoning_tokens, duration_ms"
)


# 汇总的各列：只有调用次数、输入、输出（设计 2026-10-19 4.11）
_BUCKET = (
    "count(*) AS calls, coalesce(sum(input_tokens), 0) AS input_tokens, "
    "coalesce(sum(output_tokens), 0) AS output_tokens"
)
# 按 token 从多到少：用量只算 token（设计 2026-10-19 4.11）
_ORDER = "ORDER BY sum(input_tokens + output_tokens) DESC"
# 范围按用户所在时区的日期：起始日 0 点到结束日次日 0 点（时区名作参数，不拼进 SQL）
_SCOPE = (
    "FROM llm_usage WHERE created_at >= (%(since)s::date)::timestamp AT TIME ZONE %(tz)s "
    "AND created_at < ((%(until)s::date + 1)::timestamp AT TIME ZONE %(tz)s)"
)
_TOP_THREADS = 10
# 工具用量同样按用户所在时区的日期算范围
_TOOL_SCOPE = _SCOPE.replace("FROM llm_usage", "FROM tool_usage")


class UsageRepo:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def add(
        self, *, thread_id: UUID | None, run_id: UUID | None, usage: UsageReported
    ) -> None:
        """记下一次模型调用；不属于会话的调用（如文档入库时的向量化）两个 ID 为空。"""
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO llm_usage (id, thread_id, run_id, {_RECORD_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    new_id(),
                    thread_id,
                    run_id,
                    usage.caller,
                    usage.requested_model,
                    usage.actual_model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_write_tokens,
                    usage.reasoning_tokens,
                    usage.duration_ms,
                ),
            )

    async def add_tool_use(
        self, *, thread_id: UUID, run_id: UUID, tool: str, skill: str | None
    ) -> None:
        """记下一次工具真正执行；读技能说明时 skill 是技能名（设计 2026-10-23 6.8）。"""
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO tool_usage (thread_id, run_id, tool, skill) VALUES (%s, %s, %s, %s)",
                (thread_id, run_id, tool, skill),
            )

    async def skill_last_used(self) -> dict[str, datetime]:
        """每个技能最近一次被读说明的时间（技能页用，设计 2026-10-23 7.7）；没用过的不在里面。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT skill, max(created_at) AS last_used FROM tool_usage "
                "WHERE skill IS NOT NULL GROUP BY skill"
            )
            rows = await cur.fetchall()
        return {row["skill"]: row["last_used"] for row in rows}

    async def for_run(self, run_id: UUID) -> list[UsageRecord]:
        """一次运行里每次模型调用的明细，按时间顺序。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_RECORD_COLUMNS}, created_at FROM llm_usage "
                "WHERE run_id = %s ORDER BY created_at",
                (run_id,),
            )
            rows = await cur.fetchall()
        return [UsageRecord.model_validate(row) for row in rows]

    async def for_thread(self, thread_id: UUID) -> ThreadUsage:
        """一个会话的累计用量，按实际模型版本拆分（用量大的在前）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT actual_model AS model, count(*) AS calls, "
                "sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens "
                "FROM llm_usage WHERE thread_id = %s "
                "GROUP BY actual_model ORDER BY sum(input_tokens + output_tokens) DESC",
                (thread_id,),
            )
            rows = await cur.fetchall()
        by_model = [ModelUsage.model_validate(row) for row in rows]
        total = UsageTotals(
            calls=sum(m.calls for m in by_model),
            input_tokens=sum(m.input_tokens for m in by_model),
            output_tokens=sum(m.output_tokens for m in by_model),
        )
        return ThreadUsage(total=total, by_model=by_model)

    async def summary(self, *, days: int, tz: ZoneInfo, today: date | None = None) -> UsageSummary:
        """最近 days 天（含今天，按 tz 时区的日期）的用量汇总。today 只供测试固定日期。"""
        until = today or datetime.now(tz).date()
        since = until - timedelta(days=days - 1)
        params = {"since": since, "until": until, "tz": tz.key}
        async with self._pool.connection() as conn:

            async def rows(sql: str) -> list[dict[str, Any]]:
                try:
                    cur = await conn.execute(sql, params)
                except psycopg.errors.InvalidParameterValue as exc:
                    # Python 认识、PostgreSQL 不认识的时区：两边的时区库版本不保证一致（G1）
                    raise InvalidRequestError(f"时区不认识：{tz.key}") from exc
                return list(await cur.fetchall())

            total = await rows(f"SELECT {_BUCKET} {_SCOPE}")
            by_day = await rows(
                f"SELECT (created_at AT TIME ZONE %(tz)s)::date AS day, {_BUCKET} {_SCOPE} "
                "GROUP BY 1 ORDER BY 1"
            )
            by_model = await rows(
                f"SELECT actual_model AS model, {_BUCKET} {_SCOPE} GROUP BY actual_model {_ORDER}"
            )
            by_caller = await rows(f"SELECT caller, {_BUCKET} {_SCOPE} GROUP BY caller {_ORDER}")
            by_thread = await rows(
                f"SELECT thread_id, {_BUCKET} {_SCOPE} AND thread_id IS NOT NULL "
                f"GROUP BY thread_id {_ORDER} LIMIT {_TOP_THREADS}"
            )
            by_tool = await rows(
                f"SELECT tool AS name, count(*) AS count {_TOOL_SCOPE} "
                "GROUP BY tool ORDER BY count(*) DESC, tool"
            )
            by_skill = await rows(
                f"SELECT skill AS name, count(*) AS count {_TOOL_SCOPE} AND skill IS NOT NULL "
                "GROUP BY skill ORDER BY count(*) DESC, skill"
            )
        return UsageSummary(
            since=since,
            until=until,
            total=UsageBucket.model_validate(total[0]),
            by_day=[DayUsage.model_validate(row) for row in by_day],
            by_model=[ModelUsageSummary.model_validate(row) for row in by_model],
            by_caller=[CallerUsage.model_validate(row) for row in by_caller],
            by_thread=[ThreadUsageSummary.model_validate(row) for row in by_thread],
            by_tool=[NamedCount.model_validate(row) for row in by_tool],
            by_skill=[NamedCount.model_validate(row) for row in by_skill],
        )
