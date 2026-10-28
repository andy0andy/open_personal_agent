"""运行失败的类型（设计 2026-10-23 4.5）：报错卡片按类型给按钮，不再靠文字开头去认。"""

import pytest

from agents.main_agent.models import ModelStalledError, classify_failure


class _StatusError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(Exception):  # 与 litellm 的同名：只按类名认
    pass


class APIConnectionError(Exception):
    pass


class ContextWindowExceededError(Exception):
    pass


def _wrapped(error: Exception) -> Exception:
    try:
        raise RuntimeError("调用失败") from error
    except RuntimeError as outer:
        return outer


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (Exception("insufficient_quota: You exceeded your current quota"), "quota"),
        (ModelStalledError(3), "stalled"),
        (RateLimitError("slow down"), "rate_limit"),
        (_StatusError("Too Many Requests", 429), "rate_limit"),
        (APIConnectionError("connection refused"), "gateway"),
        (_StatusError("Service Unavailable", 503), "gateway"),
        (ContextWindowExceededError("too long"), "context_overflow"),
        (Exception("prompt is too long: 1200000 tokens > 1000000 maximum"), "context_overflow"),
        (Exception("This model's maximum context length is 128000 tokens"), "context_overflow"),
        (ValueError("x"), "other"),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_failures_are_classified(error: Exception, kind: str) -> None:
    assert classify_failure(error) == kind


def test_wrapped_errors_are_classified_by_their_cause() -> None:
    assert classify_failure(_wrapped(_StatusError("Too Many Requests", 429))) == "rate_limit"
    assert classify_failure(_wrapped(ModelStalledError(3))) == "stalled"


def test_interrupted_is_never_guessed() -> None:
    """ "被打断"只由后端在停机、重启时标上，从异常认不出来。"""
    assert classify_failure(RuntimeError("服务停止")) == "other"
