"""运行失败的类型（设计 2026-10-23 4.5）：报错卡片按类型给按钮，不再靠报错文字的开头去认。

各家异常类与写法不同，所以按异常类名、状态码与报错文字一起判断，并顺着被包起来的原因往里查。
"被打断"（服务停止、重启）由后端标上，从异常认不出来。
"""

from typing import Literal

from agents.main_agent.models.base import ModelStalledError
from agents.main_agent.models.quota import is_quota_exhausted

type ErrorKind = Literal[
    "quota", "rate_limit", "stalled", "gateway", "context_overflow", "interrupted", "other"
]

_MAX_DEPTH = 5  # 往里查几层被包起来的异常（防止循环引用）
_OVERFLOW_CLASSES = frozenset({"ContextWindowExceededError", "ContextOverflowError"})
_OVERFLOW_WORDS = (
    "context length",
    "context_length_exceeded",
    "prompt is too long",
    "maximum context length",
    "context window",
)
_RATE_LIMIT_CLASSES = frozenset({"RateLimitError"})
_GATEWAY_CLASSES = frozenset(
    {
        "APIConnectionError",
        "ServiceUnavailableError",
        "InternalServerError",
        "BadGatewayError",
        "Timeout",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
    }
)


def classify_failure(error: BaseException) -> ErrorKind:
    """运行失败属于哪一类；认不出时为 other。"""
    if is_quota_exhausted(error):
        return "quota"
    chain = _chain(error)
    if any(isinstance(item, ModelStalledError) for item in chain):
        return "stalled"
    if any(_overflow(item) for item in chain):
        return "context_overflow"
    if any(_rate_limited(item) for item in chain):
        return "rate_limit"
    if any(_gateway(item) for item in chain):
        return "gateway"
    return "other"


def _chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(chain) < _MAX_DEPTH:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _overflow(error: BaseException) -> bool:
    text = str(error).lower()
    return type(error).__name__ in _OVERFLOW_CLASSES or any(w in text for w in _OVERFLOW_WORDS)


def _rate_limited(error: BaseException) -> bool:
    return type(error).__name__ in _RATE_LIMIT_CLASSES or _status(error) == 429


def _gateway(error: BaseException) -> bool:
    status = _status(error)
    return type(error).__name__ in _GATEWAY_CLASSES or (status is not None and status >= 500)


def _status(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    return status if isinstance(status, int) else None
