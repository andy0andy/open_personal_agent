"""判断模型调用失败是不是"额度用完"（D23）：各家写法不同，频率限制不能误判。"""

import pytest

from agents.main_agent.models import is_quota_exhausted


class _StatusError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class BudgetExceededError(Exception):
    """与 litellm 的异常同名：按类名识别。"""


def _wrapped(inner: BaseException) -> BaseException:
    """外面再包一层（经网关、经 LangChain 时常见）。"""
    try:
        try:
            raise inner
        except BaseException as exc:
            raise RuntimeError("模型调用失败") from exc
    except RuntimeError as outer:
        return outer


QUOTA_ERRORS = [
    _StatusError("Payment Required", 402),
    BudgetExceededError("over budget"),
    Exception("Error code: 429 - {'error': {'type': 'insufficient_quota'}}"),
    Exception("You exceeded your current quota, please check your plan and billing details."),
    Exception("Your credit balance is too low to access the Anthropic API."),
    Exception("Budget has been exceeded! Current cost: 10.2, Max budget: 10.0"),
    Exception("账户余额不足，请充值"),
    Exception("本月额度已用完"),
    # LiteLLM 网关自己的预算超限（v1.105.0 proxy/auth/auth_checks.py），
    # 经网关转发后只剩文字（终审 I1）
    Exception("ExceededBudget: User=u1 over budget. Spend=10.5, Budget=10.0"),
    Exception("ExceededBudget: Key over 30d budget. Spend=3.2, Budget=3.0"),
    Exception("ExceededBudget: Team=t1 over 1d budget. Spend=5.1, Budget=5.0"),
    Exception("Error code: 400 - {'error': {'type': 'budget_exceeded', 'code': '400'}}"),
]


@pytest.mark.parametrize("error", QUOTA_ERRORS, ids=lambda e: type(e).__name__ + str(e)[:20])
def test_quota_errors_are_recognised(error: BaseException) -> None:
    assert is_quota_exhausted(error)
    assert is_quota_exhausted(_wrapped(error))


def test_rate_limit_is_not_quota() -> None:
    assert not is_quota_exhausted(_StatusError("Rate limit reached for requests per min", 429))
    assert not is_quota_exhausted(RuntimeError("upstream exploded"))


def test_gemini_rate_limit_is_not_quota() -> None:
    """Gemini 的频率限制也写着 exceeded your current quota（终审 I1）。

    但它带 rate-limits 链接、让几秒后重试：过一会儿就好，不是额度用完。
    """
    error = _StatusError(
        "You exceeded your current quota, please check your plan and billing details. "
        "For more information on this error, head to: "
        "https://ai.google.dev/gemini-api/docs/rate-limits. Please retry in 6.5s.",
        429,
    )
    assert not is_quota_exhausted(error)
    assert not is_quota_exhausted(_wrapped(error))


def test_terminal_quota_exhausted_counts_as_quota() -> None:
    """有的上游用错误类型 terminal_quota_exhausted 表示额度用完（设计 2026-10-23 4.4）。"""
    error = Exception("Error code: 429 - {'error': {'type': 'terminal_quota_exhausted'}}")
    assert is_quota_exhausted(error)
    assert is_quota_exhausted(_wrapped(error))


def test_hard_billing_limit_counts_as_quota() -> None:
    error = Exception("You have reached your hard billing limit for this month")
    assert is_quota_exhausted(error)
    assert is_quota_exhausted(_wrapped(error))
