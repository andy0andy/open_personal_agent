"""用量统计接口（设计文档 12.1 GET /usage/summary，13.3 用量统计页）。"""

from datetime import date
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query
from pydantic import BaseModel

from agents.main_agent.usage import (
    CallerUsage,
    DayUsage,
    ModelUsageSummary,
    NamedCount,
    ThreadUsageSummary,
    UsageBucket,
)
from backend.api.deps import ServicesDep
from common.errors import InvalidRequestError

usage_router = APIRouter(prefix="/usage")


class ThreadUsageView(ThreadUsageSummary):
    title: str | None  # 为空表示会话已删除（用量仍计入）


class UsageSummaryView(BaseModel):
    since: date
    until: date
    total: UsageBucket
    by_day: list[DayUsage]
    by_model: list[ModelUsageSummary]
    by_caller: list[CallerUsage]
    by_thread: list[ThreadUsageView]
    by_tool: list[NamedCount]  # 工具、技能各用了几次（设计 2026-10-23 6.8）
    by_skill: list[NamedCount]


@usage_router.get("/summary")
async def usage_summary(
    services: ServicesDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    tz: Annotated[str, Query(max_length=64)] = "UTC",
) -> UsageSummaryView:
    """最近 days 天（含今天）的用量；按天分组用 tz 时区（浏览器所在时区）的日期。"""
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidRequestError(f"时区不认识：{tz}") from exc
    summary = await services.usage.summary(days=days, tz=zone)
    titles = await services.threads.titles([t.thread_id for t in summary.by_thread])
    return UsageSummaryView(
        **summary.model_dump(exclude={"by_thread"}),
        by_thread=[
            ThreadUsageView(**t.model_dump(), title=titles.get(t.thread_id))
            for t in summary.by_thread
        ],
    )
