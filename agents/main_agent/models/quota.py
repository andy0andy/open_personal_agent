"""判断模型调用失败是不是"额度用完"（D23）：用完了就结束这次运行，提示充值后说"继续"。

各家写法不同（OpenAI 的 insufficient_quota、Anthropic 的 credit balance、
LiteLLM 网关的 ExceededBudget / Budget has been exceeded、有的上游的 terminal_quota_exhausted
与 hard billing limit、中文的余额不足），
所以按状态码、异常类名与报错文字一起判断。
普通的频率限制（429 rate limit）过一会儿就好，不能当成额度用完。
"""

# 出现任何一个就是额度用完
_QUOTA_WORDS = (
    "insufficient_quota",
    "insufficient quota",
    "credit balance",
    "exceededbudget",  # LiteLLM 网关：ExceededBudget: User=… over budget（终审 I1）
    "budget has been exceeded",
    "budget exceeded",
    "budget_exceeded",  # LiteLLM 网关报错的 type
    "payment required",
    "terminal_quota_exhausted",  # 设计 2026-10-23 4.4（借鉴 Hermes 的识别清单）
    "hard billing limit",
    "余额不足",
    "额度不足",
    "额度已用完",
)
# OpenAI 额度用完时这么写，Gemini 的频率限制也这么写（带 rate-limits 链接、让几秒后重试）：
# 同时出现频率限制的字样时不算额度用完（终审 I1）
_AMBIGUOUS = "exceeded your current quota"
_RATE_LIMIT_WORDS = ("rate-limit", "rate limit", "per minute", "retry in", "try again in")
_MAX_DEPTH = 5  # 往里查几层被包起来的异常（防止循环引用）


def is_quota_exhausted(error: BaseException) -> bool:
    """异常本身或它包着的原因里，有一层说明额度用完了。"""
    current: BaseException | None = error
    for _ in range(_MAX_DEPTH):
        if current is None:
            return False
        if _says_quota(current):
            return True
        current = current.__cause__ or current.__context__
    return False


def _says_quota(error: BaseException) -> bool:
    if getattr(error, "status_code", None) == 402:
        return True
    if type(error).__name__ == "BudgetExceededError":
        return True
    text = str(error).lower()
    if any(word in text for word in _QUOTA_WORDS):
        return True
    return _AMBIGUOUS in text and not any(word in text for word in _RATE_LIMIT_WORDS)
