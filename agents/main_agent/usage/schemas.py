"""用量的数据结构：只算 token，不算费用（设计 2026-10-19 4.11）。

输入 = 实际发给模型的全部输入（含命中缓存的部分）。缓存读写只在每次调用的明细里，汇总不单列。
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agents.main_agent.runtime import UsageTotals


class UsageRecord(BaseModel):
    """一次模型调用的明细。"""

    caller: str
    requested_model: str
    actual_model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    duration_ms: int
    created_at: datetime


class ModelUsage(BaseModel):
    """按实际模型版本汇总。"""

    model: str
    calls: int
    input_tokens: int
    output_tokens: int


class ThreadUsage(BaseModel):
    """一个会话的累计用量：合计与按模型版本拆分。"""

    total: UsageTotals
    by_model: list[ModelUsage]


class UsageBucket(BaseModel):
    """一组调用的合计：调用次数、输入、输出。"""

    # 导出的类型定义里，有默认值的字段也标为必有：输出的数据总带着它们
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class DayUsage(UsageBucket):
    day: date  # 用户所在时区的日期


class ModelUsageSummary(UsageBucket):
    model: str  # 实际调用的模型版本


class CallerUsage(UsageBucket):
    caller: str  # main、子智能体名、title、memory_extraction、compaction、embedding


class ThreadUsageSummary(UsageBucket):
    thread_id: UUID


class NamedCount(BaseModel):
    """工具或技能用了几次（设计 2026-10-23 6.8）。"""

    name: str
    count: int


class UsageSummary(BaseModel):
    """一段时间的用量汇总（设计文档 12.1 GET /usage/summary）。"""

    since: date
    until: date  # 含当天
    total: UsageBucket
    by_day: list[DayUsage]  # 只有有调用的日子
    by_model: list[ModelUsageSummary]  # 按 token 从多到少（调用方、会话同样）
    by_caller: list[CallerUsage]
    by_thread: list[ThreadUsageSummary]  # 用量最多的 10 个会话；不属于会话的调用不在其中
    # 工具、技能各用了几次（设计 2026-10-23 6.8），从多到少
    by_tool: list[NamedCount] = []
    by_skill: list[NamedCount] = []
